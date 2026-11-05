"""Unsigned builds; dependency selection is supplied exclusively by core-ci."""

import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

from .common import (declaration, github_outputs, identifier, inputs, metadata, prerequisites,
                     public_key, registry, select)
from contract import extract_archive, file_hash, output, read_json, require, versions, write_json
from environment import native, sdk
from native import TOOLS
from sdk import prepare


def resolve():
    values = inputs("build")
    settings = registry()
    require(values["source_repo"].lower() in [r.lower() for r in settings["repositories"]], "source not in registry")
    source = metadata(values["source_repo"])
    recipe = values["recipe_ref"] or source["default_branch"]
    doc = declaration(source["full_name"], recipe)
    require(doc["package"] == values["package"], "package/source mismatch")
    entry = select(doc, values["target"])
    github_outputs(runner=entry["runner"], recipe=recipe, source=source["full_name"])


def dependency_definitions(settings, selected, recipe_ref):
    result = {}
    for repo in settings["repositories"]:
        doc = declaration(repo)
        require(doc["package"] not in result, "duplicate declared package")
        if doc["package"] in selected:
            expected = doc["package"]
            if recipe_ref:
                doc = declaration(repo, recipe_ref)
                require(doc["package"] == expected, "prerequisite recipe changed package identity")
            result[doc["package"]] = doc
    require(set(result) == set(selected), "unknown prerequisite package")
    return result


def export_dependency(feed, name, version, revision, target, environment, root, key):
    from .common import download

    encoded = versions(version, revision, target["build"]["format"])
    prefix = "dev/" + target["id"] + "/"
    filename = f'{name}_{version}-{encoded["release"]}.tar.gz'
    sums = root / "SHA256SUMS"
    signature = root / "SHA256SUMS.asc"
    download(feed["url"] + prefix + "SHA256SUMS", sums, 1024**2)
    download(feed["url"] + prefix + "SHA256SUMS.asc", signature, 1024**2)
    keyring = root / "trusted.gpg"
    subprocess.run(["gpg", "--batch", "--yes", "--output", str(keyring), "--dearmor", str(key)], check=True)
    subprocess.run(["gpgv", "--keyring", str(keyring), str(signature), str(sums)], check=True)
    matches = [line.split() for line in sums.read_text().splitlines() if line.split()[-1:] == [filename]]
    require(len(matches) == 1 and re.fullmatch(r"[a-f0-9]{64}", matches[0][0]), "development export absent")
    archive = root / filename
    download(feed["url"] + prefix + filename, archive)
    require(file_hash(archive) == matches[0][0], "development export checksum mismatch")
    extract_archive(archive, root / "development", "tar")
    record = read_json(root / "development/coreci-sdk.json")
    require(record == {"file": Path(environment["sdk"]["url"]).name, "sha256": environment["sdk"]["sha256"]},
            "prerequisite SDK mismatch")
    (root / "development/coreci-sdk.json").unlink()


