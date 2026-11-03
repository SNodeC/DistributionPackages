"""Bounded GitHub REST reads and assigned-artifact download; credentials never follow redirects."""

import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

from contract import canonical, digest, extract_archive, file_hash, require


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        result = None
        return result


def api(path, token, method="GET", value=None):
    require(path.startswith("/") and not path.startswith("//"), "invalid GitHub API path")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "core-ci-worker",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if value is not None:
        data = canonical(value).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request("https://api.github.com" + path, data=data, headers=headers, method=method)
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
        body = response.read(2 * 1024 * 1024 + 1)
        require(len(body) <= 2 * 1024 * 1024, "GitHub JSON exceeds resource bound")
        result = json.loads(body) if body else None
    return result


def work_name(selected, stage, assignment_hash=None):
    if selected.get("label"):
        result = ("Publish " if stage == "publish" else "Build ") + selected["label"]
    else:
        result = "core-ci " + stage + " " + selected["attempt"]
        if stage != "package":
            result += " " + (assignment_hash or digest(selected))
    return result


def assigned_run(selected, identity, attempt, assignment_hash, token, label=""):
    source = selected["source"]
    deployment = source["deployment"]
    repository = source["repository"]
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is not None, "invalid source repository")
    prefix = "/repos/" + repository
    metadata = api(prefix, token)
    require(metadata["id"] == source["repository_id"], "source repository ID changed")
    run = api(prefix + "/actions/runs/" + str(identity["id"]) + "/attempts/1", token)
    require(
        run["id"] == identity["id"]
        and run["repository"]["id"] == source["repository_id"]
        and run["head_repository"]["id"] == source["repository_id"],
        "build run repository mismatch",
    )
    require(
        run["actor"]["id"] == deployment["controller_app_bot_id"]
        and run["event"] == "workflow_dispatch"
        and run["run_attempt"] == 1
        and run["status"] == "completed",
        "assigned build actor/event/attempt/completion mismatch",
    )
    require(run["head_sha"] == identity["workflow_commit"], "assigned workflow commit mismatch")
    require(
        run["display_title"] == work_name({"attempt": attempt, "label": label}, "build", assignment_hash),
        "build run title mismatch",
    )
    workflow = deployment["source_workflow"]
    require(run["path"] == workflow["path"], "build workflow path mismatch")
    file = api(prefix + "/contents/" + workflow["path"] + "?ref=" + run["head_sha"], token)
    require(
        file["sha"] == workflow["blob_sha"] == identity["workflow_blob_sha"],
        "build workflow differs from approval",
    )
    return run


def artifact(selected, build_result, token, destination):
    require(
        build_result["assignment_sha256"] == digest(selected) and len(build_result["artifacts"]) == 1,
        "build assignment/artifact mismatch",
    )
    run = assigned_run(
        selected, build_result["run"], selected["attempt"], digest(selected), token, selected.get("label", "")
    )
    require(run["conclusion"] == "success", "assigned build did not succeed")
    prefix = "/repos/" + selected["source"]["repository"]
    assigned = build_result["artifacts"][0]
    job = api(prefix + "/actions/jobs/" + str(assigned["job_id"]), token)
    require(
        job["id"] == assigned["job_id"] and job["run_id"] == run["id"] and job["run_attempt"] == 1,
        "assigned job identity mismatch",
    )
    require(job["status"] == "completed" and job["conclusion"] == "success", "assigned job did not succeed")
    name = work_name(selected, "package")
    require(job["name"] == name or job["name"].endswith(" / " + name), "assigned job name mismatch")
    actual = api(prefix + "/actions/artifacts/" + str(assigned["id"]), token)
    require(
        actual["id"] == assigned["id"] and actual["name"] == selected["artifact_name"] == assigned["name"],
        "assigned artifact identity mismatch",
    )
    require(
        actual["workflow_run"]["id"] == run["id"] and not actual["expired"], "artifact does not belong to assigned run"
    )
    require(
        actual["digest"] == assigned["digest"] and actual["size_in_bytes"] == assigned["size_bytes"],
        "assigned artifact bytes changed",
    )
    require(re.fullmatch(r"sha256:[a-f0-9]{64}", actual["digest"]) is not None, "artifact has no immutable digest")
    require(0 < actual["size_in_bytes"] <= 512 * 1024 * 1024, "artifact exceeds supported resource bound")
    archive = Path(destination).with_suffix(".zip")
    download_artifact(prefix + "/actions/artifacts/" + str(assigned["id"]) + "/zip", token, archive, actual)
    try:
        extract_archive(archive, destination, "zip")
    finally:
        archive.unlink(missing_ok=True)
    return {key: job.get(key) for key in ("id", "run_id", "run_attempt", "html_url", "started_at", "completed_at")}


def download_artifact(path, token, destination, expected):
    request = urllib.request.Request(
        "https://api.github.com" + path,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "core-ci-worker",
        },
    )
    location = ""
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=60):
            raise ValueError("expected GitHub's assigned-artifact redirect")
    except urllib.error.HTTPError as response:
        require(response.code == 302, "assigned artifact download is inaccessible")
        location = response.headers["Location"]
    url = urllib.parse.urlsplit(location)
    require(
        url.scheme == "https" and url.hostname and not url.username and not url.fragment and url.port in (None, 443),
        "unsafe artifact redirect",
    )
    require(
        url.hostname.endswith(".blob.core.windows.net") or url.hostname.endswith(".actions.githubusercontent.com"),
        "unsupported GitHub artifact storage origin",
    )
    # New request deliberately has no GitHub token, and does not follow another redirect.
    with urllib.request.build_opener(NoRedirect()).open(location, timeout=60) as response, Path(destination).open(
        "xb"
    ) as outgoing:
        received = 0
        block = response.read(1024 * 1024)
        while block:
            received += len(block)
            require(received <= expected["size_in_bytes"], "download exceeds assigned artifact size")
            outgoing.write(block)
            block = response.read(1024 * 1024)
    require(
        Path(destination).stat().st_size == expected["size_in_bytes"]
        and "sha256:" + file_hash(destination) == expected["digest"],
        "downloaded artifact digest/size mismatch",
    )
