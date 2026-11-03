"""Shared build/publisher contract. Assignments grant authority; manifests never do."""

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
import urllib.request
import zipfile

MAX_FILE = 512 * 1024 * 1024
MAX_EXPANDED = 1024 * 1024 * 1024
MAX_ENTRIES = 20000
NAME = re.compile(r"[a-z0-9][a-z0-9+.-]{0,127}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
SHA1 = re.compile(r"[a-f0-9]{40}\Z")
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


def digest(value):
    result = hashlib.sha256(canonical(value).encode()).hexdigest()
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


def run(arguments, **options):
    completed = subprocess.run(arguments, check=True, text=True, timeout=120, **options)
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


def versions(tag, revision, package_format):
    match = SEMVER.fullmatch(tag)
    require(match is not None and type(revision) is int and 0 < revision < 2**64, "invalid source/rebuild version")
    require(package_format in ("deb", "rpm", "ipk", "apk"), "unsupported package format")
    upstream = ".".join(match.group(index) for index in (1, 2, 3))
    tokens = []
    if match.group(4):
        for identifier in match.group(4).split("."):
            if identifier.isdigit():
                require(identifier == "0" or not identifier.startswith("0"), "leading zero in prerelease identifier")
                tokens.extend([1, len(identifier), *map(int, identifier)])
            else:
                tokens.extend([2, *map(ord, identifier), 0])
        tokens.append(0)
        if package_format == "apk":
            upstream += "_pre0" + "".join("_p" + str(token) for token in tokens)
        else:
            upstream += "~" + ".".join("p" + str(token) for token in tokens)
    release = str(revision) if package_format in ("deb", "rpm") else "r" + str(revision)
    require(len(upstream + "-" + release) <= 240, "encoded package version exceeds supported length")
    result = {"version": upstream, "release": release, "full": upstream + "-" + release}
    return result


def assignment(path, expected_hash=None):
    selected = read_json(path, 60000)
    require(selected["schema"] == 1, "unsupported assignment schema")
    execution = selected["execution"]
    require(
        SHA256.fullmatch(execution) and selected["attempt"] == execution + ":" + str(selected["revision"]),
        "assignment identity mismatch",
    )
    require(
        re.fullmatch(r"[A-Za-z0-9_-]{1,200}", selected["artifact_name"]) is not None, "invalid assigned artifact name"
    )
    require(expected_hash is None or digest(selected) == expected_hash, "assignment digest mismatch")
    source = selected["source"]
    require(SHA1.fullmatch(source["deployment"]["worker"]["tooling_sha"]), "tooling must select an exact commit")
    if "kind" in selected:
        require(selected["kind"] == "retention" and isinstance(selected["objects"], list), "invalid retention command")
    else:
        require(
            SHA1.fullmatch(source["commit"]) and SHA1.fullmatch(source["definition_revision"]),
            "source must select exact commits",
        )
        require(
            SHA1.fullmatch(source["definition_blob_sha"]) and NAME.fullmatch(source["package"]),
            "invalid source definition identity",
        )
        versions(source["tag"], selected["revision"], selected["target"]["build"]["format"])
    return selected


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


def evidence(selected):
    result = {
        key: selected[key]
        for key in (
            "schema",
            "execution",
            "attempt",
            "revision",
            "artifact_name",
            "source",
            "target",
            "dependencies",
        )
    }
    result["assignment_sha256"] = digest(selected)
    return result


def publication_receipt(selected, build_result, publication_run, manifest):
    result = {
        "schema": 1,
        "execution": selected["execution"],
        "attempt": selected["attempt"],
        "assignment_sha256": digest(selected),
        "source_commit": selected["source"]["commit"],
        "source": {
            key: selected["source"].get(key)
            for key in ("repository", "title", "package", "tag", "definition_revision", "definition_blob_sha")
        },
        "revision": selected["revision"],
        "target": selected["target"],
        "dependencies": [
            {
                key: dependency["receipt"].get(key)
                for key in (
                    "execution",
                    "attempt",
                    "assignment_sha256",
                    "source_commit",
                    "source",
                    "revision",
                    "compatibility",
                    "packages",
                    "development_export",
                    "feed",
                )
            }
            for dependency in selected["dependencies"]
        ],
        "summary": manifest.get("summary"),
        "build_job": manifest.get("build_job"),
        "run": publication_run,
        "build_result": build_result,
        "feed": selected["source"]["deployment"]["feed"],
        "environment": manifest["environment"],
        "compatibility": compatibility(selected, manifest["environment"]),
        "packages": [],
        "development_export": None,
        "indexes": [],
    }
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


def validate_outputs(selected, directory, declared, environment):
    build = selected["target"]["build"]
    if selected["target"]["family"] == "native":
        require(
            environment["image"] == build["image"] and environment["platform"] == build["platform"],
            "image selection mismatch",
        )
        require(
            re.fullmatch(r"sha256:[a-f0-9]{64}", environment["digest"])
            and re.fullmatch(r"sha256:[a-f0-9]{64}", environment["config_digest"])
            and re.fullmatch(r"[a-z0-9][a-z0-9.:/_-]*@sha256:[a-f0-9]{64}", environment["resolved_image"])
            and environment["resolved_image"].endswith("@" + environment["digest"]),
            "invalid immutable image identity",
        )
    else:
        require(
            environment["release"].startswith(selected["target"]["suite"] + ".")
            and SHA256.fullmatch(environment["sdk"]["sha256"]),
            "invalid resolved SDK identity",
        )
    directory = Path(directory)
    require(set(declared) <= {"packages", "development_export", "summary"}, "unknown hook output fields")
    packages = declared["packages"]
    require(isinstance(packages, list) and 0 < len(packages) <= 128, "declare one to 128 package outputs")
    package_format = selected["target"]["build"]["format"]
    expected = versions(selected["source"]["tag"], selected["revision"], package_format)
    namespace = selected["source"]["package"]
    files = set()
    identities = set()
    result = evidence(selected)
    result["environment"] = environment
    result["package_version"] = expected
    if "summary" in declared:
        result["summary"] = build_summary(declared["summary"])
    result["packages"] = []
    for package in packages:
        require(
            set(package) == {"file", "component"} and NAME.fullmatch(package["component"]),
            "invalid declared package component",
        )
        filename = package["file"]
        require("/" not in filename and filename.endswith("." + package_format), "invalid package filename")
        require(filename not in files, "duplicate package output")
        files.add(filename)
        path = regular_file(directory, filename)
        metadata = package_metadata(path, package_format)
        require(
            metadata["name"] == namespace or metadata["name"].startswith(namespace + "-"),
            "package outside assigned namespace",
        )
        require(metadata["name"] == package["component"], "component differs from actual package name")
        require(
            metadata["version"] == expected["full"] and metadata["arch"] == selected["target"]["arch"],
            "package version/architecture differs from assignment",
        )
        identity = (metadata["name"], metadata["version"], metadata["arch"])
        require(identity not in identities, "duplicate package identity")
        identities.add(identity)
        result["packages"].append(
            {
                "file": filename,
                "component": package["component"],
                "size": path.stat().st_size,
                "sha256": file_hash(path),
                **metadata,
            }
        )
    result["development_export"] = None
    if declared.get("development_export") is not None:
        filename = declared["development_export"]
        require(filename == "development.tar.gz", "unsupported development export filename")
        path = regular_file(directory, filename)
        scratch = directory.parent / ("export-check-" + selected["execution"])
        try:
            extract_archive(path, scratch, "tar")
            require(
                all(
                    PurePosixPath(name).parts[0] in ("include", "lib", "share")
                    for name in (str(file.relative_to(scratch)) for file in scratch.rglob("*") if file.is_file())
                ),
                "export must contain only project development files",
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        files.add(filename)
        result["development_export"] = {
            "file": filename,
            "size": path.stat().st_size,
            "sha256": file_hash(path),
            "compatibility": compatibility(selected, environment),
        }
    require({file.name for file in directory.iterdir()} == files | {"outputs.json"}, "undeclared files in hook output")
    return result


def verify_manifest(selected, directory, build_result=None):
    manifest = read_json(Path(directory) / "manifest.json")
    for key, value in evidence(selected).items():
        require(manifest[key] == value, "manifest provenance differs from assignment: " + key)
    declared = {"packages": [{"file": item["file"], "component": item["component"]} for item in manifest["packages"]]}
    if manifest.get("development_export"):
        declared["development_export"] = manifest["development_export"]["file"]
    if "summary" in manifest:
        declared["summary"] = build_summary(manifest["summary"])
    # Job facts are added only by the trusted validator after inspecting GitHub's assigned job.
    if "build_job" in manifest:
        require(build_result is not None, "source artifact cannot declare verified GitHub job facts")
        job = manifest["build_job"]
        require(
            job["id"] == build_result["artifacts"][0]["job_id"]
            and job["run_id"] == build_result["run"]["id"]
            and job["run_attempt"] == 1,
            "build timing/job differs from assigned evidence",
        )
    # Reuse the same independent standard package-tool validation, never trust claimed metadata.
    path = Path(directory)
    temporary = path.parent / ("manifest-check-" + selected["execution"])
    require(not temporary.exists(), "validation workspace exists")
    temporary.mkdir()
    try:
        for name in [item["file"] for item in manifest["packages"]] + (
            [declared["development_export"]] if declared.get("development_export") else []
        ):
            file = regular_file(path, name)
            os.link(file, temporary / name)
        write_json(temporary / "outputs.json", declared)
        actual = validate_outputs(selected, temporary, declared, manifest["environment"])
        if "build_job" in manifest:
            actual["build_job"] = manifest["build_job"]
        require(actual == manifest, "package bytes/metadata/export differ from manifest")
        require(
            {file.name for file in path.iterdir()}
            == {file.name for file in temporary.iterdir()} - {"outputs.json"} | {"manifest.json"},
            "unexpected artifact files",
        )
    finally:
        shutil.rmtree(temporary)
    return manifest


class FeedDownload(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        require(
            urllib.parse.urlsplit(request.full_url)[:2] == urllib.parse.urlsplit(new_url)[:2],
            "feed redirect changes origin",
        )
        result = super().redirect_request(request, response, code, message, headers, new_url)
        return result


def download_feed(base, name, destination, expected):
    relative_path(name)
    parsed = urllib.parse.urlsplit(base)
    require(
        parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.query and not parsed.fragment,
        "feed requires HTTPS",
    )
    require(
        type(expected["size"]) is int and 0 < expected["size"] <= MAX_FILE and SHA256.fullmatch(expected["sha256"]),
        "invalid feed object identity",
    )
    destination = Path(destination)
    opener = urllib.request.build_opener(FeedDownload())
    try:
        with opener.open(
            base.rstrip("/") + "/" + urllib.parse.quote(name, safe="/"), timeout=60
        ) as response, destination.open("xb") as outgoing:
            received = 0
            block = response.read(1024 * 1024)
            while block:
                received += len(block)
                require(received <= expected["size"], "feed object exceeds assigned size")
                outgoing.write(block)
                block = response.read(1024 * 1024)
        require(
            destination.stat().st_size == expected["size"] and file_hash(destination) == expected["sha256"],
            "feed object checksum/size mismatch",
        )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