def dependencies(settings, values, doc, target, environment, work):
    chosen = prerequisites(values["prerequisites"])
    require(set(chosen) == set(doc["depends_on"]), "prerequisites do not match declaration")
    definitions = dependency_definitions(settings, chosen, values["recipe_ref"]) if chosen else {}
    instructions = []
    for name, (version, revision) in sorted(chosen.items()):
        other = select(definitions[name], target["id"])
        feed_name = other.get("feed", settings["default_feed"])
        require(feed_name == target.get("feed", settings["default_feed"]), "prerequisite feed mismatch")
        feed = settings["feeds"][feed_name]
        root = work / "prerequisites" / name
        root.mkdir(parents=True)
        key = public_key(feed, "gpg", root)
        encoded = versions(version, revision, target["build"]["format"])
        if target["family"] == "native":
            names = definitions[name]["development_packages"][target["build"]["format"]]
            require(isinstance(names, list) and names, "missing development_packages")
            for package in names:
                require(re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", package), "invalid development package")
            instructions.append({"names": names, "full": encoded["full"], "feed": feed["url"],
                                 "key": str(key.relative_to(work)), "distribution": other["distribution"],
                                 "suite": other["suite"], "arch": other["arch"]})
        else:
            export_dependency(feed, name, version, revision, target, environment, root, key)
        write_json(root / "metadata.json", {"package": name, "version": version, "revision": revision,
                   "upstream_version": encoded["version"], "release": encoded["release"], "target": target["id"],
                   "sdk": ({"file": Path(environment["sdk"]["url"]).name,
                            "sha256": environment["sdk"]["sha256"]} if target["family"] == "openwrt" else None)})
    return instructions


def install_lines(target, instructions):
    lines = []
    for index, item in enumerate(instructions):
        key = "/inputs/" + item["key"]
        base = item["feed"] + item["distribution"]
        if target["build"]["format"] == "deb":
            source = f'deb [signed-by={key}] {base} {item["suite"]} main\n'
            lines += ["RUN printf '%s\\n' " + shlex.join(source.splitlines()) + f' > /etc/apt/sources.list.d/coreci-{index}.list',
                      "RUN apt-get update && apt-get install -y --no-install-recommends " +
                      " ".join(shlex.quote(p + "=" + item["full"]) for p in item["names"])]
        else:
            source = (f'[coreci-{index}]\nname=coreci\nbaseurl={base}/{item["suite"]}/{item["arch"]}/\n'
                      f'gpgcheck=1\nrepo_gpgcheck=1\ngpgkey=file://{key}\n')
            lines += ["RUN printf '%s\\n' " + shlex.join(source.splitlines()) + f' > /etc/yum.repos.d/coreci-{index}.repo',
                      "RUN dnf install -y " + " ".join(shlex.quote(p + "-" + item["full"]) for p in item["names"])]
        for package in item["names"]:
            query = (["dpkg-query", "--show", "--showformat=${Version}", package] if target["build"]["format"] == "deb"
                     else ["rpm", "-q", "--queryformat", "%{VERSION}-%{RELEASE}", package])
            lines.append("RUN test \"$(" + shlex.join(query) + ")\" = " + shlex.quote(item["full"]))
    return lines


def build(source, definition, destination):
    values = inputs("build")
    settings = registry()
    doc = read_json(Path(definition) / "ci/packages.json")
    require(doc["package"] == values["package"], "package mismatch")
    target = select(doc, values["target"])
    require(values["source_repo"].lower() in [r.lower() for r in settings["repositories"]], "unregistered source")
    destination = Path(destination).resolve()
    require(not destination.exists(), "output already exists")
    destination.mkdir()
    destination.chmod(0o777)
    tooling = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"], prefix="coreci-build-") as temporary:
        work = Path(temporary)
        family = target["family"]
        fmt = target["build"]["format"]
        environment = native(target) if family == "native" else sdk(target, target["build"]["release"])
        sdk_root = None
        if family == "openwrt":
            sdk_root, staging = prepare(target, environment, work / "sdk")
            environment["staging_dir"] = str(staging)
            environment["host"] = native({"build": {"image": "ubuntu:24.04", "platform": "linux/amd64"}})
        host = environment if family == "native" else environment["host"]
        (work / "prerequisites").mkdir()
        instructions = dependencies(settings, values, doc, target, environment, work)
        write_json(work / "target.json", target)
        write_json(work / "environment.json", environment)
        for name, tree in (("source", source), ("definition", definition), ("core_ci", tooling / "core_ci"),
                           ("coreci", tooling / "coreci")):
            shutil.copytree(tree, work / name, ignore=shutil.ignore_patterns(".git", "__pycache__"), symlinks=True)
        tools = TOOLS.get(fmt, "apt-get update && apt-get install -y build-essential clang flex bison gawk gettext git "
                          "libncurses-dev libssl-dev python3 python3-setuptools rsync swig unzip zlib1g-dev file "
                          "wget curl zstd ca-certificates cmake qemu-user")
        if target["family"] == "native" and fmt == "deb":
            tools += " && apt-get install -y gnupg"
        if target["distribution"] == "rocky":
            tools = "dnf install -y dnf-plugins-core epel-release && dnf config-manager --set-enabled crb && " + tools
        extra = doc.get("build_dependencies", {}).get(fmt, []) + target["build"].get("dependencies", [])
        require(all(isinstance(p, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+_.:-]*", p) for p in extra),
                "invalid build dependencies")
        if extra:
            tools += " && " + ("dnf install -y " if fmt == "rpm" else "apt-get install -y ") + shlex.join(extra)
        lines = ["FROM " + host["resolved_image"], "RUN " + tools, "COPY prerequisites /inputs/prerequisites"]
        lines += install_lines(target, instructions)
        lines += ["RUN mkdir -p /work && chmod 1777 /work && "
                  "(getent passwd 1000 >/dev/null || useradd -u 1000 -U -M -d /tmp builder)"]
        (work / "Dockerfile").write_text("\n".join(lines) + "\n")
        (work / ".dockerignore").write_text("sdk\nsource\ndefinition\ncore_ci\ncoreci\n")
        image = "coreci-build:" + str(os.getpid())
        subprocess.run(["docker", "build", "--platform", host["platform"], "-t", image, str(work)], check=True, timeout=3600)
        mounts = []
        for source_path, container_path, readonly in ((work / "source", "/source", True),
                (work / "definition", "/definition", True), (work / "coreci", "/tool", True),
                (work / "core_ci", "/core_ci", True), (work / "prerequisites", "/prerequisites", True),
                (work / "target.json", "/target.json", True), (work / "environment.json", "/environment.json", True),
                (destination, "/output", False)):
            mounts += ["--mount", f'type=bind,source={source_path},target={container_path}' + (",readonly" if readonly else "")]
        if sdk_root:
            mounts += ["--mount", f'type=bind,source={sdk_root},target=/sdk,readonly']
        common = ["docker", "run", "--rm", "--init", "--user=1000:1000", "--platform", host["platform"],
                  "--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only", "--pids-limit=256",
                  "--memory=4g", "--cpus=2", "--tmpfs", "/tmp:rw,exec,size=2g,mode=1777",
                  "--tmpfs", "/var/tmp:rw,exec,size=2g,mode=1777", "--volume", "/work"] + mounts
        command = ["python3", "/tool/container.py", "--tag", values["tag"], "--version", values["version"],
                   "--revision", values["revision"], "--package", values["package"], "--build-id", values["build_id"],
                   "--feed", target.get("feed", settings["default_feed"])]
        try:
            subprocess.run(common + [image] + command, check=True, timeout=21600)
            subprocess.run(common + ["--network=none", image] + command + ["--inspect"], check=True, timeout=600)
        finally:
            subprocess.run(["docker", "image", "rm", image], check=False, capture_output=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("resolve", "run"))
    parser.add_argument("--source", default="source")
    parser.add_argument("--definition", default="recipe")
    parser.add_argument("--output", default="packages")
    args = parser.parse_args()
    if args.mode == "resolve":
        resolve()
    else:
        build(args.source, args.definition, args.output)


if __name__ == "__main__":
    main()
