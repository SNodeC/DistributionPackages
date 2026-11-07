"""Registry declarations, workflow inputs, signatures and artifact boundaries."""

import json
import os
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request

from contract import canonical, file_hash, output, regular_file, relative_path, require, versions, write_json
from github import NoRedirect, api
from sign_native import fingerprints


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", value), "invalid identifier")
    return value


def repository(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}", value),
            "invalid repository")
    require(value.split("/")[1] not in (".", ".."), "invalid repository")
    return value


def workflow(value):
    match = re.fullmatch(r"([^/]+/[^/]+)/\.github/workflows/([A-Za-z0-9._-]+\.ya?ml)", value)
    require(match is not None, "invalid workflow reference")
    result = (repository(match[1]), ".github/workflows/" + match[2])
    return result


def workflow_identity(value):
    repo, path = workflow(value.split("@", 1)[0])
    return repo.lower(), path


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def document(raw):
    require(len(raw) <= 1024**2, "declaration exceeds 1 MiB")
    result = json.loads(raw, object_pairs_hook=pairs,
                        parse_constant=lambda value: require(False, "invalid JSON constant: " + value))
    require(isinstance(result, dict), "declaration must be an object")
    return result


def token():
    return os.environ.get("GITHUB_TOKEN", "")


def request_file(repo, path, ref):
    repository(repo)
    relative_path(path)
    url = "https://api.github.com/repos/" + repo + "/contents/" + urllib.parse.quote(path, safe="/")
    url += "?ref=" + urllib.parse.quote(ref, safe="")
    headers = {"Accept": "application/vnd.github.raw", "X-GitHub-Api-Version": "2022-11-28"}
    if token():
        headers["Authorization"] = "Bearer " + token()
    with urllib.request.build_opener(NoRedirect()).open(urllib.request.Request(url, headers=headers), timeout=60) as response:
        raw = response.read(1024**2 + 1)
    return document(raw)


def metadata(repo):
    return api("/repos/" + repository(repo), token())


def declaration(repo, ref=""):
    branch = ref or metadata(repo)["default_branch"]
    result = request_file(repo, "ci/packages.json", branch)
    identifier(result["package"])
    require(isinstance(result["matrix"], list), "matrix must be an array")
    require(len({identifier(t["id"]) for t in result["matrix"]}) == len(result["matrix"]), "duplicate target")
    return result


def registry(path="ci/registry.json"):
    result = document(Path(path).read_bytes())
    workflow(result["build"])
    require(isinstance(result["repositories"], list), "repositories must be an array")
    for repo in result["repositories"]:
        repository(repo)
    require(isinstance(result["feeds"], dict) and result["default_feed"] in result["feeds"], "invalid default feed")
    for name, feed in result["feeds"].items():
        identifier(name)
        workflow(feed["publisher"])
        if "presentation" in feed:
            workflow(feed["presentation"])
            https(result['status_url'])
        repository(feed["repository"])
        https(feed["url"])
        require(feed["url"].endswith("/"), "feed URL must end with slash")
        require(isinstance(feed["environment"], str) and feed["environment"], "missing feed environment")
        for kind, field, pattern in (("gpg", "fingerprint", r"[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64}"),
                                     ("usign", "key_id", r"[A-Fa-f0-9]{16}"), ("apk", "sha256", r"[a-f0-9]{64}")):
            key = feed["keys"][kind]
            relative_path(key["file"])
            require(key["file"].startswith("keys/"), "public key must be under keys/")
            require(re.fullmatch(pattern, key[field]) is not None, "invalid key trust anchor")
    if "badges" in result:
        https(result["badges"])
    return result


def https(url):
    value = urllib.parse.urlsplit(url)
    require(value.scheme == "https" and value.hostname and not value.username and not value.password,
            "expected public HTTPS URL")
    return value


def download(url, path, limit=512 * 1024**2):
    https(url)
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=60) as response, Path(path).open("wb") as target:
        https(response.url)
        count = 0
        chunk = response.read(1024**2)
        while chunk:
            count += len(chunk)
            require(count <= limit, "download exceeds bound")
            target.write(chunk)
            chunk = response.read(1024**2)


