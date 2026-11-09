"""Manifest-bound publication; no source hook is ever imported or executed."""

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from .common import (checked_manifest, declaration, download, github_outputs, https, inputs, metadata,
                     public_key, registry, select, token, workflow, workflow_identity)
from .versions import versions
from contract import canonical, file_hash, output, read_json, regular_file, require
from github import api
from publish import prepare_commit
from .lease import push as checked_push, retry
from sign_native import apt_indexes, rpm_indexes, signing_key, sign_file


def provenance(values, settings):
    repo, path = workflow(settings["build"])
    require(repo.lower() == values["build_repo"].lower(), "build repository mismatch")
    result = api(f'/repos/{repo}/actions/runs/{values["build_run_id"]}', token())
    # The success callback is the last step of the build run, which may still be finishing.
    deadline = time.monotonic() + 300
    while result["status"] != "completed" and time.monotonic() < deadline:
        time.sleep(5)
        result = api(f'/repos/{repo}/actions/runs/{values["build_run_id"]}', token())
    require(result["repository"]["full_name"].lower() == repo.lower() and result["path"] == path
            and result["event"] == "workflow_dispatch" and result["conclusion"] == "success"
            and result["head_branch"] == os.environ["GITHUB_REF_NAME"], "build provenance mismatch")


def resolve(artifacts):
    values = inputs("publish")
    settings = registry()
    manifest = checked_manifest(Path(artifacts), values)
    feed = settings["feeds"][manifest["feed"]]
    repo, path = workflow(feed["publisher"])
    require(repo.lower() == os.environ["GITHUB_REPOSITORY"].lower() and
            workflow_identity(os.environ["GITHUB_WORKFLOW_REF"]) == workflow_identity(feed["publisher"]),
            "feed publisher mismatch")
    branch = metadata(feed["repository"])["default_branch"]
    owner, repository_name = feed["repository"].split("/")
    github_outputs(environment=feed["environment"], repository=feed["repository"], branch=branch,
                   owner=owner, repository_name=repository_name)


def ledger(manifest):
    return "".join(checksum + "  " + name + "\n" for name, checksum in sorted(manifest["files"].items()))


def immutable(feed, manifest, paths):
    relative = f'coreci/published/{manifest["target"]}/{manifest["package"]}_{manifest["version"]}-{manifest["revision"]}.sha256'
    destination = Path(feed) / relative
    repeated = destination.exists()
    if repeated:
        require(not destination.is_symlink() and destination.read_text() == ledger(manifest), "immutable: conflicting ledger")
    else:
        for path in paths:
            require(not (Path(feed) / path).exists() and not (Path(feed) / path).is_symlink(),
                    "immutable: existing target file without ledger")
    return relative, repeated


def badges(readme, settings, definitions):
    begin, end = "<!-- coreci:badges:begin -->", "<!-- coreci:badges:end -->"
    counts = (readme.count(begin), readme.count(end))
    require(counts in ((0, 0), (1, 1)), "invalid badge markers")
    targets = sorted({entry["id"] for doc in definitions for entry in doc["matrix"]})
    lines = [begin, "| Target | Packages |", "| --- | --- |"]
    for target in targets:
        names = sorted(doc["package"] for doc in definitions if any(t["id"] == target for t in doc["matrix"]))
        images = [f'![{name}]({settings["badges"].rstrip("/")}/{name}/{target}.svg)' for name in names]
        lines.append("| " + target + " | " + " ".join(images) + " |")
    block = "\n".join(lines + [end])
    padding = "" if readme.endswith("\n\n") else ("\n" if readme.endswith("\n") else "\n\n")
    result = readme + padding + block + "\n"
    if counts == (1, 1):
        start, finish = readme.index(begin), readme.index(end)
        require(start < finish, "reversed badge markers")
        result = readme[:start] + block + readme[finish + len(end):]
    return result


