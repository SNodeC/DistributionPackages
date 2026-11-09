"""Resolve native images and verified OpenWrt SDK metadata."""
import json
import os
import re
import subprocess
from .contract import output, require


def native(target):
    image = target["build"]["image"]
    platform = target["build"]["platform"]
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:/@_-]*", image), "unsupported image reference")
    require(re.fullmatch(r"linux/[a-z0-9_]+(?:/[a-z0-9_]+)?", platform), "unsupported image platform")
    subprocess.run(["docker", "pull", "--platform", platform, image], check=True, timeout=600)
    images = json.loads(output(["docker", "image", "inspect", image]))
    require(len(images) == 1, "ambiguous pulled image")
    metadata = images[0]
    actual = metadata["Os"] + "/" + metadata["Architecture"]
    if platform.count("/") == 2:
        actual += "/" + metadata.get("Variant", "")
    require(actual == platform, "pulled image platform mismatch")
    digests = metadata["RepoDigests"]
    require(len(digests) == 1, "pulled image has ambiguous repository identities")
    result = {
        "image": image,
        "platform": platform,
        "resolved_image": digests[0],
        "digest": digests[0].split("@")[-1],
        "config_digest": metadata["Id"],
    }
    return result

def sdk(target, release=None):
    # This public variable belongs to the trusted worker deployment, not source JSON.
    base = os.environ.get("OPENWRT_DOWNLOAD_BASE_URL", "https://downloads.openwrt.org").rstrip("/")
    require(re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?", base), "SDK metadata requires an HTTPS origin")
    require(re.fullmatch(r"[0-9]+\.[0-9]+", target["suite"]), "SDK suite must be a numeric release series")
    require(re.fullmatch(r"[a-z0-9_-]+/[a-z0-9_-]+", target["build"]["target"]), "invalid SDK target")
    if release is None:
        versions = json.loads(output(["curl", "--fail", "--silent", "--show-error", base + "/.versions.json"]))
        require(
            isinstance(versions["versions_list"], list) and len(versions["versions_list"]) <= 4096,
            "invalid release list",
        )
        releases = [
            value
            for value in versions["versions_list"]
            if re.fullmatch(re.escape(target["suite"]) + r"\.(0|[1-9][0-9]*)", value)
        ]
        require(bool(releases), "no stable SDK release exists for the configured series")
        release = max(releases, key=lambda value: tuple(map(int, value.split("."))))
    require(
        re.fullmatch(re.escape(target["suite"]) + r"\.(0|[1-9][0-9]*)", release),
        "SDK release is outside configured series",
    )
    root = base + "/releases/" + release + "/targets/" + target["build"]["target"] + "/"
    profile = json.loads(output(["curl", "--fail", "--silent", "--show-error", root + "profiles.json"]))
    require(
        profile["version_number"] == release
        and profile["target"] == target["build"]["target"]
        and profile["arch_packages"] == target["arch"],
        "SDK release/target/package architecture mismatch",
    )
    packages = set(profile["default_packages"])
    ipk = "opkg" in packages
    apk = bool(packages & {"apk", "apk-mbedtls", "apk-openssl"})
    require(
        (target["build"]["format"] == "ipk" and ipk and not apk)
        or (target["build"]["format"] == "apk" and apk and not ipk),
        "SDK package format mismatch",
    )
    sums = output(["curl", "--fail", "--silent", "--show-error", root + "sha256sums"])
    archives = re.findall(
        r"^([a-f0-9]{64})[ \t]+\*?(openwrt-sdk-[A-Za-z0-9_.-]+\.tar\.(?:xz|zst|gz))$", sums, re.MULTILINE
    )
    require(len(archives) == 1, "SDK archive is absent or ambiguous")
    result = {"release": release, "sdk": {"url": root + archives[0][1], "sha256": archives[0][0]}}
    return result
