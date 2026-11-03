"""Bounded deployment-owned templates over verified publication evidence."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
from urllib.parse import quote, urlsplit

from jinja2 import FileSystemLoader, StrictUndefined
from jinja2.sandbox import ImmutableSandboxedEnvironment

from contract import canonical, read_json, regular_file, relative_path, require


def render(feed, templates=None):
    feed = Path(feed)
    templates = Path(templates) if templates is not None else Path(__file__).resolve().parents[1] / "status-templates"
    require(not templates.is_symlink() and templates.is_dir(), "templates require a trusted regular directory")
    size = 0
    for file in templates.rglob("*"):
        require(not file.is_symlink(), "template bundle cannot contain links")
        if file.is_file():
            size += file.stat().st_size
    require(size <= 4 * 1024 * 1024, "template bundle exceeds resource bound")
    site = read_json(regular_file(templates, "presentation.json"), 65536)
    require(
        site.get("schema") == 1 and set(site) <= {"schema", "title", "parameters", "projects", "assets"},
        "invalid presentation settings",
    )
    require(
        isinstance(site.get("title"), str) and isinstance(site.get("parameters", {}), dict),
        "invalid presentation parameters",
    )
    require(isinstance(site.get("projects", {}), dict), "invalid project presentation settings")
    controller_path = feed / "status/controller.json"
    controller = read_json(regular_file(feed, "status/controller.json"), 8 * 1024 * 1024) if controller_path.exists() else None
    rows = []
    for path in sorted((feed / "receipts").glob("*/*.json")):
        require(
            not path.is_symlink() and not path.parent.is_symlink() and not (feed / "receipts").is_symlink(),
            "status receipts cannot contain links",
        )
        receipt = read_json(path)
        require(receipt["schema"] == 1, "unsupported status receipt schema")
        build = receipt["build_result"]["run"]["html_url"]
        publication = receipt["run"]["html_url"]
        for url in (build, publication):
            require(
                re.fullmatch(r"https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/[0-9]+", url),
                "invalid status execution URL",
            )
        repository = build.split("/actions/runs/")[0].removeprefix("https://github.com/")
        base = receipt["feed"]["base_url"].rstrip("/") + "/"
        feed_tree_url = "https://github.com/" + quote(receipt["feed"]["repository"]) + "/tree/" + quote(receipt["feed"]["branch"], safe="") + "/"
        address = urlsplit(base)
        require(
            address.scheme == "https"
            and address.hostname
            and not address.username
            and not address.password
            and not address.query
            and not address.fragment,
            "status feed requires HTTPS",
        )
        coordinates = receipt["compatibility"]
        recorded = next((item for item in controller["executions"] if item["id"] == receipt.get("execution")), None) if controller else None
        source = receipt.get("source") or ({"tag": recorded["tag"], "commit": recorded["source_commit"],
                                           "definition_revision": recorded["definition_revision"]} if recorded else None)
        job = receipt.get("build_job")
        duration = None
        if job and job.get("started_at") and job.get("completed_at"):
            start = datetime.fromisoformat(job["started_at"].replace("Z", "+00:00"))
            finish = datetime.fromisoformat(job["completed_at"].replace("Z", "+00:00"))
            require(
                start.utcoffset() is not None and finish.utcoffset() is not None and finish >= start,
                "invalid assigned job timing",
            )
            duration = (finish - start).total_seconds()
        for package in receipt["packages"]:
            relative_path(package["path"])
            if (feed / package["path"]).is_file():
                rows.append(
                    {
                        "execution": receipt.get("execution"),
                        "attempt": receipt.get("attempt"),
                        "repository": repository,
                        "target": "/".join(coordinates[key] for key in ("distribution", "suite", "arch", "format")),
                        "coordinates": coordinates,
                        "target_row": receipt.get("target"),
                        "package": package["name"],
                        "version": package["version"],
                        "source": source,
                        "revision": receipt.get("revision", int(path.stem)),
                        "dependencies": receipt.get("dependencies"),
                        "source_commit": receipt["source_commit"],
                        "sha256": package["sha256"],
                        "package_url": base + quote(package["path"]),
                        "package_directory": quote(package["path"].rpartition("/")[0]) + "/",
                        "feed_tree_url": feed_tree_url,
                        "receipt_url": base + quote(path.relative_to(feed).as_posix()),
                        "build_url": build,
                        "publication_url": publication,
                        "build_job": job,
                        "build_duration_seconds": duration,
                        "environment": receipt.get("environment"),
                        "development_export_available": bool(receipt.get("development_export") and
                            (feed / receipt["development_export"]["path"]).is_file()),
                        "summary": receipt.get("summary"),
                        "published_utc": recorded["publication_verified_utc"] if recorded and recorded["attempt"] == receipt.get("attempt")
                                         else receipt.get("published_utc"),
                    }
                )
    rows.sort(key=lambda row: (row["repository"], row["target"], row["package"], row["version"], row["receipt_url"]))
    projects = []
    selected_projects = {item["repository"]: item for item in controller["projects"]} if controller else {}
    executions = controller["executions"] if controller else []
    for repository in sorted({row["repository"] for row in rows} | set(selected_projects)):
        selected = selected_projects.get(repository, {})
        work = [item for item in executions if item["repository"] == repository]
        publications = [row for row in rows if row["repository"] == repository]
        settings = site.get("projects", {}).get(repository, {})
        require(isinstance(settings, dict), "project presentation must be an object")
        name = settings.get("page", repository.split("/")[1])
        require(
            isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", name),
            "invalid project status page name",
        )
        status_path = "status/" + ("README/" if name == "README" else "") + name + ".md"
        targets = []
        coordinates = {"/".join(target[key] for key in ("distribution", "suite", "arch", "format")): target
                       for target in selected.get("targets", [])}
        coordinates.update({row["target"]: row["coordinates"] for row in publications})
        for item in work:
            coordinates["/".join(item["coordinates"][key] for key in ("distribution", "suite", "arch", "format"))] = item["coordinates"]
        for identity in sorted(coordinates):
            items = [row for row in publications if row["target"] == identity]
            target_work = sorted([item for item in work if item["coordinates"] == coordinates[identity]],
                                 key=lambda item: item["revision"], reverse=True)
            targets.append({"coordinates": coordinates[identity], "publications": items, "executions": target_work})
        projects.append(
            {
                "repository": repository,
                "title": settings.get("title", selected.get("title", repository)),
                "versions": selected.get("versions", []),
                "executions": work,
                "parameters": settings,
                "status_path": status_path,
                "targets": targets,
                "publications": publications,
            }
        )
    context = {"schema": 1, "site": site, "projects": projects, "publications": rows, "controller": controller}
    environment = ImmutableSandboxedEnvironment(
        loader=FileSystemLoader(templates), undefined=StrictUndefined, autoescape=True
    )
    environment.globals.clear()
    outputs = {"status.json": (canonical(context) + "\n").encode()}
    pages = [
        ("index.html", "index.html.j2", None),
        ("status/index.html", "index.html.j2", None),
        ("status/README.md", "index.md.j2", None),
    ]
    for project in projects:
        require(
            all(path != project["status_path"] for path, template, page_project in pages),
            "colliding project status pages",
        )
        pages.append((project["status_path"], "project.md.j2", project))
        pages.append((project["status_path"].removesuffix(".md") + ".html", "project.md.j2", project))
    for path, template, project in pages:
        chunks = []
        size = 0
        for chunk in environment.get_template(template).generate(**context, project=project, output_path=path):
            size += len(chunk.encode())
            require(size <= 4 * 1024 * 1024, "rendered status page exceeds resource bound")
            chunks.append(chunk)
        outputs[path] = "".join(chunks).encode()
    assets = site.get("assets", [])
    require(isinstance(assets, list) and len(assets) <= 64, "invalid status assets")
    for name in assets:
        relative_path(name)
        require(name.startswith("assets/"), "status assets must be inside the bundle's assets directory")
        outputs["status/" + name] = regular_file(templates, name).read_bytes()
    require(sum(len(data) for data in outputs.values()) <= 32 * 1024 * 1024, "status output exceeds resource bound")
    # Validate/render everything before changing status files. Packages/keys/receipts are never outputs.
    for path in outputs:
        require(
            all(not (feed / parent).is_symlink() for parent in Path(path).parents), "linked status parent directory"
        )
        destination = feed / path
        require(
            not destination.is_symlink() and destination.resolve().is_relative_to(feed.resolve()),
            "unsafe status destination",
        )
    for path, data in outputs.items():
        destination = feed / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return list(outputs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", required=True)
    parser.add_argument("--templates")
    arguments = parser.parse_args()
    print(json.dumps(render(arguments.feed, arguments.templates)))