def targets(manifest, artifacts):
    entry = select({"matrix": [manifest["entry"]]}, manifest["target"])
    fmt = entry["build"]["format"]
    result = {}
    for name in manifest["files"]:
        if name != "development.tar.gz":
            require(name.endswith("." + fmt), "unexpected publication file")
            # The builder inspected identities; re-inspect independently at the signing boundary.
            from contract import package_metadata

            identity = package_metadata(regular_file(artifacts, name), fmt)
            package = manifest["package"]
            encoded = versions(manifest["version"], manifest["revision"], fmt, entry)
            require(identity["name"] == package or identity["name"].startswith(package + "-"), "package namespace mismatch")
            require(identity["version"] == encoded["full"] and identity["arch"] in (entry["arch"], "all", "noarch"),
                    "package metadata mismatch")
            if fmt == "deb":
                path = f'{entry["distribution"]}/pool/{entry["suite"]}/{identity["name"]}_{identity["version"]}_{identity["arch"]}.deb'
            elif fmt == "rpm":
                path = (f'{entry["distribution"]}/{entry["suite"]}/{entry["arch"]}/Packages/'
                        f'{identity["name"]}-{identity["version"]}.{identity["arch"]}.rpm')
            else:
                filename = (f'{identity["name"]}_{identity["version"]}_{identity["arch"]}.ipk' if fmt == "ipk"
                            else f'{identity["name"]}-{identity["version"]}.apk')
                path = f'openwrt/{entry["suite"]}/{entry["arch"]}/{filename}'
            require(path not in result.values(), "duplicate package destination")
            result[name] = path
    require(result, "no publication packages")
    if "development.tar.gz" in manifest["files"]:
        require(entry["family"] == "openwrt", "native export is not supported")
        encoded = versions(manifest["version"], manifest["revision"], fmt, entry)
        result["development.tar.gz"] = (f'dev/{entry["id"]}/{manifest["package"]}_{manifest["version"]}-'
                                        f'{encoded["release"]}.tar.gz')
    return result


@contextmanager
def secrets(work):
    files = {}
    try:
        for name in ("APT_SIGNING_KEY", "PACKAGES_GPG_PASSPHRASE", "OPENWRT_USIGN_KEY", "OPENWRT_APK_KEY"):
            value = os.environ.get(name, "")
            if value:
                path = Path(work) / name
                path.write_text(value)
                path.chmod(0o600)
                files[name] = path
        yield files
    finally:
        for path in files.values():
            path.unlink(missing_ok=True)


def snapshot(feed):
    result = {}
    for path in Path(feed).rglob("*"):
        relative = path.relative_to(feed)
        if ".git" not in relative.parts:
            if path.is_symlink():
                result[str(relative)] = ("symlink", os.readlink(path))
            elif path.is_file():
                result[str(relative)] = file_hash(path)
    return result


def availability(feed, paths, root):
    expected = {name: file_hash(Path(root) / name) for name in paths}
    deadline = time.monotonic() + 900
    pending = dict(expected)
    with tempfile.TemporaryDirectory() as temporary:
        while pending and time.monotonic() < deadline:
            for name in list(pending):
                try:
                    target = Path(temporary) / "object"
                    download(feed["url"] + name, target)
                    if file_hash(target) == pending[name]:
                        del pending[name]
                except (OSError, ValueError):
                    pass
            if pending:
                time.sleep(10)
    require(not pending, "feed availability timeout")


def publish(artifacts, root):
    return retry(root, lambda: publish_once(artifacts, root))


