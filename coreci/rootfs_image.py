"""One-time OCI preparation from an explicitly pinned official disk image."""

import argparse
import json
import lzma
from pathlib import Path
import shutil
import subprocess
import tempfile

from .contract import file_hash, output, require


def prepare(specification, image, directory):
    archive = directory / "root.img.xz"
    subprocess.run(
        ["curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https",
         "--output", str(archive), specification["url"]], check=True, timeout=1200,
    )
    require(file_hash(archive) == specification["sha256"], "official disk image checksum mismatch")
    disk = directory / "root.img"
    with lzma.open(archive, "rb") as incoming, disk.open("wb") as outgoing:
        shutil.copyfileobj(incoming, outgoing)
    table = json.loads(output(["sfdisk", "--json", str(disk)]))["partitiontable"]
    roots = [partition for partition in table["partitions"] if partition["type"] == "83"]
    require(len(roots) == 1, "official disk image must contain exactly one Linux root partition")
    offset = roots[0]["start"] * table["sectorsize"]
    root = directory / "root"
    root.mkdir()
    subprocess.run(
        ["sudo", "mount", "-o", "loop,ro,noload,nodev,nosuid,noexec,offset=" + str(offset), str(disk), str(root)],
        check=True, timeout=60,
    )
    try:
        subprocess.run(
            ["sudo", "tar", "--numeric-owner", "--one-file-system", "-cf", str(directory / "rootfs.tar"),
             "-C", str(root), "."], check=True, timeout=600,
        )
    finally:
        subprocess.run(["sudo", "umount", str(root)], check=True, timeout=60)
    (directory / "Dockerfile").write_text(
        "FROM scratch\nADD rootfs.tar /\n"
        + "LABEL org.opencontainers.image.source=\"https://github.com/SNodeC/DistributionPackages\"\n"
        + "LABEL org.snodec.rootfs.sha256=\"" + specification["sha256"] + "\"\n"
        + "CMD [\"/bin/sh\"]\n"
    )
    (directory / ".dockerignore").write_text("*\n!Dockerfile\n!rootfs.tar\n")
    subprocess.run(
        ["docker", "build", "--platform", "linux/arm64", "--tag", image, str(directory)],
        check=True, timeout=1200,
    )
    subprocess.run(["docker", "push", image], check=True, timeout=1200)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["bookworm", "trixie"], required=True)
    arguments = parser.parse_args()
    specification = json.loads((Path(__file__).parents[1] / "rootfs-images.json").read_text())[arguments.suite]
    image = "ghcr.io/snodec/raspberrypios-" + arguments.suite + ":" + specification["sha256"]
    with tempfile.TemporaryDirectory(prefix="core-ci-rootfs-") as temporary:
        prepare(specification, image, Path(temporary))
    print(image)


if __name__ == "__main__":
    main()
