"""Trusted checked feed commit and HTTPS verification. No source code is executed."""

import argparse
import base64
import hashlib
import json
import re
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

from contract import assignment, canonical, output, read_json, require, run
from github import api
from sign_native import receipt_path, retained_receipt, update
from validate import trusted_deployment


def render(feed):
    # Templates run after signing files are removed, with no inherited job credentials.
    result = subprocess.run(
        [
            os.environ.get("CORE_CI_RENDER_PYTHON", sys.executable),
            str(Path(__file__).with_name("feed_status.py")),
            "--feed",
            str(feed),
        ],
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=subprocess.PIPE,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def base64url(value):
    result = base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    return result


def writer_token(private_key, feed):
    now = int(time.time())
    unsigned = (
        base64url(b'{"alg":"RS256","typ":"JWT"}')
        + "."
        + base64url(canonical({"iat": now - 60, "exp": now + 540, "iss": os.environ["FEED_WRITER_APP_ID"]}).encode())
    )
    signed = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", str(private_key)],
        input=unsigned.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        timeout=30,
    )
    jwt = unsigned + "." + base64url(signed.stdout)
    response = api(
        "/app/installations/" + str(int(os.environ["FEED_WRITER_INSTALLATION_ID"])) + "/access_tokens",
        jwt,
        "POST",
        {"repository_ids": [feed["repository_id"]], "permissions": {"contents": "write"}},
    )
    require(
        response["permissions"].get("contents") == "write" and response.get("repository_selection") == "selected",
        "feed token is not repository-restricted",
    )
    token = response["token"]
    metadata = api("/repos/" + feed["repository"], token)
    require(metadata["id"] == feed["repository_id"], "feed repository identity changed")
    return token


def run_identity(selected):
    token = os.environ["GITHUB_TOKEN"]
    repository = os.environ["GITHUB_REPOSITORY"]
    run = api("/repos/" + repository + "/actions/runs/" + str(int(os.environ["GITHUB_RUN_ID"])) + "/attempts/1", token)
    workflow = selected["source"]["deployment"]["publication_workflow"]
    require(
        run["actor"]["id"] == selected["source"]["deployment"]["controller_app_bot_id"] and run["run_attempt"] == 1,
        "publication run actor/attempt mismatch",
    )
    require(run["path"] == workflow["path"] and run["event"] == "workflow_dispatch", "publication workflow mismatch")
    actual = api("/repos/" + repository + "/contents/" + workflow["path"] + "?ref=" + run["head_sha"], token)
    require(actual["sha"] == workflow["blob_sha"], "publication workflow differs from controller approval")
    result = {
        "id": run["id"],
        "run_attempt": 1,
        "repository_id": int(os.environ["GITHUB_REPOSITORY_ID"]),
        "actor_id": run["actor"]["id"],
        "workflow_blob_sha": actual["sha"],
        "workflow_commit": run["head_sha"],
        "html_url": run["html_url"],
    }
    return result


def prepare_commit(feed, expected_paths, message="Publish verified core-ci packages", orphan=False, removed=()):
    base = output(["git", "-C", str(feed), "rev-parse", "--verify", "HEAD"]) if orphan else ""
    require(set(removed) <= set(expected_paths), "unapproved feed deletion")
    run(["git", "-C", str(feed), "add", "--all", "--", *expected_paths])
    staged_paths = output(["git", "-C", str(feed), "diff", "--cached", "--name-only", "--no-renames"]).splitlines()
    require(set(staged_paths) <= set(expected_paths), "feed index contains changes outside the prepared update")
    for path in expected_paths:
        if path in removed:
            require(not (feed / path).exists() and not (feed / path).is_symlink(), "deleted feed path still exists")
            run(["git", "-C", str(feed), "cat-file", "-e", "HEAD:" + path], stdout=subprocess.DEVNULL)
        else:
            raw = output(["git", "-C", str(feed), "hash-object", "--no-filters", str(feed / path)])
            staged = output(["git", "-C", str(feed), "rev-parse", ":" + path])
            require(raw == staged, "feed index omits or transforms verified package/index bytes")
    changed = subprocess.run(["git", "-C", str(feed), "diff", "--cached", "--quiet"], check=False).returncode
    require(changed in (0, 1), "cannot inspect feed changes")
    identity = ["git", "-C", str(feed), "-c", "user.name=core-ci publisher", "-c", "user.email=core-ci@users.noreply.github.com"]
    if orphan:
        snapshot = output(identity + ["commit-tree", output(["git", "-C", str(feed), "write-tree"]), "-m", message])
        run(["git", "-C", str(feed), "update-ref", "HEAD", snapshot, base])
    elif changed == 1:
        run(identity + ["commit", "-m", message], stdout=subprocess.DEVNULL)
    return base


