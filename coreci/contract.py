"""Shared build and publisher validation primitives."""

import hashlib
from email.parser import Parser
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import resource
import tempfile
import tarfile
import urllib.parse
import zipfile

MAX_FILE = 512 * 1024 * 1024
MAX_EXPANDED = 1024 * 1024 * 1024
MAX_ENTRIES = 20000
SEMVER = re.compile(
    r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?\Z"
)


def require(condition, message):
    if not condition:
        raise ValueError(message)

def canonical(value):
    result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return result

def file_hash(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as incoming:
        block = incoming.read(1024 * 1024)
        while block:
            checksum.update(block)
            block = incoming.read(1024 * 1024)
    result = checksum.hexdigest()
    return result

def read_json(path, limit=2 * 1024 * 1024):
    require(Path(path).stat().st_size <= limit, "JSON exceeds the contract resource bound")
    result = json.loads(Path(path).read_text())
    return result

def write_json(path, value):
    Path(path).write_text(canonical(value) + "\n")

def run(arguments, timeout=120, **options):
    completed = subprocess.run(arguments, check=True, text=True, timeout=timeout, **options)
    return completed

def output(arguments):
    # Bound tool output while it is produced, rather than after allocating it in memory.
    limit = 2 * 1024 * 1024
    temporary = os.environ.get("RUNNER_TEMP", os.environ.get("TMPDIR"))
    with tempfile.TemporaryFile(dir=temporary) as stdout, tempfile.TemporaryFile(dir=temporary) as stderr:
        subprocess.run(
            arguments,
            check=True,
            stdout=stdout,
            stderr=stderr,
            timeout=120,
            preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit)),
        )
        stdout.seek(0)
        result = stdout.read(limit + 1).decode().strip()
        require(len(result.encode()) <= limit, "tool metadata exceeds resource bound")
    return result

def relative_path(name):
    path = PurePosixPath(name)
    require(isinstance(name, str) and 0 < len(name) <= 512 and not path.is_absolute(), "invalid relative path")
    require(all(part not in ("", ".", "..") for part in name.split("/")), "unsafe archive path")
    require("\\" not in name and all(32 < ord(char) < 127 for char in name), "unsupported path characters")
    return path

def regular_file(root, name):
    relative_path(name)
    path = Path(root) / name
    require(path.is_file() and not path.is_symlink(), "expected a regular file")
    require(path.resolve().is_relative_to(Path(root).resolve()), "file escapes its root")
    require(path.stat().st_size <= MAX_FILE, "file exceeds resource bound")
    return path

def extract_archive(archive, destination, kind):
    require(Path(archive).stat().st_size <= MAX_FILE, "compressed archive exceeds resource bound")
    destination = Path(destination)
    require(not destination.exists(), "archive destination must be new")
    seen = set()
    total = 0
    members = []
    with zipfile.ZipFile(archive) if kind == "zip" else tarfile.open(archive, "r:*") as opened:
        entries = opened.infolist() if kind == "zip" else opened.getmembers()
        require(len(entries) <= MAX_ENTRIES, "too many archive entries")
        for entry in entries:
            name = entry.filename.rstrip("/") if kind == "zip" else entry.name.rstrip("/")
            path = relative_path(name)
            require(name not in seen, "duplicate archive entry")
            seen.add(name)
            if kind == "zip":
                mode = entry.external_attr >> 16
                directory = entry.is_dir()
                require(not entry.flag_bits & 1, "encrypted archive not supported")
                require(
                    stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), "archive links/special files are forbidden"
                )
                size = entry.file_size
            else:
                directory = entry.isdir()
                require(entry.isfile() or directory, "export links/special files are forbidden")
                size = entry.size
            total += size
            require(0 <= size <= MAX_FILE and total <= MAX_EXPANDED, "expanded archive exceeds resource bound")
            members.append((entry, path, directory))
        destination.mkdir(parents=True)
        for entry, path, directory in members:
            target = destination / path
            if directory:
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with opened.open(entry) if kind == "zip" else opened.extractfile(entry) as incoming, target.open(
                    "xb"
                ) as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                target.chmod(0o644)

