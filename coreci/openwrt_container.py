"""The source hook outputs interface, executed inside the isolated container."""
import os
from pathlib import Path
import shutil
import sys
from contract import package_metadata, read_json, require, write_json


def outputs():
    target = read_json(os.environ["TARGET_JSON"])
    package_format = target["build"]["format"]
    namespace = os.environ["PACKAGE_NAMESPACE"]
    destination = Path(os.environ["OUTPUT_DIR"])
    packages = []
    for path in sorted((Path(os.environ["SDK_DIR"]) / "bin/packages").rglob(namespace + "*." + package_format)):
        if "core-ci-prerequisites" not in path.parts:
            metadata = package_metadata(path, package_format)
            if metadata["name"] == namespace or metadata["name"].startswith(namespace + "-"):
                require(not (destination / path.name).exists(), "duplicate OpenWrt package output")
                shutil.copyfile(path, destination / path.name)
                packages.append({"file": path.name, "component": metadata["name"]})
    require(bool(packages), "OpenWrt produced no assigned packages")
    declared = {"packages": packages}
    if (destination / "development.tar.gz").exists():
        declared["development_export"] = "development.tar.gz"
    write_json(destination / "outputs.json", declared)


if __name__ == "__main__":
    outputs()
