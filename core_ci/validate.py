"""Unprivileged validation job. No source hook or artifact executable is run."""

import argparse
import os
from pathlib import Path

from contract import assignment, canonical, output, read_json, require, verify_manifest, write_json
from github import artifact


def trusted_deployment(selected):
    deployment = selected["source"]["deployment"]
    require(
        str(deployment["controller_app_bot_id"]) == os.environ["CONTROLLER_APP_BOT_ID"],
        "controller bot differs from trusted worker configuration",
    )
    require(
        os.environ["GITHUB_ACTOR_ID"] == os.environ["CONTROLLER_APP_BOT_ID"],
        "only configured controller dispatches are accepted",
    )
    require(
        os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch" and os.environ["GITHUB_RUN_ATTEMPT"] == "1",
        "unsupported publication invocation",
    )
    require(
        deployment["worker"]["repository"] == os.environ["GITHUB_REPOSITORY"]
        and str(deployment["worker"]["repository_id"]) == os.environ["GITHUB_REPOSITORY_ID"],
        "worker repository mismatch",
    )
    tooling = Path(__file__).resolve().parents[1]
    require(
        deployment["worker"]["tooling_sha"]
        == os.environ["CORE_CI_TOOLING_SHA"]
        == output(["git", "-C", str(tooling), "rev-parse", "HEAD"]),
        "tooling differs from trusted deployment",
    )
    for name, key in (("FEED_REPOSITORY", "repository"), ("FEED_BRANCH", "branch"), ("FEED_BASE_URL", "base_url")):
        require(deployment["feed"][key] == os.environ[name], "feed differs from trusted worker configuration: " + key)
    require(str(deployment["feed"]["repository_id"]) == os.environ["FEED_REPOSITORY_ID"], "feed repository ID mismatch")
    require(
        deployment["signing"]["gpg_fingerprint"] == os.environ["PACKAGES_GPG_FINGERPRINT"],
        "signing fingerprint differs from worker configuration",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assignment", required=True)
    parser.add_argument("--assignment-sha256", required=True)
    parser.add_argument("--build-result", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    selected = assignment(arguments.assignment, arguments.assignment_sha256)
    trusted_deployment(selected)
    require(
        selected["execution"] == os.environ["EXECUTION"] and selected["attempt"] == os.environ["ATTEMPT"],
        "publication inputs differ from assignment",
    )
    # Must be an explicitly scoped source-actions reader. Its actual access is an activation check.
    token = os.environ["SOURCE_ARTIFACT_TOKEN"]
    require(bool(token), "configure read-only source Actions artifact access before activation")
    job = artifact(selected, read_json(arguments.build_result), token, arguments.output)
    if selected["target"]["build"]["format"] == "apk":
        from sdk import prepare

        environment = read_json(Path(arguments.output) / "manifest.json")["environment"]
        prepare(selected["target"], environment, Path(os.environ["RUNNER_TEMP"]) / "validation-sdk")
    manifest = verify_manifest(selected, arguments.output)
    manifest["build_job"] = job
    write_json(Path(arguments.output) / "manifest.json", manifest)
    if selected["target"]["family"] == "openwrt":
        selector = canonical(manifest["environment"])
        require(len(selector.encode()) <= 16384 and "\n" not in selector and "\r" not in selector, "invalid SDK environment selector")
        with open(os.environ["GITHUB_OUTPUT"], "a") as output_file:
            output_file.write("environment=" + selector + "\n")


if __name__ == "__main__":
    main()
