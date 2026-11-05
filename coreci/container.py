"""Isolated hook execution followed by independent output inspection."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, "/core_ci")
from contract import canonical, file_hash, package_metadata, read_json, regular_file, require, versions, write_json


def inspect(args, target, environment):
    root = Path("/output")
    declared = read_json(root / "outputs.json")
    require(set(declared) <= {"packages", "development_export", "summary"}, "unknown outputs field")
    require(isinstance(declared["packages"], list) and declared["packages"], "no packages produced")
    files = {}
    fmt = target["build"]["format"]
    encoded = versions(args.tag, int(args.revision), fmt)
    if fmt == "apk":
        os.environ["CORE_CI_APK"] = "/sdk/staging_dir/host/bin/apk"
    for item in declared["packages"]:
        require(set(item) == {"file", "component"}, "invalid output description")
        name = item["file"]
        require("/" not in name and name.endswith("." + fmt) and name not in files, "invalid package output")
        path = regular_file(root, name)
        actual = package_metadata(path, fmt)
        require(actual["name"] == item["component"] and
                (actual["name"] == args.package or actual["name"].startswith(args.package + "-")), "package name mismatch")
        require(actual["version"] == encoded["full"], "package version/release mismatch")
        require(actual["arch"] in (target["arch"], "all", "noarch"), "package architecture mismatch")
        files[name] = file_hash(path)
    if declared.get("development_export"):
        require(target["family"] == "openwrt" and declared["development_export"] == "development.tar.gz",
                "unexpected development export")
        # Inspect and bind SDK identity without running anything from the export.
        from contract import extract_archive
        import tarfile

        export = regular_file(root, "development.tar.gz")
        expanded = Path("/work/development")
        extract_archive(export, expanded, "tar")
        write_json(expanded / "coreci-sdk.json", {"file": Path(environment["sdk"]["url"]).name,
                                               "sha256": environment["sdk"]["sha256"]})
        with tarfile.open(export, "w:gz") as archive:
            for child in sorted(expanded.iterdir()):
                archive.add(child, arcname=child.name)
        files[export.name] = file_hash(export)
    require({p.name for p in root.iterdir()} == set(files) | {"outputs.json"}, "unexpected output files")
    manifest = {"build_id": args.build_id, "package": args.package, "version": args.version,
                "revision": int(args.revision), "target": target["id"], "feed": args.feed,
                "entry": target, "files": files}
    if target["family"] == "openwrt":
        manifest["sdk"] = {"file": Path(environment["sdk"]["url"]).name, "sha256": environment["sdk"]["sha256"]}
    (root / "outputs.json").unlink()
    write_json(root / "manifest.json", manifest)


def hook(args, target, environment):
    require(os.getuid() == 1000 and os.getgid() == 1000, "hooks require isolated unprivileged user")
    source = Path("/work/source")
    shutil.copytree("/source", source, symlinks=True)
    ci = Path("/definition")
    definition = read_json(ci / "ci/packages.json")
    path = (ci / definition["build"][target["family"]]).resolve()
    require(path.is_relative_to(ci) and path.is_file(), "hook escapes recipe checkout")
    encoded = versions(args.tag, int(args.revision), target["build"]["format"])
    values = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/work", "LANG": "C.UTF-8",
              "SOURCE_DIR": str(source), "CI_DIR": str(ci), "TARGET_JSON": "/target.json", "OUTPUT_DIR": "/output",
              "SOURCE_VERSION": args.tag, "SOURCE_TAG": args.tag, "PACKAGE_NAMESPACE": args.package,
              "PACKAGE_UPSTREAM_VERSION": encoded["version"], "PACKAGE_REVISION": args.revision,
              "PREREQUISITES_DIR": "/prerequisites"}
    if target["family"] == "openwrt":
        sdk_root = Path("/work/sdk")
        shutil.copytree("/sdk", sdk_root, symlinks=True)
        staging = sdk_root / environment["staging_dir"]
        require(staging.resolve().is_relative_to(sdk_root) and staging.is_dir(), "invalid staging directory")
        for directory in Path("/prerequisites").iterdir():
            development = directory / "development"
            for file in development.rglob("*"):
                destination = staging / "usr" / file.relative_to(development)
                require(file.is_dir() or not destination.exists(), "development export overwrites SDK")
            shutil.copytree(development, staging / "usr", dirs_exist_ok=True)
        values.update(SDK_DIR=str(sdk_root), SDK_STAGING_DIR=str(staging))
        if target["build"]["format"] == "apk":
            values["CORE_CI_APK"] = str(sdk_root / "staging_dir/host/bin/apk")
    subprocess.run(["/bin/sh", str(path)], cwd=source, env=values, check=True, timeout=21000)


def main():
    parser = argparse.ArgumentParser()
    for name in ("tag", "version", "revision", "package", "build-id", "feed"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--inspect", action="store_true")
    args = parser.parse_args()
    target = read_json("/target.json")
    environment = read_json("/environment.json")
    if args.inspect:
        inspect(args, target, environment)
    else:
        hook(args, target, environment)


if __name__ == "__main__":
    main()