def publish_once(artifacts, root):
    values = inputs("publish")
    settings = registry()
    manifest = checked_manifest(Path(artifacts), values)
    feed = settings["feeds"][manifest["feed"]]
    repo, path = workflow(feed["publisher"])
    require(workflow_identity(feed["publisher"]) == workflow_identity(os.environ["GITHUB_WORKFLOW_REF"]), "publisher mismatch")
    root = Path(root).resolve()
    artifacts = Path(artifacts).resolve()
    branch = metadata(feed["repository"])["default_branch"]
    require(output(["git", "-C", str(root), "remote", "get-url", "origin"]).removesuffix(".git").lower()
            in ("https://github.com/" + feed["repository"].lower(), "git@github.com:" + feed["repository"].lower()),
            "feed checkout mismatch")
    base = output(["git", "-C", str(root), "rev-parse", "HEAD"])
    before = snapshot(root)
    entry = manifest["entry"]
    fmt = entry["build"]["format"]
    with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"], prefix="coreci-publish-") as temporary:
        work = Path(temporary)
        sdk_root = None
        if entry["family"] == "openwrt":
            from environment import sdk
            from .sdk import prepare

            environment = sdk(entry, entry["build"]["release"])
            sdk_root, _ = prepare(entry, environment, work / "sdk")
            require(manifest["sdk"] == {"file": Path(environment["sdk"]["url"]).name,
                                        "sha256": environment["sdk"]["sha256"]}, "publication SDK mismatch")
        paths = targets(manifest, artifacts)
        ledger_path, repeated = immutable(root, manifest, paths.values())
        if repeated:
            github_outputs(feed_commit=base)
        else:
            public_directory = work / "public"
            public_directory.mkdir()
            public = public_key(feed, "gpg", public_directory)
            key_home = work / "keyring"
            key_home.mkdir(mode=0o700)
            with secrets(work) as private, signing_key(private["APT_SIGNING_KEY"], private.get("PACKAGES_GPG_PASSPHRASE"), public,
                    feed["keys"]["gpg"]["fingerprint"].upper(), str(key_home)) as (home, gpg, keyring):
                for name, relative in paths.items():
                    destination = root / relative
                    require(destination.resolve().is_relative_to(root), "package destination escapes feed")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(artifacts / name, destination)
                if fmt == "rpm":
                    for name, relative in paths.items():
                        subprocess.run(["rpmsign", "--define", "_gpg_name " + feed["keys"]["gpg"]["fingerprint"],
                            "--define", "_gpg_path " + str(home), "--define", "_openpgp_sign_id " +
                            feed["keys"]["gpg"]["fingerprint"], "--define", "_gpg_sign_cmd_extra_args " +
                            shlex_passphrase(private.get("PACKAGES_GPG_PASSPHRASE")), "--addsign", str(root / relative)], check=True)
                if fmt in ("deb", "rpm"):
                    generator = apt_indexes if fmt == "deb" else rpm_indexes
                    indices = generator(root, entry["distribution"], entry["suite"], entry["arch"], gpg, keyring)
                else:
                    indices = openwrt_indices(root, entry, feed, paths, sdk_root, private, work)
                if "development.tar.gz" in paths:
                    directory = root / "dev" / entry["id"]
                    sums = directory / "SHA256SUMS"
                    sums.write_text("".join(file_hash(p) + "  " + p.name + "\n" for p in sorted(directory.glob("*.tar.gz"))))
                    signature = sign_file(gpg, keyring, sums)
                    signature.rename(directory / "SHA256SUMS.asc")
                    indices += [sums, directory / "SHA256SUMS.asc"]
                ledger_file = root / ledger_path
                ledger_file.parent.mkdir(parents=True, exist_ok=True)
                ledger_file.write_text(ledger(manifest))
                presentation_paths = set()
                if 'presentation' in feed:
                    from .presentation import receipt, refresh, status_fetch
                    presentation_paths.add(receipt(root, manifest, values, feed, paths))
                    try:
                        staged = work / 'presentation'
                        require(not (root / 'receipts').is_symlink(), 'status receipts cannot contain links')
                        shutil.copytree(root / 'receipts', staged / 'receipts', symlinks=True)
                        state = Path('coreci/presentation.json')
                        if (root / state).exists():
                            (staged / state).parent.mkdir(parents=True)
                            shutil.copyfile(root / state, staged / state)
                        rendered = refresh(staged, settings, manifest['feed'],
                            exists=lambda name: (root / name).is_file(), status=status_fetch(settings['status_url']))
                    except Exception as error:
                        with Path(os.environ.get('GITHUB_STEP_SUMMARY', os.devnull)).open('a') as summary:
                            summary.write(f'\n**Presentation warning:** {error}\n\nExisting presentation retained; publication continues.\n')
                    else:
                        for name in rendered:
                            destination = root / name
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(staged / name, destination)
                        presentation_paths.update(rendered)
                elif 'badges' in settings:
                    definitions = [declaration(repo) for repo in settings["repositories"]]
                    readme = root / "README.md"
                    contents = readme.read_bytes().decode("utf-8") if readme.exists() else ""
                    readme.write_bytes(badges(contents, settings, definitions).encode("utf-8"))
                    presentation_paths.add('README.md')
                from .validate import validate

                validation_key = public
                if entry["family"] == "openwrt":
                    kind = "usign" if fmt == "ipk" else "apk"
                    validation_key = public_directory / Path(feed["keys"][kind]["file"]).name
                validate(root, entry, list(paths.values()), validation_key, sdk_root)
                after = snapshot(root)
                allowed = set(paths.values()) | {ledger_path} | presentation_paths | {str(p.relative_to(root)) for p in indices}
                if fmt == "rpm":
                    prefix = f'{entry["distribution"]}/{entry["suite"]}/{entry["arch"]}/repodata/'
                    allowed |= {name for name in before if name.startswith(prefix)}
                changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
                require(changed <= allowed, "publication changed unrelated feed files")
                committed_base = prepare_commit(root, changed, orphan=True, removed=changed - after.keys())
                require(committed_base == base, "feed checkout changed during publication")
                commit = checked_push(root, branch, os.environ["GH_TOKEN"], base)
                availability(feed, [str(p.relative_to(root)) for p in indices], root)
                github_outputs(feed_commit=commit)


