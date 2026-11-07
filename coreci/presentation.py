"""Bounded deployment-owned templates over verified publication evidence."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import quote, urlsplit

from jinja2 import FileSystemLoader, StrictUndefined
from jinja2.sandbox import ImmutableSandboxedEnvironment

from contract import canonical, read_json, regular_file, relative_path, require, write_json, file_hash, package_metadata, output, compatibility
import os
import subprocess
import time
import urllib.request
from .common import declaration, metadata, registry, token, https, NoRedirect, github_outputs, workflow_identity
from .lease import retry, push as checked_push, restore_partial
from github import api
from publish import prepare_commit


def render(feed, templates=None, exists=None):
    feed = Path(feed)
    exists = exists or (lambda name: (feed / name).is_file())
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
        repository = (receipt.get("source") or {}).get("repository") or build.split("/actions/runs/")[0].removeprefix("https://github.com/")
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
            if exists(package["path"]):
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
                            exists(receipt["development_export"]["path"])),
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


def utc(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace('+00:00', 'Z') if seconds is not None else None


def job(run_id, repository, cache):
    identity = str(run_id)
    result = cache.get(identity)
    if run_id and not result:
        rows = api(f'/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100', token())["jobs"]
        selected = [item for item in rows if item['name'] == 'build']
        if selected:
            result = selected[0]['html_url']
            cache[identity] = result
    return result


def current_work(unit):
    result = unit['inflight']
    if not result:
        if unit['status'] == 'Failed':
            result = unit['failure']
        elif unit['status'] == 'Settled':
            result = unit['published']
        else:
            result = unit['next']
    return result


def project(status, settings, definitions, identity, cache, lookup=job):
    require(status['schema'] == 1 and type(status['generation']) is int, 'invalid status schema')
    packages = {item['name']: item for item in status['packages']}
    docs = {doc['package']: doc for doc in definitions.values()}
    repositories = {name:item['sourceRepo']['owner']+'/'+item['sourceRepo']['repo'] for name,item in packages.items()}
    selected = [item for item in status['units'] if item['feed'] == identity['id']]
    executions, projects, ids = [], [], {}
    for unit in selected:
        current = current_work(unit)
        if current:
            build_id = f'{unit["package"]}~{unit["target"]}~{current["version"]}~r{current["revision"]}'
            ids[(unit['package'], unit['target'])] = build_id
    for name, package in sorted(packages.items()):
        doc = docs[name]
        repository = repositories[name]
        targets = [entry for entry in doc['matrix'] if entry.get('feed', settings['default_feed']) == identity['id']]
        if targets:
            projects.append(dict(repository=repository, title=doc.get('title', repository),
                versions=[package['released']['tag']] if package['released'] else [],
                targets=[coordinates(entry) for entry in targets]))
    activities = {'Waiting': 'Waiting', 'Blocked': 'Waiting', 'Ready': 'Pending', 'Dispatching': 'Pending',
                  'Building': 'Building', 'AwaitingPublish': 'Publishing', 'Publishing': 'Publishing',
                  'Failed': 'Failed', 'Settled': 'Published'}
    by_unit = {(item['package'], item['target']): item for item in selected}
    for unit in selected:
        key = (unit['package'], unit['target'])
        if unit['status'] != 'NoRelease':
            doc = docs[unit['package']]
            repository = repositories[unit['package']]
            entry = next(entry for entry in doc['matrix'] if entry['id'] == unit['target'])
            current = current_work(unit)
            release = packages[unit['package']]['released']
            activity = activities[unit['status']]
            prerequisites = [(name, unit['target']) for name in doc['depends_on']]
            blockers = [ids[p] for p in prerequisites if by_unit[p]['status'] != 'Settled' and p in ids]
            run_id = current.get('runId')
            workflow_repo = settings['build'].split('/.github/workflows/')[0]
            executions.append(dict(id=ids[key], repository=repository,
                tag=release['tag'] if release and release['version'] == current['version'] else current['version'],
                attempt=ids[key]+':'+str(current.get('attempt', 1)), revision=current['revision'],
                state=activity.lower(), activity=activity, failure=unit['failure']['reason'] if unit['status'] == 'Failed' else None,
                superseded_by=None, prerequisites=[ids[p] for p in prerequisites if p in ids], blockers=blockers,
                coordinates=coordinates(entry), build_job_url=lookup(run_id, workflow_repo, cache) if run_id else None,
                publication_verified_utc=utc(unit['published']['at']) if unit['published'] else None))
    return dict(schema=1, feed={key:identity[key] for key in ('repository','repository_id','branch')}, projects=projects, executions=executions)


def coordinates(entry):
    return {**{key:entry[key] for key in ('distribution','suite','arch')}, 'format':entry['build']['format']}


def status_fetch(url):
    https(url)
    with urllib.request.build_opener(NoRedirect()).open(url, timeout=30) as response:
        require(response.url == url, 'redirected status response')
        raw = response.read(8 * 1024**2 + 1)
    require(len(raw) <= 8 * 1024**2, 'status response exceeds bound')
    return json.loads(raw)


def refresh(root, settings, feed_id, exists=None, status=None):
    root = Path(root)
    state_path = root / 'coreci/presentation.json'
    previous = read_json(state_path) if state_path.exists() else dict(generation=-1, jobs={})
    status = status if status is not None else status_fetch(settings['status_url'])
    paths = []
    if status['generation'] > previous['generation']:
        feed = settings['feeds'][feed_id]
        info = metadata(feed['repository'])
        identity = dict(id=feed_id, repository=feed['repository'], repository_id=info['id'], branch=info['default_branch'])
        definitions = {repo:declaration(repo) for repo in settings['repositories']}
        cache = dict(previous.get('jobs', {}))
        controller = project(status, settings, definitions, identity, cache)
        destination = root / 'status/controller.json'
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_json(destination, controller)
        paths = ['status/controller.json'] + render(root, exists=exists)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(state_path, dict(generation=status['generation'], jobs=cache))
        paths += ['coreci/presentation.json']
    return paths


def receipt(root, manifest, values, feed, paths):
    source = manifest['source']
    require(source['tag'].removeprefix('v') == manifest['version'], 'receipt source tag mismatch')
    require(source['package'] == manifest['package'] and re.fullmatch(r'[0-9a-f]{40}', source['commit']), 'invalid receipt source')
    build_repo, run_id = values['build_repo'], int(values['build_run_id'])
    rows = api(f'/repos/{build_repo}/actions/runs/{run_id}/jobs?per_page=100', token())['jobs']
    builds = [row for row in rows if row['name'] == 'build']
    require(len(builds) == 1, 'receipt requires one build job')
    execution = manifest['build_id']
    packages = []
    for name, relative in paths.items():
        if name != 'development.tar.gz':
            info = package_metadata(Path(root) / relative, manifest['entry']['build']['format'])
            packages.append(dict(path=relative, name=info['name'], version=info['version'], sha256=file_hash(Path(root)/relative)))
    data = dict(schema=1, execution=execution, attempt=execution+':1', source=source, source_commit=source['commit'],
        revision=manifest['revision'], compatibility=compatibility(dict(target=manifest['entry']),manifest['environment']), target=manifest['entry'],
        feed=dict(base_url=feed['url'], repository=feed['repository'], branch=metadata(feed['repository'])['default_branch']),
        build_result=dict(run=dict(html_url=f'https://github.com/{build_repo}/actions/runs/{run_id}')),
        run=dict(html_url=f'https://github.com/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{os.environ["GITHUB_RUN_ID"]}'),
        build_job=builds[0], packages=packages, dependencies=[dict(package=name,version=value[0],revision=value[1])
            for name,value in sorted(manifest.get('prerequisites', {}).items())],
        summary=manifest.get('summary'), environment=manifest['environment'], published_utc=utc(time.time()))
    if 'development.tar.gz' in paths:
        data['development_export'] = dict(path=paths['development.tar.gz'])
    relative = f'receipts/{manifest["build_id"]}/{manifest["revision"]}.json'
    destination = Path(root) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    require(not destination.exists(), 'immutable: receipt already exists')
    write_json(destination, data)
    return relative


def resolve(settings, feed_id):
    feed = settings['feeds'][feed_id]
    require(workflow_identity(feed['presentation']) == workflow_identity(os.environ['GITHUB_WORKFLOW_REF']), 'presentation workflow mismatch')
    owner, repo = feed['repository'].split('/')
    github_outputs(environment=feed['environment'], owner=owner, repository_name=repo, repository=feed['repository'],
                   branch=metadata(feed['repository'])['default_branch'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('resolve','run'))
    parser.add_argument('--root', default='feed')
    args = parser.parse_args()
    settings, feed_id = registry(), os.environ['INPUT_FEED']
    if args.mode == 'resolve':
        resolve(settings, feed_id)
    else:
        root = Path(args.root).resolve()
        feed = settings['feeds'][feed_id]
        require(workflow_identity(feed['presentation']) == workflow_identity(os.environ['GITHUB_WORKFLOW_REF']), 'presentation workflow mismatch')
        branch = metadata(feed['repository'])['default_branch']
        if not root.exists():
            subprocess.run(['git','clone','--filter=blob:none','--no-checkout','--single-branch','--branch',branch,
                            'https://github.com/'+feed['repository']+'.git',str(root)],check=True)
        def attempt():
            base = output(['git','-C',str(root),'rev-parse','HEAD'])
            files = set(output(['git','-C',str(root),'ls-tree','-r','--name-only','HEAD']).splitlines())
            for name in files:
                if name.startswith(('receipts/','status/','docs/','install/')) or name in ('README.md','index.html','status.json','coreci/presentation.json'):
                    destination = root / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    require(not destination.is_symlink(), 'linked presentation file')
                    destination.write_bytes(subprocess.check_output(['git','-C',str(root),'show','HEAD:'+name]))
            changed = refresh(root, settings, feed_id, lambda name:name in files)
            differences = [name for name in changed if name != 'coreci/presentation.json' and
                (name not in files or output(['git','-C',str(root),'hash-object',str(root/name)]) !=
                 output(['git','-C',str(root),'rev-parse','HEAD:'+name]))]
            if changed and differences:
                # Populate the index from the tree, retaining every package without fetching its blob.
                subprocess.run(['git','-C',str(root),'read-tree','HEAD'],check=True)
                subprocess.run(['git','-C',str(root),'update-index','--skip-worktree','-z','--stdin'],check=True,
                    input=''.join(name+'\0' for name in files if not (root/name).exists()).encode())
                prepare_commit(root, changed, 'Update public core-ci status', orphan=True)
                checked_push(root, branch, os.environ['GH_TOKEN'], base)
            return None
        retry(root, attempt, restore_partial)
    return None


if __name__ == '__main__':
    main()