def public_key(feed, kind, directory):
    key = feed["keys"][kind]
    path = Path(directory) / Path(key["file"]).name
    download(feed["url"] + key["file"], path, 1024**2)
    if kind == "gpg":
        actual = fingerprints(output(["gpg", "--batch", "--with-colons", "--show-keys", str(path)]))
        require(actual == [key["fingerprint"].upper()], "GPG public key mismatch")
    elif kind == "apk":
        require(file_hash(path) == key["sha256"], "APK public key mismatch")
    else:
        require(output(["usign", "-F", "-p", str(path)]).lower() == key["key_id"].lower(), "usign key mismatch")
    return path


def inputs(kind):
    names = "build_id package version revision target callback_url".split()
    names += ("source_repo tag prerequisites recipe_ref" if kind == "build" else "build_repo build_run_id artifact").split()
    result = {name: os.environ.get("INPUT_" + name.upper(), "") for name in names}
    for name in names:
        require(result[name] or name in ("callback_url", "prerequisites", "recipe_ref"), "missing input: " + name)
    identifier(result["package"])
    identifier(result["target"])
    require(re.fullmatch(r"[1-9][0-9]*", result["revision"]), "invalid revision")
    require(result["build_id"] == f'{result["package"]}~{result["target"]}~{result["version"]}~r{result["revision"]}',
            "build_id does not match inputs")
    versions(result["version"], int(result["revision"]), "deb")
    if kind == "build":
        require(result["tag"].removeprefix("v") == result["version"], "tag/version mismatch")
        repository(result["source_repo"])
        if result["recipe_ref"]:
            subprocess.run(["git", "check-ref-format", "--branch", result["recipe_ref"]], check=True, capture_output=True)
    else:
        repository(result["build_repo"])
        require(re.fullmatch(r"[1-9][0-9]*", result["build_run_id"]), "invalid build_run_id")
        require(result["artifact"] == "coreci-" + result["build_id"], "artifact name mismatch")
    return result


def prerequisites(text):
    result = {}
    if text:
        for item in text.split(","):
            name, value = item.split("=", 1)
            identifier(name)
            version, revision = value.rsplit("-", 1)
            require(name not in result and re.fullmatch(r"[1-9][0-9]*", revision), "invalid prerequisite")
            versions(version, int(revision), "deb")
            result[name] = (version, int(revision))
    return result


def select(doc, target):
    matches = [entry for entry in doc["matrix"] if entry["id"] == target]
    require(len(matches) == 1, "target not found exactly once")
    result = matches[0]
    require(result["family"] in ("native", "openwrt"), "invalid target family")
    require(result["build"]["format"] in (("deb", "rpm") if result["family"] == "native" else ("ipk", "apk")),
            "invalid target format")
    for field in ("distribution", "suite", "arch"):
        require(re.fullmatch(r"[A-Za-z0-9._+-]+", result[field]), "unsafe target coordinate")
    return result


def github_outputs(**values):
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        for name, value in values.items():
            require("\n" not in str(value) and "\r" not in str(value), "invalid workflow output")
            stream.write(name + "=" + str(value) + "\n")


def checked_manifest(root, values):
    manifest = document(regular_file(root, "manifest.json").read_bytes())
    for name in ("build_id", "package", "version", "target"):
        require(manifest[name] == values[name], "manifest mismatch: " + name)
    require(type(manifest["revision"]) is int and manifest["revision"] == int(values["revision"]), "revision mismatch")
    require(isinstance(manifest["files"], dict) and manifest["files"], "missing manifest files")
    actual = {str(p.relative_to(root)) for p in Path(root).rglob("*") if not p.is_dir()}
    require(actual == set(manifest["files"]) | {"manifest.json"}, "unexpected artifact files")
    for name, checksum in manifest["files"].items():
        require("/" not in name and re.fullmatch(r"[a-f0-9]{64}", checksum), "invalid manifest file")
        require(file_hash(regular_file(root, name)) == checksum, "artifact checksum mismatch")
    require(manifest["entry"]["id"] == values["target"], "matrix entry mismatch")
    identifier(manifest["feed"])
    return manifest
