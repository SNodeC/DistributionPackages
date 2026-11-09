"""Acquire an untrusted SDK archive; existing preparation verifies it again."""
import argparse
import os
import platform
import re
import resource
import shutil
import tarfile
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit

from .contract import file_hash, read_json, require, output, run
from .environment import sdk
from .common import github_outputs, inputs, select


def cache_path(environment):
    name = Path(urlsplit(environment["sdk"]["url"]).path).name
    return Path(os.environ["RUNNER_TEMP"]) / "coreci-sdk" / name


def acquire(environment, archive):
    archive = Path(archive)
    valid = archive.is_file() and not archive.is_symlink() and archive.stat().st_size <= 1024**3
    valid = valid and file_hash(archive) == environment["sdk"]["sha256"]
    if not valid:
        if archive.exists() or archive.is_symlink():
            archive.unlink()
        archive.parent.mkdir(parents=True, exist_ok=True)
        partial = archive.with_name(archive.name + ".part")
        command = [
            "curl", "--fail", "--location", "--show-error", "--continue-at", "-",
            "--retry", "5", "--retry-all-errors", "--connect-timeout", "30",
            "--speed-limit", "1024", "--speed-time", "120", "--retry-max-time", "5400",
            "--max-filesize", str(1024**3), "--output", str(partial),
            "--write-out", "SDK transfer: bytes=%{size_download} speed=%{speed_download} url=%{url_effective}\n",
            environment["sdk"]["url"],
        ]
        deadline = time.monotonic() + 5400
        downloaded = False
        while not downloaded:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "SDK download exceeded 90 minutes")
            previous = partial.stat().st_size if partial.exists() else 0
            try:
                subprocess.run(command, check=True, timeout=remaining)
                downloaded = True
            except subprocess.CalledProcessError:
                # curl resets to its initial offset on internal retries. Continue
                # from retained bytes only if those retries made forward progress.
                if not partial.exists() or partial.stat().st_size <= previous:
                    raise
        valid = partial.is_file() and partial.stat().st_size <= 1024**3
        valid = valid and file_hash(partial) == environment["sdk"]["sha256"]
        if not valid:
            partial.unlink(missing_ok=True)
        require(valid, "SDK checksum mismatch")
        partial.replace(archive)
    return archive


def prepare(target, environment, destination):
    archive = os.environ.get("CORECI_SDK_ARCHIVE") or str(cache_path(environment))
    verified = acquire(environment, archive)
    return prepare_sdk(target, environment, destination, archive=verified)


def cache(manifest=None):
    target = (read_json(manifest)["entry"] if manifest else
              select(read_json(Path("recipe/ci/packages.json")), inputs("build")["target"]))
    arch = (target["arch"].split("_")[0] if manifest and target["family"] == "openwrt"
            else target["build"].get("platform", "linux/amd64").split("/")[1])
    aliases = {"x86": "amd64", "x86_64": "amd64", "aarch64": "arm64", "i386": "386", "powerpc": "ppc", "loongarch64": "loong64"}
    emulator = aliases.get(arch, arch)
    github_outputs(emulator="" if emulator == aliases.get(platform.machine(), platform.machine()) else emulator)
    if target["family"] == "openwrt":
        environment = sdk(target, target["build"]["release"])
        archive = cache_path(environment)
        github_outputs(archive=str(archive),
                       key="openwrt-sdk-" + archive.name + "-" + environment["sdk"]["sha256"])


def prepare_sdk(target, environment, destination, archive=None):
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest")
    cache(parser.parse_args().manifest)
