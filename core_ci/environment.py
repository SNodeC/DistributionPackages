"""Build environment resolution runs on the GitHub worker, before source hooks."""

import json
import os
from pathlib import Path
import tempfile
import re
import subprocess

from contract import assignment, compatibility, digest, extract_archive, output, read_json, require, write_json
from github import work_name, api, assigned_run, download_artifact


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


def previous(selected):
    result = None
    attempts = list(reversed(selected.get("environment_from", [])))
    token = os.environ.get("GITHUB_TOKEN", "")
    require(not attempts or token, "retry requires read-only access to previous environment evidence")
    index = 0
    prefix = "/repos/" + selected["source"]["repository"]
    while index < len(attempts) and result is None:
        earlier = attempts[index]
        run = assigned_run(
            selected, earlier["run"], earlier["attempt"], earlier["assignment_sha256"], token, earlier.get("label", "")
        )
        run_path = prefix + "/actions/runs/" + str(run["id"])
        listing = api(run_path + "/artifacts?per_page=100", token)
        require(listing["total_count"] <= 100, "previous artifact list exceeds supported bounds")
        artifacts = [item for item in listing["artifacts"] if item["name"] == earlier["artifact_name"]]
        require(len(artifacts) <= 1, "ambiguous previous environment artifact")
        if artifacts:
            artifact = artifacts[0]
            require(
                not artifact["expired"]
                and artifact["workflow_run"]["id"] == run["id"]
                and 0 < artifact["size_in_bytes"] <= 65536,
                "previous environment evidence is inaccessible",
            )
            with tempfile.TemporaryDirectory(prefix="core-ci-environment-", dir=os.environ["RUNNER_TEMP"]) as temporary:
                archive = Path(temporary) / "environment.zip"
                download_artifact(
                    prefix + "/actions/artifacts/" + str(artifact["id"]) + "/zip", token, archive, artifact
                )
                root = Path(temporary) / "extracted"
                extract_archive(archive, root, "zip")
                require(
                    {item.name for item in root.iterdir()} == {"environment.json"},
                    "unexpected environment artifact files",
                )
                document = read_json(root / "environment.json", 16384)
                require(
                    document["assignment_sha256"] == earlier["assignment_sha256"],
                    "previous environment assignment mismatch",
                )
                result = document["environment"]
        else:
            jobs = api(run_path + "/attempts/1/jobs?per_page=100", token)
            require(jobs["total_count"] <= 100, "previous job list exceeds supported bounds")
            name = work_name(earlier, "package")
            matches = [job for job in jobs["jobs"] if job["name"] == name or job["name"].endswith(" / " + name)]
            require(
                len(matches) == 1 and matches[0]["run_id"] == run["id"] and matches[0]["run_attempt"] == 1,
                "previous build job is inaccessible",
            )
            steps = {step["name"]: step for step in matches[0]["steps"]}
            require(
                steps.get("Build selected packages in an isolated container", {}).get("conclusion") == "skipped"
                and steps.get("Record resolved build environment", {}).get("conclusion")
                in ("failure", "skipped", "cancelled"),
                "previous environment evidence is unavailable; refuse to resolve another after a possible build",
            )
        index += 1
    return result


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--assignment", required=True)
    parser.add_argument("--assignment-sha256", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    require(os.environ["GITHUB_RUN_ATTEMPT"] == "1", "reruns require an explicit controller retry")
    selected = assignment(arguments.assignment, arguments.assignment_sha256)
    require(
        selected["execution"] == os.environ["EXECUTION"] and selected["attempt"] == os.environ["ATTEMPT"],
        "workflow identity mismatch",
    )
    resolved = previous(selected)
    if resolved is None:
        if selected["target"]["family"] == "native":
            resolved = native(selected["target"])
        elif selected["dependencies"]:
            # The selected receipts own physical compatibility, including at joins.
            inherited = selected["dependencies"][0]["receipt"]["environment"]
            resolved = {key: inherited[key] for key in ("release", "sdk", "toolchain", "staging_dir")}
            expected = compatibility(selected, resolved)
            for dependency in selected["dependencies"]:
                receipt = dependency["receipt"]
                require(receipt["compatibility"] == expected, "prerequisites require incompatible SDKs or targets")
                require(
                    all(receipt["environment"][key] == resolved[key] for key in resolved),
                    "prerequisite SDK identities disagree",
                )
        else:
            resolved = sdk(selected["target"], selected["target"]["build"].get("release"))
    if selected["target"]["family"] == "openwrt":
        from sdk import prepare

        prepare(selected["target"], resolved, Path(os.environ["RUNNER_TEMP"]) / "core-ci-sdk")
        if "host" not in resolved:
            resolved["host"] = native(
                {
                    "build": {
                        "image": os.environ.get("OPENWRT_WORKER_IMAGE", "ubuntu:24.04"),
                        "platform": os.environ.get("OPENWRT_WORKER_PLATFORM", "linux/amd64"),
                    }
                }
            )
    write_json(arguments.output, {"assignment_sha256": digest(selected), "environment": resolved})


if __name__ == "__main__":
    main()
