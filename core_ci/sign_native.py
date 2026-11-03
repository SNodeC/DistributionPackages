"""Trusted native feed update. Never invokes hooks, package scripts or installed packages."""

import argparse
from contextlib import contextmanager
import gzip
import os
from pathlib import Path
import re
import shutil
import shlex
import stat
import subprocess
import tempfile

from contract import (
    assignment,
    publication_receipt,
    digest,
    file_hash,
    output,
    read_json,
    relative_path,
    require,
    run,
    verify_manifest,
    write_json,
)


def fingerprints(text):
    result = []
    primary = False
    for line in text.splitlines():
        fields = line.split(":")
        if fields[0] in ("pub", "sec"):
            primary = True
        elif fields[0] in ("sub", "ssb"):
            primary = False
        elif fields[0] == "fpr" and primary:
            result.append(fields[9])
            primary = False
    return result


@contextmanager
def signing_key(private_key, passphrase, public_key, expected, temporary_root):
    require(re.fullmatch(r"(?:[A-F0-9]{40}|[A-F0-9]{64})", expected) is not None, "invalid trusted fingerprint")
    for file in [private_key] + ([passphrase] if passphrase else []):
        require(
            stat.S_IMODE(Path(file).stat().st_mode) & 0o077 == 0,
            "private key/passphrase files require owner-only permissions",
        )
    with tempfile.TemporaryDirectory(prefix="core-ci-keyring-", dir=temporary_root) as temporary:
        home = Path(temporary)
        home.chmod(0o700)
        gpg = ["gpg", "--homedir", str(home), "--batch", "--no-tty"]
        try:
            public = output(gpg + ["--with-colons", "--show-keys", str(public_key)])
            require(fingerprints(public) == [expected], "trusted public key does not match configured fingerprint")
            run(gpg + ["--import", str(private_key)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            secret = output(gpg + ["--with-colons", "--list-secret-keys"])
            require(fingerprints(secret) == [expected], "private signing key does not match trusted public key")
            public_export = home / "trusted.gpg"
            with public_export.open("wb") as outgoing:
                subprocess.run(
                    gpg + ["--export", expected], check=True, stdout=outgoing, stderr=subprocess.PIPE, timeout=30
                )
            arguments = gpg + ["--yes", "--pinentry-mode", "loopback", "--local-user", expected]
            if passphrase:
                arguments += ["--passphrase-file", str(passphrase)]
            yield home, arguments, public_export
        finally:
            subprocess.run(
                ["gpgconf", "--homedir", str(home), "--kill", "all"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def sign_file(gpg, keyring, file, clear=False):
    signature = Path(str(file) + (".inrelease" if clear else ".gpg"))
    run(
        gpg
        + (["--armor"] if not clear else [])
        + ["--output", str(signature), "--clearsign" if clear else "--detach-sign", str(file)],
        stderr=subprocess.PIPE,
    )
    arguments = ["gpgv", "--keyring", str(keyring), str(signature)]
    if not clear:
        arguments.append(str(file))
    run(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return signature


def feed_component(value):
    require(
        isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", value) is not None,
        "unsafe feed coordinate",
    )
    return value


def receipt_path(selected):
    result = "receipts/" + selected["execution"] + "/" + str(selected["revision"]) + ".json"
    return result


def retained_receipt(selected, build_result, publication_run, feed):
    receipt = None
    path = Path(feed) / receipt_path(selected)
    if path.exists():
        receipt = read_json(path)
        require(
            receipt["assignment_sha256"] == digest(selected)
            and receipt["build_result"] == build_result
            and receipt["run"] == publication_run,
            "conflicting publication replay",
        )
        # Index paths are mutable across later publications; package/export bytes are immutable.
        objects = list(receipt["packages"])
        if receipt.get("development_export"):
            objects.append(receipt["development_export"])
        for item in objects:
            relative_path(item["path"])
            file = Path(feed) / item["path"]
            require(
                file.is_file()
                and not file.is_symlink()
                and file.stat().st_size == item["size"]
                and file_hash(file) == item["sha256"],
                "retained publication bytes changed",
            )
    return receipt


def file_identity(feed, path):
    path = Path(path)
    result = {"path": str(path.relative_to(feed)), "size": path.stat().st_size, "sha256": file_hash(path)}
    return result


def add_new(source, destination):
    require(
        not destination.exists() and not destination.is_symlink(),
        "published package identity already exists; reserve a new rebuild revision",
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def publish_key(feed, public_key):
    destination = feed / "keys" / Path(public_key).name
    destination.parent.mkdir(exist_ok=True)
    if destination.exists():
        require(
            file_hash(destination) == file_hash(public_key),
            "deployed verification key differs; rotation needs owner approval",
        )
    else:
        shutil.copyfile(public_key, destination)


def publish_export(feed, selected, manifest, artifacts):
    result = None
    if manifest["development_export"]:
        export = manifest["development_export"]
        destination = feed / "exports" / selected["execution"] / str(selected["revision"]) / "development.tar.gz"
        add_new(Path(artifacts) / export["file"], destination)
        result = {**export, **file_identity(feed, destination)}
    return result


def update(
    selected, build_result, publication_run, artifacts, feed, private_key, passphrase, public_key, temporary_root
):
    feed = Path(feed).resolve()
    require(feed.is_dir(), "feed checkout is required")
    receipt = retained_receipt(selected, build_result, publication_run, feed)
    if receipt is None:
        manifest = verify_manifest(selected, artifacts, build_result)
        package_format = selected["target"]["build"]["format"]
        require(package_format in ("deb", "rpm"), "this publisher supports native packages only")
        target = selected["target"]
        distribution = feed_component(target["distribution"])
        suite = feed_component(target["suite"])
        arch = feed_component(target["arch"])
        expected = selected["source"]["deployment"]["signing"]["gpg_fingerprint"]
        receipt = publication_receipt(selected, build_result, publication_run, manifest)
        with signing_key(private_key, passphrase, public_key, expected, temporary_root) as (key_home, gpg, keyring):
            rpmdb = key_home / "rpmdb"
            rpmdb.mkdir()
            if package_format == "rpm":
                run(["rpmkeys", "--dbpath", str(rpmdb), "--import", str(public_key)], stderr=subprocess.PIPE)
            for package in manifest["packages"]:
                filename = (
                    f"{package['name']}_{package['version']}_{package['arch']}.deb" if package_format == "deb"
                    else f"{package['name']}-{package['version']}.{package['arch']}.rpm"
                )
                relative_path(filename)
                folder = (
                    distribution + "/pool/" + suite
                    if package_format == "deb"
                    else distribution + "/" + suite + "/" + arch + "/Packages"
                )
                file = feed / folder / filename
                add_new(Path(artifacts) / package["file"], file)
                if package_format == "rpm":
                    extra = "--pinentry-mode loopback" + (
                        " --passphrase-file " + shlex.quote(str(passphrase)) if passphrase else ""
                    )
                    run(
                        [
                            "rpmsign",
                            "--define",
                            "_gpg_name " + expected,
                            "--define",
                            "_openpgp_sign_id " + expected,
                            "--define",
                            "_gpg_path " + str(key_home),
                            "--define",
                            "_gpg_sign_cmd_extra_args " + extra,
                            "--addsign",
                            str(file),
                        ],
                        stderr=subprocess.PIPE,
                    )
                    checked = output(["rpmkeys", "--dbpath", str(rpmdb), "--checksig", "--verbose", str(file)])
                    require(
                        "signature" in checked.lower()
                        and "OK" in checked
                        and "NOT OK" not in checked
                        and "NOKEY" not in checked,
                        "RPM signature verification failed",
                    )
                receipt["packages"].append(
                    {**package, **file_identity(feed, file), "file": filename, "unsigned_sha256": package["sha256"]}
                )
            publish_key(feed, public_key)
            if package_format == "deb":
                indexes = apt_indexes(feed, distribution, suite, arch, gpg, keyring)
            else:
                indexes = rpm_indexes(feed, distribution, suite, arch, gpg, keyring)
            receipt["indexes"] = [file_identity(feed, path) for path in indexes]
            receipt["development_export"] = publish_export(feed, selected, manifest, artifacts)
        path = feed / receipt_path(selected)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, receipt)
    return receipt


def apt_indexes(feed, distribution, suite, arch, gpg, keyring):
    root = feed / distribution
    relative = Path("dists") / suite
    binary = root / relative / "main" / ("binary-" + arch)
    binary.mkdir(parents=True, exist_ok=True)
    packages = binary / "Packages"
    # apt-ftparchive reads actual retained control records; restrict the affected architecture.
    with packages.open("wb") as outgoing:
        subprocess.run(
            ["apt-ftparchive", "--arch", arch, "packages", "pool/" + suite],
            cwd=root,
            check=True,
            stdout=outgoing,
            stderr=subprocess.PIPE,
            timeout=120,
        )
    with packages.open("rb") as incoming, (binary / "Packages.gz").open("wb") as outgoing:
        with gzip.GzipFile(fileobj=outgoing, mode="wb", mtime=0) as compressed:
            shutil.copyfileobj(incoming, compressed)
    release = root / relative / "Release"
    release.unlink(missing_ok=True)
    (release.parent / "Release.gpg").unlink(missing_ok=True)
    (release.parent / "InRelease").unlink(missing_ok=True)
    architectures = " ".join(
        sorted(path.name.removeprefix("binary-") for path in (release.parent / "main").glob("binary-*"))
    )
    with release.open("wb") as outgoing:
        subprocess.run(
            [
                "apt-ftparchive",
                "-o",
                "APT::FTPArchive::Release::Suite=" + suite,
                "-o",
                "APT::FTPArchive::Release::Codename=" + suite,
                "-o",
                "APT::FTPArchive::Release::Components=main",
                "-o",
                "APT::FTPArchive::Release::Architectures=" + architectures,
                "release",
                str(relative),
            ],
            cwd=root,
            check=True,
            stdout=outgoing,
            stderr=subprocess.PIPE,
            timeout=120,
        )
    signature = sign_file(gpg, keyring, release)
    signature.rename(release.parent / "Release.gpg")
    inline = sign_file(gpg, keyring, release, clear=True)
    inline.rename(release.parent / "InRelease")
    result = [packages, binary / "Packages.gz", release, release.parent / "Release.gpg", release.parent / "InRelease"]
    return result


def rpm_indexes(feed, distribution, suite, arch, gpg, keyring):
    root = feed / distribution / suite / arch
    run(["createrepo_c", "--update", "--retain-old-md=0", str(root)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    repomd = root / "repodata/repomd.xml"
    signature = sign_file(gpg, keyring, repomd)
    signature.rename(repomd.parent / "repomd.xml.asc")
    result = [path for path in (root / "repodata").iterdir() if path.is_file()]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assignment", required=True)
    parser.add_argument("--assignment-sha256", required=True)
    parser.add_argument("--build-result", required=True)
    parser.add_argument("--publication-run", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--feed", required=True)
    parser.add_argument("--private-key-file", required=True)
    parser.add_argument("--passphrase-file")
    parser.add_argument("--public-key-file", required=True)
    parser.add_argument("--temporary-root", required=True)
    arguments = parser.parse_args()
    selected = assignment(arguments.assignment, arguments.assignment_sha256)
    update(
        selected,
        read_json(arguments.build_result),
        read_json(arguments.publication_run),
        arguments.artifacts,
        arguments.feed,
        arguments.private_key_file,
        arguments.passphrase_file,
        arguments.public_key_file,
        arguments.temporary_root,
    )


if __name__ == "__main__":
    main()
