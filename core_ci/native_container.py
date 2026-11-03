"""Trusted container bootstrap; the source hook runs as an unprivileged child."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from contract import assignment, output, package_metadata, read_json, require, versions, write_json


def package(build):
    """Use the source's CPack component model; emit the existing hook output contract."""
    target = read_json(os.environ["TARGET_JSON"])
    package_format = target["build"]["format"]
    destination = Path(os.environ["OUTPUT_DIR"])
    encoded = versions(os.environ["SOURCE_VERSION"], int(os.environ["PACKAGE_REVISION"]), package_format)
    directory = Path(build).resolve() / "core-ci-packages"
    arguments = [
        "cpack", "--config", str(Path(build).resolve() / "CPackConfig.cmake"),
        "-G", package_format.upper(), "-B", str(directory),
        "-D", "CPACK_PACKAGE_VERSION=" + (encoded["full"] if package_format == "deb" else encoded["version"]),
        "-D", "CPACK_DEBIAN_PACKAGE_VERSION=" + encoded["full"],
        "-D", "CPACK_RPM_PACKAGE_RELEASE=" + encoded["release"],
        "-D", "CPACK_RPM_PACKAGE_RELEASE_DIST=OFF",
        "-D", "CPACK_PACKAGE_CONTACT=Volker Christian <me@vchrist.at>",
    ]
    subprocess.run(arguments, cwd=build, check=True, timeout=600)
    packages = []
    for path in sorted(directory.glob("*." + package_format)):
        metadata = package_metadata(path, package_format)
        require(metadata["version"] == encoded["full"], "CPack package version differs from assignment")
        shutil.copyfile(path, destination / path.name)
        packages.append({"file": path.name, "component": metadata["name"]})
    require(bool(packages), "CPack produced no packages")
    summary = {"compilers": [{"name": "c++", "version": output(["c++", "--version"]).splitlines()[0]}]}
    report = Path(build) / "core-ci-tests.xml"
    if report.exists():
        cases = list(ET.parse(report).getroot().iter("testcase"))
        failed = sum(case.find("failure") is not None or case.find("error") is not None for case in cases)
        skipped = sum(case.find("skipped") is not None for case in cases)
        summary["tests"] = {"passed": len(cases) - failed - skipped, "failed": failed, "skipped": skipped}
        require(failed == 0, "source tests failed")
    write_json(destination / "outputs.json", {"packages": packages, "summary": summary})


def main():
    selected = assignment("/assignment.json")
    target = selected["target"]
    package_format = target["build"]["format"]
    values = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" in line:
            name, value = line.split("=", 1)
            values[name] = shlex.split(value)[0] if value else ""
    distribution = "debian" if target["distribution"] == "raspberrypios" else target["distribution"]
    require(values.get("ID") == distribution, "image distribution differs from target")
    if target["distribution"] == "raspberrypios":
        require(Path("/etc/rpi-issue").is_file(), "target requires the official Raspberry Pi OS root filesystem")
    require(
        target["suite"] in (values.get("VERSION_ID"), values.get("VERSION_CODENAME")),
        "image series differs from target",
    )
    arch = (
        output(["dpkg", "--print-architecture"]) if package_format == "deb" else output(["rpm", "--eval", "%{_arch}"])
    )
    require(arch == target["arch"], "image package architecture differs from target")
    package_files = []
    expected = []
    for directory in Path("/prerequisites").iterdir():
        receipt = read_json(directory / "receipt.json")
        for package in receipt["packages"]:
            package_files.append(str(directory / package["file"]))
            expected.append(package)
    # Dependency installation happens while preparing the disposable build image, before hooks.
    if "--install" in sys.argv:
        if package_files:
            if package_format == "deb":
                subprocess.run(["apt-get", "update"], check=True, timeout=300)
                subprocess.run(
                    ["apt-get", "install", "--yes", "--no-install-recommends", *package_files], check=True, timeout=300
                )
            else:
                subprocess.run(
                    ["dnf", "install", "--assumeyes", "--setopt=install_weak_deps=False", *package_files],
                    check=True,
                    timeout=300,
                )
    else:
        execute_hook(selected, target, package_format, expected)


def execute_hook(selected, target, package_format, expected):
    require(
        os.getuid() == 1000 and os.getgid() == 1000, "source hooks require the isolated unprivileged container user"
    )
    for package in expected:
        actual = (
            output(["dpkg-query", "--show", "--showformat=${Version}", package["name"]])
            if package_format == "deb"
            else output(["rpm", "-q", "--queryformat", "%{VERSION}-%{RELEASE}", package["name"]])
        )
        require(actual == package["version"], "package manager substituted a prerequisite version")
    source = Path("/work/source")
    shutil.copytree("/source", source, symlinks=True)
    ci = Path("/definition")
    hook = (ci / selected["source"]["build"]["native"]).resolve()
    require(hook.is_relative_to(ci) and hook.is_file(), "hook escapes selected CI checkout")
    encoded = versions(selected["source"]["tag"], selected["revision"], package_format)
    environment = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "SOURCE_DIR": str(source),
        "CI_DIR": str(ci),
        "TARGET_JSON": "/target.json",
        "SOURCE_VERSION": selected["source"]["tag"],
        "SOURCE_COMMIT": selected["source"]["commit"],
        "PACKAGE_REVISION": str(selected["revision"]),
        "PACKAGE_VERSION": encoded["full"],
        "PACKAGE_UPSTREAM_VERSION": encoded["version"],
        "PACKAGE_RELEASE": encoded["release"],
        "PACKAGE_NAMESPACE": selected["source"]["package"],
        "PREREQUISITES_DIR": "/prerequisites",
        "OUTPUT_DIR": "/output",
    }
    subprocess.run(
        ["/bin/sh", str(hook)],
        cwd=source,
        env=environment,
        check=True,
        timeout=3000,
    )


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--package":
        package(sys.argv[2])
    else:
        main()
