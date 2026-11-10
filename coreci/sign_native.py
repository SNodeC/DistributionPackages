"""Native signing and affected-directory index generation."""
from contextlib import contextmanager
import gzip
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from .contract import file_hash, output, require, run


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
    contents = subprocess.run(
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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    ).stdout
    release.write_bytes(contents)
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
