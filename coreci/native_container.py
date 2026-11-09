import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

if __package__:
    from .contract import output, package_metadata, read_json, require, write_json
    from .versions import versions
else:
    from contract import output, package_metadata, read_json, require, write_json
    from versions import versions


def package(build):
    """Use the source's CPack component model; emit the existing hook output contract."""
    target = read_json(os.environ["TARGET_JSON"])
    package_format = target["build"]["format"]
    destination = Path(os.environ["OUTPUT_DIR"])
    encoded = versions(os.environ["SOURCE_VERSION"], int(os.environ["PACKAGE_REVISION"]), package_format, target)
    directory = Path(build).resolve() / "core-ci-packages"
    arguments = [
        "cpack", "--config", str(Path(build).resolve() / "CPackConfig.cmake"),
        "-G", package_format.upper(), "-B", str(directory),
        "-D", "CPACK_OUTPUT_FILE_PREFIX=" + str(directory),
        "-D", "CPACK_PACKAGE_VERSION=" + (encoded["full"] if package_format == "deb" else encoded["version"]),
        "-D", "CPACK_DEBIAN_PACKAGE_VERSION=" + encoded["full"],
        "-D", "CPACK_RPM_PACKAGE_RELEASE=" + encoded["release"],
        "-D", "CPACK_RPM_PACKAGE_RELEASE_DIST=OFF",
        "-D", "CPACK_PACKAGE_CONTACT=Volker Christian <me@vchrist.at>",
    ]
    subprocess.run(arguments, cwd=build, check=True, timeout=3600)
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


if __name__ == "__main__":
    package(sys.argv[2])
