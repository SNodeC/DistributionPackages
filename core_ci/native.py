"""Native worker entry point. No signing credentials are accepted here."""

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

from contract import evidence
from contract import assignment, compatibility, download_feed, extract_archive, output, read_json, require, write_json


TOOLS = {
    "deb": "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends build-essential python3 pkg-config ca-certificates git",
    "rpm": "dnf install -y gcc gcc-c++ make rpm-build python3 pkgconf-pkg-config findutils tar gzip git && dnf clean all",
}


def prepare_dependencies(selected, destination, environment):
    destination.mkdir()
    for dependency in selected["dependencies"]:
        receipt = dependency["receipt"]
        base = receipt["feed"]["base_url"]
        require(
            receipt["execution"] == dependency["execution"] and receipt["attempt"] == dependency["attempt"],
            "prerequisite receipt mismatch",
        )
        require(receipt["compatibility"] == compatibility(selected, environment), "prerequisite target incompatibility")
        root = destination / dependency["execution"]
        root.mkdir()
        write_json(root / "receipt.json", receipt)
        for package in receipt["packages"]:
            require("/" not in package["file"], "invalid prerequisite filename")
            download_feed(base, package["path"], root / package["file"], package)
        if receipt.get("development_export"):
            export = receipt["development_export"]
            require(export["compatibility"] == compatibility(selected, environment), "incompatible development export")
            archive = root / "development.tar.gz"
            download_feed(base, export["path"], archive, export)
            extract_archive(archive, root / "development", "tar")


