"""Verified OpenWrt SDK preparation, used only by trusted GitHub worker code."""

import argparse
import json
import os
import re
from pathlib import Path
import resource
import shutil
import subprocess
import tarfile

from contract import SHA256, assignment, canonical, digest, file_hash, output, read_json, regular_file, relative_path, require, run, write_json


def prepare(target, environment, destination, archive=None):
    from environment import sdk

    print("SDK metadata start", flush=True)
    expected = sdk(target, environment["release"])
    require(
        all(environment[key] == value for key, value in expected.items()),
        "SDK identity differs from official release metadata",
    )
    print("SDK metadata verified", flush=True)
    destination = Path(destination)
    require(not destination.exists(), "SDK destination must be new")
    destination.mkdir()
    supplied = Path(archive) if archive is not None else None
    archive = destination / "sdk.archive"
    if supplied is not None:
        require(
            supplied.is_file() and not supplied.is_symlink() and supplied.stat().st_size <= 1024**3,
            "supplied SDK requires a regular file within 1 GiB",
        )
        shutil.copyfile(supplied, archive)
    else:
        subprocess.run(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--max-filesize",
                str(1024**3),
                "--output",
                str(archive),
                expected["sdk"]["url"],
            ],
            check=True,
            timeout=600,
        )
    require(
        archive.stat().st_size <= 1024**3 and file_hash(archive) == expected["sdk"]["sha256"], "SDK checksum mismatch"
    )
    print("SDK archive verified", flush=True)
    extracted = destination / "extracted"
    extract(archive, extracted, expected["sdk"]["url"].endswith(".zst"))
    print("SDK extraction completed", flush=True)
    roots = list(extracted.iterdir())
    require(len(roots) == 1 and roots[0].is_dir() and not roots[0].is_symlink(), "SDK archive requires one directory")
    root = roots[0]
    run(["make", "--no-print-directory", "-C", str(root), "defconfig"], preexec_fn=lambda: os.umask(0o022))
    query = destination / "query.mk"
    query.write_text("TOPDIR:=$(CURDIR)\nSDK:=1\ninclude $(TOPDIR)/rules.mk\ninclude $(TOPDIR)/include/version.mk\n")
    values = {}
    for variable in "ARCH_PACKAGES VERSION_NUMBER BOARD SUBTARGET STAGING_DIR TARGET_CROSS TOOLCHAIN_DIR".split():
        values[variable] = output(
            ["make", "--no-print-directory", "--silent", "-C", str(root), "-f", str(query.resolve()), "val." + variable]
        )
        require(bool(values[variable]) and "\n" not in values[variable], "SDK cannot report " + variable)
    require(
        values["ARCH_PACKAGES"] == target["arch"]
        and values["VERSION_NUMBER"] == environment["release"]
        and values["BOARD"] + "/" + values["SUBTARGET"] == target["build"]["target"],
        "extracted SDK target identity mismatch",
    )
    compiler = (Path(values["TOOLCHAIN_DIR"]) / "bin" / (values["TARGET_CROSS"] + "gcc")).resolve()
    require(compiler.is_relative_to(root.resolve()) and compiler.is_file(), "SDK compiler escapes verified SDK")
    identity = {
        "triple": output([str(compiler), "-dumpmachine"]),
        "version": output([str(compiler), "-dumpfullversion"]),
        "compiler_sha256": file_hash(compiler),
    }
    require("toolchain" not in environment or environment["toolchain"] == identity, "SDK toolchain changed")
    environment["toolchain"] = identity
    staging = Path(values["STAGING_DIR"]).resolve()
    require(staging.is_relative_to(root.resolve()), "SDK staging path escapes SDK")
    require(
        environment.get("staging_dir", str(staging.relative_to(root.resolve())))
        == str(staging.relative_to(root.resolve())),
        "SDK staging identity changed",
    )
    environment["staging_dir"] = str(staging.relative_to(root.resolve()))
    if target["build"]["format"] == "apk":
        tool = root / "staging_dir/host/bin/apk"
        require(
            tool.is_file() and output([str(tool), "--version"]).startswith("apk-tools 3."), "SDK requires apk-tools v3"
        )
        os.environ["CORE_CI_APK"] = str(tool)
    return root, staging.relative_to(root.resolve())


def extract(archive, destination, zstd=False):
    archive = Path(archive)
    temporary = archive.with_suffix(".tar")
    if zstd:
        with temporary.open("wb") as outgoing:
            subprocess.run(
                ["zstd", "--decompress", "--stdout", str(archive)],
                stdout=outgoing,
                check=True,
                timeout=300,
                preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024**3, 4 * 1024**3)),
            )
        archive = temporary
    try:
        with tarfile.open(archive, "r:*") as opened:
            members = []
            size = 0
            for index, item in enumerate(opened):
                size += item.size
                require(
                    index < 200000 and size <= 4 * 1024**3 and len(item.name) <= 1024,
                    "SDK archive exceeds resource bounds",
                )
                # Host bindings belong to the SDK builder; OpenWrt regenerates them for its current host.
                host_command = Path(item.name).parts[1:-1] == ("staging_dir", "host", "bin")
                if not (item.issym() and item.linkname.startswith("/") and host_command):
                    members.append(item)
            # Python's standard data filter rejects traversal, external links, devices and special files.
            opened.extractall(destination, members=members, filter="data")
    finally:
        temporary.unlink(missing_ok=True)