def package_metadata(path, package_format):
    if package_format == "deb":
        fields = [
            output(["dpkg-deb", "--field", str(path), field])
            for field in ("Package", "Version", "Architecture", "Depends", "Pre-Depends")
        ]
        result = {
            "name": fields[0],
            "version": fields[1],
            "arch": fields[2],
            "dependencies": [value for value in fields[3:] if value],
        }
    elif package_format == "rpm":
        text = output(
            [
                "rpm",
                "-qp",
                "--nosignature",
                "--nodigest",
                "--queryformat",
                "%{NAME}\n%{VERSION}-%{RELEASE}\n%{ARCH}\n%{EPOCHNUM}",
                str(path),
            ]
        )
        fields = text.splitlines()
        require(len(fields) == 4 and fields[3] == "0", "unexpected RPM epoch/metadata")
        dependencies = output(["rpm", "-qp", "--nosignature", "--nodigest", "--requires", str(path)]).splitlines()
        result = {"name": fields[0], "version": fields[1], "arch": fields[2], "dependencies": dependencies}
    elif package_format == "ipk":
        with tempfile.TemporaryDirectory(prefix="core-ci-ipk-", dir=os.environ.get("RUNNER_TEMP")) as temporary:
            controls = Path(temporary) / "control.tar.gz"
            with controls.open("wb") as outgoing:
                subprocess.run(
                    ["tar", "-xzOf", str(path), "./control.tar.gz"],
                    check=True,
                    stdout=outgoing,
                    stderr=subprocess.PIPE,
                    timeout=120,
                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024**2, 2 * 1024**2)),
                )
            control = Parser().parsestr(output(["tar", "-xzOf", str(controls), "./control"]), headersonly=True)
        require(
            all(len(control.get_all(key, [])) == 1 for key in ("Package", "Version", "Architecture")),
            "invalid IPK control fields",
        )
        result = {
            "name": control["Package"],
            "version": control["Version"],
            "arch": control["Architecture"],
            "dependencies": control.get("Depends", ""),
        }
    elif package_format == "apk":
        tool = os.environ["CORE_CI_APK"]
        require(
            output([tool, "--version"]).startswith("apk-tools 3."), "APK metadata requires selected SDK apk-tools v3"
        )
        document = json.loads(output([tool, "adbdump", "--format", "json", str(path)]))
        info = document["info"]
        result = {
            "name": info["name"],
            "version": info["version"],
            "arch": info["arch"],
            "dependencies": info.get("depends", []),
        }
    else:
        raise ValueError("unsupported package format")
    return result

def compatibility(selected, environment=None):
    target = selected["target"]
    result = {key: target[key] for key in ("family", "distribution", "suite", "arch")}
    result["format"] = target["build"]["format"]
    if target["family"] == "native":
        result["platform"] = target["build"]["platform"]
    else:
        result.update(
            {
                "release": environment["release"],
                "target": target["build"]["target"],
                "sdk_sha256": environment["sdk"]["sha256"],
                "toolchain": environment["toolchain"],
            }
        )
    return result

def build_summary(value):
    require(isinstance(value, dict) and set(value) <= {"compilers", "tests"}, "unsupported build summary")
    require(len(canonical(value).encode()) <= 8192, "build summary exceeds resource bound")
    compilers = value.get("compilers", [])
    require(isinstance(compilers, list) and len(compilers) <= 16, "invalid compiler summary")
    for compiler in compilers:
        require(isinstance(compiler, dict) and set(compiler) == {"name", "version"}, "invalid compiler fields")
        require(
            all(
                isinstance(text, str) and 0 < len(text) <= 512 and all(ord(c) >= 32 for c in text)
                for text in compiler.values()
            ),
            "invalid compiler text",
        )
    if "tests" in value:
        tests = value["tests"]
        require(
            isinstance(tests, dict)
            and {"passed", "failed", "skipped"}
            <= set(tests)
            <= {"passed", "failed", "skipped", "coverage_percent", "report_url"},
            "invalid test summary fields",
        )
        require(
            all(type(tests[key]) is int and 0 <= tests[key] <= 10000000 for key in ("passed", "failed", "skipped")),
            "invalid test counts",
        )
        if "coverage_percent" in tests:
            coverage = tests["coverage_percent"]
            require(type(coverage) in (int, float) and 0 <= coverage <= 100, "invalid reported coverage")
        if "report_url" in tests:
            require(
                isinstance(tests["report_url"], str) and len(tests["report_url"]) <= 2048, "invalid test report URL"
            )
            url = urllib.parse.urlsplit(tests["report_url"])
            require(
                url.scheme == "https"
                and url.hostname
                and not url.username
                and not url.password
                and all(ord(char) >= 32 for char in tests["report_url"]),
                "test report requires a public HTTPS URL",
            )
    return value