def build(arguments):
    selected = assignment(arguments.assignment, arguments.assignment_sha256)
    require(selected["source"]["repository"] == os.environ["GITHUB_REPOSITORY"], "source repository mismatch")
    require(
        str(selected["source"]["repository_id"]) == os.environ["GITHUB_REPOSITORY_ID"], "source repository ID mismatch"
    )
    require(os.environ["GITHUB_RUN_ATTEMPT"] == "1", "reruns require an explicit controller retry")
    source = Path(arguments.source).resolve()
    tooling = Path(__file__).resolve().parents[1]
    require(
        output(["git", "-C", str(source), "rev-parse", "HEAD"]) == selected["source"]["commit"],
        "checkout is not the selected source",
    )
    require(
        output(["git", "-C", str(tooling), "rev-parse", "HEAD"])
        == selected["source"]["deployment"]["worker"]["tooling_sha"],
        "tooling checkout mismatch",
    )
    ci = Path(arguments.definition).resolve()
    require(
        output(["git", "-C", str(ci), "rev-parse", "HEAD"]) == selected["source"]["definition_revision"],
        "checkout is not the selected CI revision",
    )
    definition = ci / "ci/packages.json"
    blob = output(["git", "hash-object", str(definition)])
    require(blob == selected["source"]["definition_blob_sha"], "checkout definition does not match selection")
    document = read_json(definition)
    require(selected["target"] in document["matrix"], "selected target absent from committed definition")
    for key in ("package", "title", "depends_on", "build"):
        require(document[key] == selected["source"][key], "committed definition differs from assignment")
    family = selected["target"]["family"]
    hook = (ci / selected["source"]["build"][family]).resolve()
    require(hook.is_relative_to(ci) and hook.is_file(), "hook escapes selected CI checkout")
    resolved = read_json(arguments.environment, 16384)
    require(resolved["assignment_sha256"] == arguments.assignment_sha256, "environment belongs to another assignment")
    environment = resolved["environment"]
    host = environment if family == "native" else environment["host"]
    image = host["resolved_image"]
    platform = host["platform"]
    package_format = selected["target"]["build"]["format"]
    require(
        package_format in TOOLS or (family == "openwrt" and package_format in ("ipk", "apk")),
        "unsupported worker format",
    )
    destination = Path(arguments.output).resolve()
    require(not destination.exists(), "output destination must be new")
    destination.mkdir()
    destination.chmod(0o777)
    tag = "core-ci-build-" + selected["execution"] + ":" + str(selected["revision"])
    with tempfile.TemporaryDirectory(prefix="core-ci-", dir=os.environ["RUNNER_TEMP"]) as temporary:
        work = Path(temporary)
        write_json(work / "assignment.json", selected)
        write_json(work / "target.json", selected["target"])
        write_json(work / "environment.json", environment)
        prepare_dependencies(selected, work / "prerequisites", environment)
        # Copied input trees enter the hook container without .git credentials or host workspace.
        shutil.copytree(source, work / "source", ignore=shutil.ignore_patterns(".git"), symlinks=True)
        shutil.copytree(ci, work / "definition", ignore=shutil.ignore_patterns(".git"), symlinks=True)
        shutil.copytree(tooling / "core_ci", work / "core_ci")
        install = "RUN python3 /tool/native_container.py --install\n"
        tools = TOOLS.get(
            package_format,
            "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
            "build-essential clang flex bison gawk gettext git libncurses-dev libssl-dev python3 python3-setuptools rsync swig "
            "unzip zlib1g-dev file wget curl zstd ca-certificates cmake qemu-user",
        )
        if family == "native":
            if selected["target"]["distribution"] == "rocky":
                tools = ("dnf install -y dnf-plugins-core epel-release && "
                         "dnf config-manager --set-enabled crb && " + tools)
            dependencies = document.get("build_dependencies", {}).get(package_format, [])
            target_dependencies = selected["target"]["build"].get("dependencies", [])
            require(isinstance(dependencies, list) and isinstance(target_dependencies, list),
                    "build dependencies must be arrays")
            dependencies = dependencies + target_dependencies
            require(
                isinstance(dependencies, list)
                and all(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+_.:-]*", name)
                        for name in dependencies),
                "invalid source-declared build dependencies",
            )
            if dependencies:
                installer = ("apt-get install -y --no-install-recommends" if package_format == "deb"
                             else "dnf install -y --setopt=install_weak_deps=False")
                tools += " && " + installer + " " + " ".join(shlex.quote(name) for name in dependencies)
        mounts = [
            "--mount",
            "type=bind,source=" + str(tooling / "core_ci") + ",target=/tool,readonly",
            "--mount",
            "type=bind,source=" + str(work / "assignment.json") + ",target=/assignment.json,readonly",
            "--mount",
            "type=bind,source=" + str(work / "target.json") + ",target=/target.json,readonly",
            "--mount",
            "type=bind,source=" + str(work / "environment.json") + ",target=/environment.json,readonly",
            "--mount",
            "type=bind,source=" + str(work / "prerequisites") + ",target=/prerequisites,readonly",
        ]
        if family == "openwrt":
            roots = list((Path(os.environ["RUNNER_TEMP"]) / "core-ci-sdk/extracted").iterdir())
            require(len(roots) == 1, "resolved SDK workspace is unavailable")
            shutil.move(str(roots[0]), work / "sdk")
            (work / ".dockerignore").write_text("sdk\n")
            mounts += ["--mount", "type=bind,source=" + str(work / "sdk") + ",target=/sdk,readonly",
                       "--env", "CORE_CI_APK=/sdk/staging_dir/host/bin/apk"]
            install = ""
        (work / "Dockerfile").write_text(
            "FROM "
            + image
            + "\nRUN "
            + tools
            + "\nCOPY core_ci /tool\nCOPY prerequisites /prerequisites\n"
            + "COPY assignment.json /assignment.json\n"
            + install + "RUN mkdir -p /work && chmod 1777 /work && "
            + "(getent passwd 1000 >/dev/null || useradd -u 1000 -U -M -d /tmp builder)\n"
        )
        try:
            subprocess.run(["docker", "pull", "--platform", platform, image], check=True, timeout=600)
            metadata = json.loads(output(["docker", "image", "inspect", image]))
            require(
                len(metadata) == 1 and metadata[0]["Id"] == host["config_digest"],
                "resolved image configuration changed",
            )
            # Hosted runner UID need not be the container UID. Every mounted input is read-only.
            for path in work.rglob("*"):
                if not path.is_symlink():
                    path.chmod(0o755 if path.is_dir() else path.stat().st_mode | 0o444)
            subprocess.run(
                [
                    "docker",
                    "build",
                    "--platform",
                    platform,
                    "--tag",
                    tag,
                    "--file",
                    str(work / "Dockerfile"),
                    str(work),
                ],
                check=True,
                timeout=1200,
            )
            common = [
                "docker",
                "run",
                "--rm",
                "--init",
                "--user=1000:1000",
                "--platform",
                platform,
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=256",
                "--memory=4g",
                "--cpus=2",
            ]
            subprocess.run(
                common
                + mounts
                + [
                    "--read-only",
                    "--tmpfs",
                    "/tmp:rw,exec,size=2g,mode=1777",
                    "--volume",
                    "/work",
                    "--mount",
                    "type=bind,source=" + str(work / "source") + ",target=/source,readonly",
                    "--mount",
                    "type=bind,source=" + str(work / "definition") + ",target=/definition,readonly",
                    "--mount",
                    "type=bind,source=" + str(destination) + ",target=/output",
                    tag,
                    "python3",
                    "/tool/native_container.py" if family == "native" else "/tool/openwrt_container.py",
                ],
                check=True,
                timeout=3600,
            )
            # Hook container has exited. No source process can race the independent validation.
            result = subprocess.run(
                common
                + [
                    "--network=none",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:rw,size=64m,mode=1777",
                    "--tmpfs",
                    "/work:rw,size=1g,mode=1777",
                ]
                + mounts
                + [
                    "--mount",
                    "type=bind,source=" + str(destination) + ",target=/work/output,readonly",
                    tag,
                    "python3",
                    "-c",
                    "import sys; sys.path.insert(0, '/tool'); from contract import *; s=assignment('/assignment.json'); "
                    "print(canonical(validate_outputs(s, '/work/output', "
                    "read_json('/work/output/outputs.json'), read_json('/environment.json'))))",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                timeout=300,
            )
            manifest = json.loads(result.stdout)
            require(
                manifest["environment"] == environment
                and all(manifest[key] == value for key, value in evidence(selected).items()),
                "container changed trusted environment or assignment evidence",
            )
            (destination / "outputs.json").unlink()
            write_json(destination / "manifest.json", manifest)
        finally:
            subprocess.run(
                ["docker", "image", "rm", tag], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