PUBLICATION_FILES = {
    "ipk": {"scripts/ipkg-make-index.sh", "staging_dir/host/bin/usign", "staging_dir/host/bin/.usign.bin",
            "staging_dir/host/bin/mkhash", "staging_dir/host/bin/.mkhash.bin",
            "staging_dir/host/lib/ld-linux-x86-64.so.2", "staging_dir/host/lib/runas.so"},
    "apk": {"staging_dir/host/bin/apk", "staging_dir/host/bin/.apk.bin",
            "staging_dir/host/lib/ld-linux-x86-64.so.2", "staging_dir/host/lib/runas.so"},
}


def publication_tools(root, selected, environment, destination):
    root, destination = Path(root).resolve(), Path(destination)
    destination.mkdir()
    pending, files = sorted(PUBLICATION_FILES[selected["target"]["build"]["format"]]), {}
    while pending:
        name = pending.pop()
        if name not in files:
            relative_path(name)
            source = (root / name).resolve()
            require(source.is_relative_to(root) and source.is_file(), "publication tool escapes verified SDK or is missing")
            require(len(files) < 32 and sum(item["size"] for item in files.values()) + source.stat().st_size <= 64 * 1024**2,
                    "publication tools exceed resource bounds")
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            files[name] = {"path": name, "size": target.stat().st_size, "sha256": file_hash(target)}
            if name.endswith(".bin") or name.startswith("staging_dir/host/lib/"):
                for library in re.findall(r"\(NEEDED\).*?\[([^]]+)\]", output(["readelf", "-d", "-W", str(source)])):
                    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*", library), "invalid SDK library name")
                    pending.append("staging_dir/host/lib/" + library)
    write_json(destination / "tools.json", {"schema": 1, "assignment_sha256": digest(selected),
               "execution": selected["execution"], "attempt": selected["attempt"], "target": selected["target"],
               "environment": environment, "files": [files[name] for name in sorted(files)]})
    return file_hash(destination / "tools.json")


def verified_tools(directory, expected_sha256, selected, environment):
    directory = Path(directory)
    manifest = regular_file(directory, "tools.json")
    require(SHA256.fullmatch(expected_sha256) and file_hash(manifest) == expected_sha256, "publication tools manifest hash mismatch")
    document = read_json(manifest, 65536)
    expected = {"schema": 1, "assignment_sha256": digest(selected), "execution": selected["execution"],
                "attempt": selected["attempt"], "target": selected["target"], "environment": environment}
    require(all(document[key] == value for key, value in expected.items()), "publication tools identity mismatch")
    require(isinstance(document["files"], list) and len(document["files"]) <= 32, "invalid publication tools listing")
    names, total = set(), 0
    for item in document["files"]:
        name = item["path"]
        require(name not in names and type(item["size"]) is int and item["size"] > 0 and SHA256.fullmatch(item["sha256"]),
                "invalid or duplicate publication tool")
        path = regular_file(directory, name)
        total += item["size"]
        require(total <= 64 * 1024**2 and path.stat().st_size == item["size"] and file_hash(path) == item["sha256"],
                "publication tool size/hash mismatch")
        names.add(name)
    require(PUBLICATION_FILES[selected["target"]["build"]["format"]] <= names and
            {str(path.relative_to(directory)) for path in directory.rglob("*") if not path.is_dir() or path.is_symlink()}
            == names | {"tools.json"}, "publication tools file set mismatch")
    for name in names:
        (directory / name).chmod(0o755)
    if selected["target"]["build"]["format"] == "apk":
        os.environ["CORE_CI_APK"] = str(directory / "staging_dir/host/bin/apk")
    return directory


def main():
    from validate import trusted_deployment

    parser = argparse.ArgumentParser()
    parser.add_argument("--assignment", required=True)
    parser.add_argument("--assignment-sha256", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    selected = assignment(arguments.assignment, arguments.assignment_sha256)
    trusted_deployment(selected)
    require(selected["execution"] == os.environ["EXECUTION"] and selected["attempt"] == os.environ["ATTEMPT"]
            and selected["target"]["family"] == "openwrt", "publication tools assignment mismatch")
    raw = canonical(selected["environment"]) if selected.get("kind") == "retention" else os.environ["CORE_CI_SDK_ENVIRONMENT"]
    require(len(raw.encode()) <= 16384 and "\n" not in raw and "\r" not in raw, "invalid SDK environment selector")
    environment = json.loads(raw)
    require(isinstance(environment, dict), "SDK environment selector must be an object")
    before = canonical(environment)
    root, _ = prepare(selected["target"], environment, Path(os.environ["RUNNER_TEMP"]) / "tools-sdk")
    require(canonical(environment) == before, "SDK preparation changed selected environment")
    tools_hash = publication_tools(root, selected, environment, arguments.output)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output_file:
        output_file.write("tools-sha256=" + tools_hash + "\n")


if __name__ == "__main__":
    main()
