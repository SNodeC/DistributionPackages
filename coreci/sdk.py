"""Acquire an untrusted SDK archive; existing preparation verifies it again."""
import argparse
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit

from contract import file_hash, read_json, require
from environment import sdk
from sdk import prepare as prepare_sdk
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
            "--speed-limit", "1024", "--speed-time", "120", "--retry-max-time", "2700",
            "--max-filesize", str(1024**3), "--output", str(partial),
            "--write-out", "SDK transfer: bytes=%{size_download} speed=%{speed_download} url=%{url_effective}\n",
            environment["sdk"]["url"],
        ]
        deadline = time.monotonic() + 2700
        downloaded = False
        while not downloaded:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "SDK download exceeded 45 minutes")
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
    if target["family"] == "openwrt":
        environment = sdk(target, target["build"]["release"])
        archive = cache_path(environment)
        github_outputs(archive=str(archive),
                       key="openwrt-sdk-" + archive.name + "-" + environment["sdk"]["sha256"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest")
    cache(parser.parse_args().manifest)