def shlex_passphrase(path):
    import shlex

    result = "--pinentry-mode loopback"
    if path:
        result += " --passphrase-file " + shlex.quote(str(path))
    return result


def openwrt_indices(root, entry, feed, paths, sdk_root, private, work):
    from sign_openwrt import indexes

    fmt = entry["build"]["format"]
    kind = "usign" if fmt == "ipk" else "apk"
    key = feed["keys"][kind]
    public = work / "public" / Path(key["file"]).name
    download(feed["url"] + key["file"], public, 1024**2)
    secret = private["OPENWRT_USIGN_KEY" if fmt == "ipk" else "OPENWRT_APK_KEY"]
    tool = str(sdk_root / "staging_dir/host/bin" / ("usign" if fmt == "ipk" else "apk"))
    keys = work / "openwrt-keys"
    keys.mkdir()
    shutil.copyfile(public, keys / public.name)
    if fmt == "ipk":
        require(output([tool, "-F", "-p", str(public)]).lower() == key["key_id"].lower(), "usign trust mismatch")
        require(output([tool, "-F", "-s", str(secret)]) == output([tool, "-F", "-p", str(public)]), "usign key mismatch")
    else:
        require(file_hash(public) == key["sha256"], "APK trust mismatch")
        public_der = output(["openssl", "pkey", "-pubin", "-in", str(public), "-pubout"])
        require(public_der == output(["openssl", "pkey", "-in", str(secret), "-pubout"]), "APK key mismatch")
        require("prime256v1" in output(["openssl", "pkey", "-pubin", "-in", str(public), "-text", "-noout"]),
                "APK key must use EC P-256")
        for relative in paths.values():
            if relative.endswith(".apk"):
                subprocess.run([tool, "--allow-untrusted", "adbsign", "--reset-signatures", "--sign", str(secret),
                                str(root / relative)], check=True)
                subprocess.run([tool, "--keys-dir", str(keys), "verify", str(root / relative)], check=True)
    folder = root / "openwrt" / entry["suite"] / entry["arch"]
    result = indexes(folder, fmt, sdk_root, tool, keys, secret, public)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("check-run", "resolve", "run"))
    parser.add_argument("--artifacts", default="packages")
    parser.add_argument("--feed", default="feed")
    args = parser.parse_args()
    if args.mode == "check-run":
        provenance(inputs("publish"), registry())
    elif args.mode == "resolve":
        resolve(args.artifacts)
    else:
        publish(args.artifacts, args.feed)


if __name__ == "__main__":
    main()
