"""Trusted status-only feed update from the controller's public graph facts."""

import argparse
import json
import os
from pathlib import Path
import tempfile
import subprocess
from urllib.parse import urlsplit
import urllib.request

from contract import canonical, read_json, require, run, versions
from publish import checked_push, prepare_commit, render, writer_token


def executing_attempt():
    require(os.environ["GITHUB_RUN_ATTEMPT"] == "1"
            and os.environ["GITHUB_EVENT_NAME"] in ("workflow_dispatch", "workflow_run"),
            "status updates require an original authorized event")
    allowed = {os.environ[name] for name in ("CONTROLLER_APP_BOT_ID", "STATUS_NOTIFY_BOT_ID", "STATUS_OWNER_ID")}
    require(os.environ["GITHUB_ACTOR_ID"] in allowed, "unauthorized status actor")


def snapshot(url):
    # Same public presentation stream as the browser; no credential is sent to it.
    address = urlsplit(url)
    require(address.scheme in ("http", "https") and address.hostname and not address.username and not address.password
            and not address.query and not address.fragment and address.path == "/events", "invalid controller SSE URL")
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    graph = None
    received = 0
    with urllib.request.urlopen(request, timeout=30) as response:
        require(response.url == url and response.headers.get_content_type() == "text/event-stream",
                "redirected or invalid controller SSE response")
        while graph is None or not graph["ready"]:
            line = response.readline(8 * 1024 * 1024 + 1)
            received += len(line)
            require(bool(line) and received <= 8 * 1024 * 1024, "incomplete or oversized controller snapshot")
            if line.startswith(b"data: "):
                event = json.loads(line[6:])
                if graph is None:
                    require(isinstance(event, dict) and event.get("ready") is False,
                            "controller snapshot must begin with metadata")
                    graph = event
                else:
                    require(isinstance(event, list), "unexpected controller snapshot reset")
                    for operation in event:
                        path = operation["path"].split("/")
                        if operation["op"] == "add" and len(path) == 3 and path[1] == "executions":
                            identity = path[2].replace("~1", "/").replace("~0", "~")
                            require(identity not in graph["executions"], "duplicate controller snapshot record")
                            graph["executions"][identity] = operation["value"]
                        else:
                            require(operation == {"op": "replace", "path": "/ready", "value": True},
                                    "unexpected controller snapshot operation")
                            graph["ready"] = True
    return graph


def projection(graph):
    projects = []
    executions = []
    work = sorted(graph["executions"].values(), key=lambda item: item["index"], reverse=True)
    for repository, metadata in graph["repositories"].items():
        definition = metadata["definition"]
        tags = []
        for item in work:
            if item["source"]["repository"] == repository and item["source"]["tag"] not in tags:
                tag = item["source"]["tag"]
                tags.append(tag)
                index = len(tags) - 1
                while index > 0 and subprocess.run(
                    ["dpkg", "--compare-versions", versions(tags[index], 1, "deb")["version"], "gt",
                     versions(tags[index - 1], 1, "deb")["version"]], check=False,
                ).returncode == 0:
                    tags[index - 1], tags[index] = tags[index], tags[index - 1]
                    index -= 1
        projects.append({"repository": repository, "title": definition["title"], "versions": tags,
                         "targets": [{**{key: target[key] for key in ("distribution", "suite", "arch")},
                                      "format": target["build"]["format"]} for target in definition["matrix"]]})
    for item in work:
        active = item["active"]
        state = active["state"]
        executions.append({
            "id": item["id"], "repository": item["source"]["repository"], "tag": item["source"]["tag"],
            "attempt": active["id"], "revision": active["revision"], "state": state,
            "activity": "Retired" if active.get("retirement") else state.capitalize(),
            "failure": active.get("failure"), "superseded_by": None,
            "prerequisites": item["prerequisites"],
            "blockers": [identity for identity in item["prerequisites"]
                         if graph["executions"][identity]["active"]["state"] != "published"],
            "coordinates": {**{key: item["target"][key] for key in ("distribution", "suite", "arch")},
                            "format": item["target"]["build"]["format"]},
            "build_job_url": item.get("build", {}).get("job", {}).get("html_url"),
            "publication_verified_utc": active.get("proof", {}).get("verified_at"),
        })
    feed_identity = {"repository": os.environ["FEED_REPOSITORY"], "repository_id": int(os.environ["FEED_REPOSITORY_ID"]),
                     "branch": os.environ["FEED_BRANCH"]}
    return {"schema": 1, "feed": feed_identity, "projects": projects, "executions": executions}


def prepare(feed):
    executing_attempt()
    facts = projection(snapshot(os.environ["CORE_CI_STATUS_URL"]))
    path = feed / "status/controller.json"
    require(not path.is_symlink() and not path.parent.is_symlink(), "linked controller projection destination")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical(facts) + "\n")
    paths = ["status/controller.json"] + render(feed)
    prepare_commit(feed, paths, "Update public core-ci status")
    return paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", required=True)
    parser.add_argument("--phase", choices=("prepare", "push"), required=True)
    arguments = parser.parse_args()
    executing_attempt()
    os.umask(0o077)
    feed = Path(arguments.feed).resolve()
    if arguments.phase == "prepare":
        prepare(feed)
    else:
        # Verify the prepared bytes before minting a token. No rendering in the push phase.
        run(["git", "-C", str(feed), "diff", "--exit-code", "HEAD"], stdout=None)
        facts = read_json(feed / "status/controller.json", 8 * 1024 * 1024)
        with tempfile.TemporaryDirectory(prefix="core-ci-status-key-", dir=os.environ["RUNNER_TEMP"]) as temporary:
            key = Path(temporary) / "writer.pem"
            key.write_text(os.environ.pop("PACKAGES_APP_PRIVATE_KEY"))
            key.chmod(0o600)
            token = writer_token(key, facts["feed"])
            checked_push(feed, facts["feed"]["branch"], token)
        print("Pushed public status snapshot")


if __name__ == "__main__":
    main()