def checked_push(feed, branch, token, base=""):
    authorization = base64.b64encode(("x-access-token:" + token).encode()).decode()
    environment = {
        **os.environ,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic " + authorization,
        "GIT_TERMINAL_PROMPT": "0",
    }
    require(not base or re.fullmatch(r"[a-f0-9]{40}", base), "invalid expected feed head")
    lease = ["--force-with-lease=refs/heads/" + branch + ":" + base] if base else []
    run(
        ["git", "-C", str(feed), "push", *lease, "origin", "HEAD:refs/heads/" + branch],
        env=environment,
        stdout=subprocess.DEVNULL,
    )
    revision = output(["git", "-C", str(feed), "rev-parse", "HEAD"])
    return revision


def wait_for_https(selected, expected):
    path = receipt_path(selected)
    require(re.fullmatch(r"[a-f0-9]{64}", expected) is not None, "invalid prepared receipt hash")
    url = selected["source"]["deployment"]["feed"]["base_url"].rstrip("/") + "/" + path
    verified = False
    deadline = time.monotonic() + 600
    while not verified and time.monotonic() < deadline:
        try:
            request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(request, timeout=30) as response:
                content = response.read(2 * 1024 * 1024 + 1)
                verified = (
                    len(content) <= 2 * 1024 * 1024
                    and response.url.startswith(selected["source"]["deployment"]["feed"]["base_url"].rstrip("/") + "/")
                    and hashlib.sha256(content).hexdigest() == expected
                )
        except OSError:
            verified = False
        if not verified:
            time.sleep(10)
    require(
        verified, "feed push may have committed; HTTPS receipt is not verified; reconcile before replacing this work"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("prepare", "retain", "push", "confirm"), required=True)
    parser.add_argument("--assignment", required=True)
    parser.add_argument("--assignment-sha256", required=True)
    parser.add_argument("--build-result", default="")
    parser.add_argument("--artifacts", default="")
    parser.add_argument("--tools", default="")
    parser.add_argument("--feed", default="")
    parser.add_argument("--receipt-sha256", default="")
    parser.add_argument("--feed-revision", default="")
    parser.add_argument("--expected-head", default="")
    arguments = parser.parse_args()
    require(arguments.phase == "confirm" or bool(arguments.feed), "prepare/retain/push require --feed")
    require(
        arguments.phase != "prepare" or bool(arguments.build_result and arguments.artifacts),
        "prepare requires --build-result and --artifacts",
    )
    require(arguments.phase != "push" or re.fullmatch(r"[a-f0-9]{40}", arguments.expected_head), "push requires the prepared feed head")
    os.umask(0o077)
    selected = assignment(arguments.assignment, arguments.assignment_sha256)
    require(arguments.phase == "push" or (arguments.phase == "retain") == (selected.get("kind") == "retention"), "phase differs from assignment")
    trusted_deployment(selected)
    require(
        selected["execution"] == os.environ["EXECUTION"] and selected["attempt"] == os.environ["ATTEMPT"],
        "publication identity mismatch",
    )
    require(
        arguments.phase not in ("prepare", "retain") or selected["target"]["build"]["format"] not in ("ipk", "apk") or bool(arguments.tools),
        "OpenWrt prepare requires --tools",
    )
    if arguments.phase == "confirm":
        require(re.fullmatch(r"[a-f0-9]{40}", arguments.feed_revision) is not None, "invalid prepared feed revision")
        wait_for_https(selected, arguments.receipt_sha256)
        print("Verified public receipt for prepared revision:", arguments.feed_revision)
    else:
        feed = Path(arguments.feed).resolve()
        package_format = selected["target"]["build"]["format"]
        secret_name, public_name = {
            "deb": ("APT_SIGNING_KEY", "apt.asc"),
            "rpm": ("APT_SIGNING_KEY", "apt.asc"),
            "ipk": ("OPENWRT_USIGN_KEY", "opkg.pub"),
            "apk": ("OPENWRT_APK_KEY", "core-ci-apk.pem"),
        }[package_format]
        identity = run_identity(selected)
        removed = []
        with tempfile.TemporaryDirectory(prefix="core-ci-secrets-", dir=os.environ["RUNNER_TEMP"]) as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            keys = {}
            for name in (secret_name,) if arguments.phase in ("prepare", "retain") else ("PACKAGES_APP_PRIVATE_KEY",):
                value = os.environ.pop(name, "")
                require(bool(value), "missing protected publication secret: " + name)
                path = root / name
                path.write_text(value)
                path.chmod(0o600)
                keys[name] = path
            passphrase = None
            value = os.environ.pop("PACKAGES_GPG_PASSPHRASE", "")
            if value and arguments.phase in ("prepare", "retain") and package_format in ("deb", "rpm"):
                passphrase = root / "passphrase"
                passphrase.write_text(value)
                passphrase.chmod(0o600)
            if arguments.phase in ("prepare", "retain"):
                public_key = Path(__file__).resolve().parents[1] / "keys" / public_name
                if arguments.phase == "retain":
                    from retention import update as prune

                    paths, removed = prune(selected, feed, keys[secret_name], passphrase, public_key, root, arguments.tools)
                elif package_format in ("ipk", "apk"):
                    from sign_openwrt import update as update_openwrt

                    receipt = update_openwrt(
                        selected,
                        read_json(arguments.build_result),
                        identity,
                        arguments.artifacts,
                        feed,
                        keys[secret_name],
                        public_key,
                        root,
                        arguments.tools,
                    )
                else:
                    receipt = update(
                        selected,
                        read_json(arguments.build_result),
                        identity,
                        arguments.artifacts,
                        feed,
                        keys[secret_name],
                        passphrase,
                        public_key,
                        root,
                    )
                if arguments.phase == "prepare":
                    receipt = retained_receipt(selected, read_json(arguments.build_result), identity, feed)
                    require(receipt is not None, "publication requires the prepared verified receipt")
                    paths = [receipt_path(selected), "keys/" + public_name] + [
                        item["path"] for item in receipt["packages"] + receipt["indexes"]
                    ]
                    if receipt.get("development_export"):
                        paths.append(receipt["development_export"]["path"])
            else:
                token = writer_token(keys["PACKAGES_APP_PRIVATE_KEY"], selected["source"]["deployment"]["feed"])
                revision = checked_push(feed, selected["source"]["deployment"]["feed"]["branch"], token, arguments.expected_head)
        if arguments.phase == "push":
            print("Pushed checked feed revision:", revision)
        else:
            paths += render(feed)
            # GitHub Pages has a 1 GB site limit. Retain versions and leave headroom.
            require(
                sum(
                    path.stat().st_size
                    for path in feed.rglob("*")
                    if path.is_file() and ".git" not in path.relative_to(feed).parts
                )
                < 900 * 1024 * 1024,
                "new packages would exceed reviewed Pages capacity",
            )
            if package_format == "rpm":
                scope = "/".join([selected["target"][key] for key in ("distribution", "suite", "arch")]) + "/repodata"
                deleted = output(["git", "-C", str(feed), "ls-files", "--deleted", "--", scope]).splitlines()
                removed += deleted
                paths += deleted
            base = prepare_commit(feed, paths, orphan=True, removed=removed)
            receipt_hash = hashlib.sha256((feed / receipt_path(selected)).read_bytes()).hexdigest() if arguments.phase == "prepare" else ""
            revision = output(["git", "-C", str(feed), "rev-parse", "HEAD"])
            with open(os.environ["GITHUB_OUTPUT"], "a") as outputs:
                outputs.write("receipt-sha256=" + receipt_hash + "\nfeed-revision=" + revision + "\nexpected-head=" + base + "\n")
            print("Prepared and locally verified publication; no feed mutation requested")


if __name__ == "__main__":
    main()
