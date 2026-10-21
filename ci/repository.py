"""Capture an immutable release generation from exact source commits."""
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import http.client
from graphlib import TopologicalSorter
from functools import cache
from math import ceil
import tempfile
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent

def load_master(path):
    value = json.loads(path.read_text())
    defaults = dict(capacity='plan', headroom=2, dependent_version='published', rebuild_overlap=True)
    if not isinstance(value, dict) or set(value) - {'repositories', 'settings'}:
        raise ValueError('Master configuration contains repositories and optional settings only')
    names = value.get('repositories')
    if not isinstance(names, list) or not names or any(not isinstance(n, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,100}', n) or n in {'.', '..'} for n in names) or len({n.casefold() for n in names}) != len(names):
        raise ValueError('repositories must be unique repository names')
    settings = value.get('settings', {})
    if not isinstance(settings, dict) or set(settings) - defaults.keys():
        raise ValueError('Unknown coordinator setting')
    defaults.update(settings)
    if (defaults['capacity'] != 'plan' and (type(defaults['capacity']) is not int or defaults['capacity'] < 3)
            or type(defaults['headroom']) is not int or defaults['headroom'] < 1
            or defaults['dependent_version'] not in ('published', 'latest') or type(defaults['rebuild_overlap']) is not bool
            or type(defaults['capacity']) is int and defaults['headroom'] >= defaults['capacity']):
        raise ValueError('Invalid capacity, headroom, dependent_version or rebuild_overlap setting')
    return dict(repositories=names, settings=defaults)


def rows(config):
    platforms = {'amd64': 'linux/amd64', 'x86_64': 'linux/amd64', 'arm64': 'linux/arm64', 'aarch64': 'linux/arm64', 'armhf': 'linux/arm/v7', 'riscv64': 'linux/riscv64'}
    result = []
    try:
        for family, matrix in config['matrix'].items():
            if family == 'linux':
                for item in matrix:
                    if item['distribution'] not in {'debian', 'ubuntu', 'rocky', 'fedora'} or set(item['architectures']) - platforms.keys() or not re.fullmatch(r'[A-Za-z0-9./:_-]+', item['image']):
                        raise ValueError('Unsupported native distribution or unsafe image')
                    for arch in item['architectures']:
                        build = dict(distribution=item['distribution'], suite=item['suite'], image=item['image'], arch=arch, platform=platforms[arch], runner='ubuntu-24.04-arm' if arch in {'arm64', 'aarch64', 'armhf'} else 'ubuntu-24.04')
                        result.append(dict(family=family, distribution=build['distribution'], suite=build['suite'], arch=arch, runner=build['runner'], build=build))
            elif family == 'raspberrypi':
                for suite, image in matrix.items():
                    if not re.fullmatch(r'[0-9a-f]{64}', image['sha256']) or not image['url'].startswith('https://downloads.raspberrypi.com/'):
                        raise ValueError('Raspberry Pi images need an official URL and SHA256')
                    result.append(dict(family=family, distribution='raspberrypios', suite=suite, arch='arm64', runner='ubuntu-24.04-arm', build=dict(suite=suite, **image)))
            elif family == 'openwrt':
                for release in matrix['releases']:
                    series = release.rsplit('.', 1)[0]
                    if series not in {'24.10', '25.12'} or not re.fullmatch(r'[0-9]{2}\.[0-9]{2}\.[0-9]+', release):
                        raise ValueError('Unsupported OpenWrt release ' + release + '; use 24.10.N or 25.12.N')
                    for arch, target in matrix['targets'].items():
                        if not re.fullmatch(r'[a-z0-9_-]+/[a-z0-9_-]+', target):
                            raise ValueError('Unsafe OpenWrt target')
                        arch = 'riscv64_riscv64' if arch == 'riscv64_generic' and series == '24.10' else arch
                        build = dict(release=release, series=series, target=target, arch=arch)
                        result.append(dict(family=family, distribution='openwrt', suite=series, arch=arch, runner='ubuntu-24.04', build=build))
            else:
                raise ValueError('Unsupported matrix family: ' + family)
        for row in result:
            if any((row[k] in {'.', '..'} or not re.fullmatch(r'[A-Za-z0-9._-]+', row[k])) for k in ('distribution', 'suite', 'arch')):
                raise ValueError('Unsafe target identity')
            row['id'] = '-'.join(row[k] for k in ('distribution', 'suite', 'arch'))
        if not result or len({r['id'] for r in result}) != len(result):
            raise ValueError('Matrix must contain unique targets')
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('Malformed build matrix: ' + str(error)) from error
    return result


def validate_project(name, config):
    if (name not in REPOSITORIES or not isinstance(config, dict) or not {'title', 'package', 'depends_on', 'matrix', 'build'} <= set(config) or set(config) - {'title', 'package', 'depends_on', 'matrix', 'build', '_commit', '_digest', '_tag'}
            or not isinstance(config.get('title'), str) or not config['title'] or not isinstance(config['build'], dict)
            or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', config.get('package', ''))):
        raise ValueError('Invalid repository definition: ' + name)
    if not isinstance(config['depends_on'], list) or len(set(config['depends_on'])) != len(config['depends_on']) or set(config['depends_on']) - set(REPOSITORIES):
        raise ValueError('Invalid registered dependencies: ' + name)
    for family, path in config['build'].items():
        if family not in {'native', 'openwrt'} or not re.fullmatch(r'[A-Za-z0-9_./-]+', path) or Path(path).is_absolute() or '..' in Path(path).parts:
            raise ValueError('Unsafe source build hook: ' + name)
    if {'openwrt' if r['family'] == 'openwrt' else 'native' for r in rows(config)} != set(config['build']):
        raise ValueError('Every supported family needs a source build hook: ' + name)
    return None


def validate_projects(projects):
    if not isinstance(projects, dict) or not projects:
        raise ValueError('A capture needs repository definitions')
    for name, config in projects.items():
        validate_project(name, config)
    if len({c['package'] for c in projects.values()}) != len(projects):
        raise ValueError('Repository package namespaces must be unique')
    order = tuple(TopologicalSorter({n: c['depends_on'] for n, c in projects.items()}).static_order())
    if set(order) != set(projects):
        raise ValueError('Missing dependency definitions')
    return {name: projects[name] for name in order}


def load_projects(path):
    return validate_projects(json.loads(path.read_text())['projects']) if path.exists() else {}


def bind_projects(projects, baseline, project):
    projects = dict(projects)
    pending, visited = list(projects[project]['depends_on']), set()
    while pending:
        dependency = pending.pop()
        if dependency not in visited:
            visited.add(dependency)
            ref = source_commit(baseline.get('sources', {}).get(dependency))
            if ref is not None and projects[dependency].get('_commit') != ref:
                supplied = json.loads(os.environ.get('PACKAGE_REQUEST', '{}')).get('definitions', {})
                if os.environ.get('GITHUB_REPOSITORY') not in (None, '', 'SNodeC/DistributionPackages'):
                    if supplied.get(dependency, {}).get('_commit') != ref:
                        raise ValueError(f'Pinned definition unavailable for {dependency}@{ref} in coordinator request')
                    projects[dependency] = supplied[dependency]
                else:
                    projects[dependency] = definition(dependency, ref)
            pending.extend(projects[dependency]['depends_on'])
    return validate_projects(projects)


def activate(bundle, target, baseline=None, project=None):
    projects = json.loads((bundle / 'profiles.json').read_text())[target]['projects']
    projects = bind_projects(projects, baseline, project) if baseline is not None and project is not None else validate_projects(projects)
    PROJECTS.clear()
    PROJECTS.update(projects)
    Path(os.environ.get('CI_DEFINITIONS', ROOT / 'ci/definitions.json')).write_text(json.dumps(dict(projects=PROJECTS, targets={target: projects})))
    return None


def content(project, path, ref):
    from ci.dispatch import api
    import base64
    value = api(f'repos/SNodeC/{project}/contents/{path}?ref={ref}')
    if value.get('encoding') == 'none':
        value = api(f'repos/SNodeC/{project}/git/blobs/{value["sha"]}')
    return base64.b64decode(value.get('content', ''))


@cache
def definition_data(project, commit):
    data = content(project, 'ci/packages.json', commit)
    config = json.loads(data)
    if not isinstance(config, dict):
        raise ValueError('Source definitions must be objects')
    return config, hashlib.sha256(data).hexdigest()


def definition(project, commit):
    config, checksum = definition_data(project, commit)
    if any(key.startswith('_') for key in config):
        raise ValueError('Source definitions must be objects without capture metadata')
    return dict(config, _commit=commit, _digest=checksum)


def ownership(info):
    from ci.dispatch import ApiError
    facts = {}
    supplied = json.loads(os.environ.get('PACKAGE_REQUEST', '{}')).get('definitions', {})
    source = os.environ.get('GITHUB_REPOSITORY', '')
    for project, refs in info.get('sources', {}).items():
        commit = source_commit(refs)
        if project not in REPOSITORIES or commit is None:
            raise ApiError(422, f'Retained sibling ownership unavailable for {project}@{commit}; register an exact source')
        config = (dict(definition_data(project, commit)[0], _commit=commit)
                  if not source or source == 'SNodeC/DistributionPackages' else supplied.get(project, {}))
        if source.casefold() == ('SNodeC/' + project).casefold() and PROJECTS.get(project, {}).get('_commit') == commit:
            config = PROJECTS[project]
        if config.get('_commit') != commit or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', config.get('package', '')):
            raise ValueError(f'Pinned ownership unavailable for {project}@{commit}; supply its matching package namespace')
        facts[project] = dict(_commit=commit, package=config['package'])
    return facts


def dependent_source(name, row, info, requests):
    from ci.dispatch import api, ApiError, failure
    try:
        previous = ref = source_commit(info.get('sources', {}).get(name))
        request = requests.get(name, {})
        pending = request.get('eligible', True) and request and (
            ref != request['sha'] or project_revision(info, name, ownership(info)) < int(request['revision']))
        tag = request['tag'] if pending else None
        if CONFIG['settings']['dependent_version'] == 'latest' and not pending:
            refs = run('git', 'ls-remote', '--tags', f'https://github.com/SNodeC/{name}.git', 'refs/tags/v*')
            tags = [line.split()[1].removeprefix('refs/tags/') for line in refs.splitlines()
                    if re.fullmatch(r'refs/tags/v[0-9]+\.[0-9]+\.[0-9]+', line.split()[1])]
            tag = max(tags, key=lambda t: tuple(map(int, t[1:].split('.')))) if tags else None
        ref = request['sha'] if pending else source_commit(sources({name: tag})[name]) if tag else ref
        if ref is None:
            branch = api(f'repos/SNodeC/{name}')['default_branch']
            ref = api(f'repos/SNodeC/{name}/git/ref/heads/{branch}')['object']['sha']
        result, reason = dict(definition(name, ref)) | (dict(_tag=tag) if tag else {}), ''
        validate_project(name, result)
        if pending and not supports(name, row, {name: result}):
            if previous is None:
                raise ValueError('Explicit request omits this row and no last-published source exists')
            result = definition(name, previous)
    except (ApiError, ValueError, TypeError, OSError, subprocess.SubprocessError) as error:
        result = None
        reason = ('Source definition temporarily unavailable: ' if failure(error)['category'] == 'transient'
                  else 'Selected source definition excluded: ') + str(error)
    return result, reason


def isolate(projects, errors):
    result = {}
    for name in projects:
        try:
            selected, pending = {}, [name]
            while pending:
                dependency = pending.pop()
                if dependency not in selected:
                    selected[dependency] = projects[dependency]
                    pending.extend(projects[dependency]['depends_on'])
            result = validate_projects(result | selected)
        except (ValueError, KeyError, TypeError) as error:
            errors[name] = 'Invalid pinned dependency graph: ' + str(error)
    return result


def configure(root, project, commit, claimed):
    from ci.publish.publication import published
    current = definition(project, commit)
    if {k: v for k, v in current.items() if not k.startswith('_')} != claimed:
        raise ValueError('Notification matrix does not match its source commit')
    requests = json.loads((root / 'status.json').read_text()).get('requests', {})
    snapshots, failures = {}, {}
    for row in rows(current):
        info, _ = published(root, row)
        choices = {n: dependent_source(n, row, info, requests) for n in REPOSITORIES if n != project}
        selected = {project: current} | {n: c for n, (c, _) in choices.items() if c is not None}
        errors = {n: reason for n, (_, reason) in choices.items() if reason}
        snapshots[row['id']] = isolate(selected, errors)
        if project not in snapshots[row['id']]:
            raise ValueError(project + ': ' + errors[project])
        failures[row['id']] = errors
    PROJECTS.clear()
    PROJECTS.update({n: c for graph in snapshots.values() for n, c in graph.items()})
    ROW_PROJECTS.clear()
    ROW_PROJECTS.update(snapshots)
    DEFINITIONS.write_text(json.dumps(dict(projects=PROJECTS, targets=snapshots, errors=failures)))
    return None


def source_commit(value):
    result = (next((v for k, v in value.items() if k.endswith('^{}')), next(iter(value.values())))
              if isinstance(value, dict) and value else None)
    if result is not None and not re.fullmatch(r'[0-9a-f]{40}', result):
        raise ValueError('Expected an exact source commit')
    return result


CONFIG = load_master(ROOT / "ci/projects.json")
REPOSITORIES = tuple(CONFIG["repositories"])
DEFINITIONS = Path(os.environ.get("CI_DEFINITIONS", ROOT / "ci/definitions.json"))
PROJECTS = load_projects(DEFINITIONS)
ROW_PROJECTS = json.loads(DEFINITIONS.read_text()).get("targets") or {r['id']: PROJECTS for c in PROJECTS.values() for r in rows(c)} if DEFINITIONS.exists() else {}

def missing_prerequisites(project, row, info, revisions, projects):
    return [dependency for dependency in dependencies(project, projects) if not supports(dependency, row, projects) or not info.get('sources', {}).get(dependency) and dependency not in revisions]


def affected(project, projects=None):
    projects = PROJECTS if projects is None else projects
    selected = {project}
    for name, config in projects.items():
        if selected.intersection(config['depends_on']):
            selected.add(name)
    return tuple(name for name in projects if name in selected)


def dependencies(project, projects=None):
    projects = PROJECTS if projects is None else projects
    selected = set(projects[project]['depends_on'])
    for name in reversed(projects):
        if name in selected:
            selected.update(projects[name]['depends_on'])
    return tuple(name for name in projects if name in selected)


def supports(project, row, projects=None):
    projects = PROJECTS if projects is None else projects
    return project in projects and any(r['id'] == row['id'] for r in rows(projects[project]))


def package_owner(name, projects=None):
    projects = PROJECTS if projects is None else projects
    matches = [repo for repo, config in projects.items()
               if name == config['package'] or name.startswith((config['package'] + '-', config['package'] + '_'))]
    result = max(matches, key=lambda repo: len(projects[repo]['package']), default=None)
    return result


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **(dict(timeout=120) if args[0] == 'gh' else {}), **kwargs).strip()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@contextmanager
def signer():
    with tempfile.TemporaryDirectory() as home:
        subprocess.run(['gpg', '--homedir', home, '--batch', '--import'],
                       input=os.environ['APT_SIGNING_KEY'], text=True, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        yield home


def matrix():
    return list({json.dumps(row['build'], sort_keys=True): row['build'] for config in PROJECTS.values() for row in rows(config) if row['family'] == 'openwrt'}.values())


def linux_matrix():
    return list({json.dumps(row['build'], sort_keys=True): row['build'] for config in PROJECTS.values() for row in rows(config) if row['family'] == 'linux'}.values())


def sources(tags):
    result = {}
    for repo, tag in tags.items():
        if not re.fullmatch(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', tag):
            raise ValueError(f'{repo}: select vMAJOR.MINOR.PATCH tags only')
        refs = run('git', 'ls-remote', f'https://github.com/SNodeC/{repo}.git',
                   f'refs/tags/{tag}', f'refs/tags/{tag}^{{}}').splitlines()
        if not refs:
            raise RuntimeError(f'{repo}: {tag} tag is missing')
        result[repo] = dict(line.split()[::-1] for line in refs)
    return result


def unchanged(bundle):
    # Captured bytes, not mutable upstream tags, define an in-flight release.
    for name, checksum in json.loads((bundle / 'checksums.json').read_text()).items():
        if Path(name).is_absolute() or '..' in Path(name).parts or digest(bundle / name) != checksum:
            raise RuntimeError('Captured source archive changed: ' + name)


def archive_source(repo, config, source_tag, archives):
    commit = config['_commit']
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / repo
        if not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise ValueError('Capture requires an exact source commit')
        run('git', 'init', str(source))
        run('git', '-C', str(source), 'remote', 'add', 'origin', f'https://github.com/SNodeC/{repo}.git')
        run('git', '-C', str(source), 'fetch', '--depth', '1', 'origin', commit)
        run('git', '-C', str(source), 'checkout', '--detach', 'FETCH_HEAD')
        run('git', '-C', str(source), 'submodule', 'update', '--init', '--recursive', '--depth', '1')
        if run('git', '-C', str(source), 'rev-parse', 'HEAD') != commit:
            raise RuntimeError('Source checkout does not match captured commit')
        if hashlib.sha256((source / 'ci/packages.json').read_bytes()).hexdigest() != config['_digest']:
            raise RuntimeError('Source definition differs from captured JSON')
        version_file = source / 'VERSION'
        # Older published releases used a literal project VERSION.
        version = version_file.read_text().strip() if version_file.exists() else re.search(
            r'\bVERSION\s+([0-9]+\.[0-9]+\.[0-9]+)', (source / 'CMakeLists.txt').read_text())[1]
        if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version) or source_tag != f'v{version}':
            raise RuntimeError(f'{repo}: release tag and VERSION disagree')
        name = f'{repo}-{version}'
        archive = f'{name}-{commit}.tar.gz'
        run('tar', '-czf', str(archives / archive), '--exclude=.git',
            f'--transform=s,^,{name}/,', '-C', str(source), '.')
    return version, {f'refs/tags/{source_tag}': commit}, archive


def prepare(published_root, bundle):
    from ci.publish.publication import published
    archives = bundle / 'archives'
    archives.mkdir(parents=True)
    changed = os.environ.get('RELEASE_PROJECT', '')
    tag = os.environ.get('RELEASE_TAG', '')
    if changed not in REPOSITORIES:
        raise ValueError('Unknown release project')
    state = json.loads((published_root / 'status.json').read_text())
    revisions = state['allocations'][os.environ['GITHUB_RUN_ID']]
    selected_projects = set().union(*(set(affected(changed, graph)) for graph in ROW_PROJECTS.values()))
    if set(revisions) != selected_projects:
        raise RuntimeError('Reserved revisions do not match the release project')
    context = dict(contract=3, projects=PROJECTS, tag=tag, requested_at=os.environ.get('RELEASE_REQUESTED_AT', ''), captured_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), recipe_ref=os.environ.get('RECIPE_REF', 'main'),
                   recipe_commit=run('git', '-C', str(ROOT), 'rev-parse', 'HEAD'),
                   destination='SNodeC/Packages', packages_commit=run('git', '-C', str(published_root), 'rev-parse', 'HEAD'),
                   release_project=changed, run_id=os.environ.get('GITHUB_RUN_ID', 'local'),
                   run_url=f'https://github.com/{os.environ.get("GITHUB_REPOSITORY", "SNodeC/DistributionPackages")}/actions/runs/{os.environ.get("GITHUB_RUN_ID", "local")}')
    profiles, captured = {}, {}
    target_rows = rows(PROJECTS[changed])
    for row in target_rows:
        baseline, directory = published(published_root, row)
        if (baseline and any(int(value) <= project_revision(baseline, repo) for repo, value in revisions.items())
                and baseline.get('context', {}).get('run_id') != context['run_id']):
            raise RuntimeError('Package revision must exceed the published revision; check the reserved project revisions')
        choices = {n: dependent_source(n, row, baseline, state.get('requests', {})) for n in REPOSITORIES if n != changed}
        projects = {changed: ROW_PROJECTS[row['id']][changed]} | {n: c for n, (c, _) in choices.items() if c is not None}
        errors = {n: reason for n, (_, reason) in choices.items() if reason}
        projects = isolate(projects, errors)
        selected = set(affected(changed, projects)) & revisions.keys()
        tags = {changed: tag}
        for repo in selected:
            if repo != changed and repo not in errors and supports(repo, row, projects) and (projects[repo]['_commit'] == source_commit(baseline.get('sources', {}).get(repo)) or projects[repo].get('_tag')):
                refs = baseline.get('sources', {}).get(repo, {})
                tags[repo] = projects[repo].get('_tag') or next(key.removeprefix('refs/tags/') for key in refs if not key.endswith('^{}'))
        tags = {repo: value for repo, value in tags.items() if supports(repo, row, projects)}
        required = {dependency for project in tags for dependency in dependencies(project, projects)} - tags.keys()
        for dependency in required:
            dependency_tag = baseline.get('context', {}).get('source_tags', {}).get(dependency)
            if dependency_tag:
                tags[dependency] = dependency_tag
        profile = dict(context={k: v for k, v in context.items() if k != 'projects'} | dict(source_tags=tags, versions={}), sources={}, archives={},
                       baseline=baseline, directory=directory, projects=projects, errors=errors)
        for repo, source_tag in tags.items():
            if repo not in revisions:
                profile['sources'][repo] = baseline['sources'][repo]
            else:
                key = (repo, projects[repo]['_commit'])
                try:
                    if key not in captured:
                        captured[key] = archive_source(repo, projects[repo], source_tag, archives)
                    version, refs, archive = captured[key]
                    profile['context']['versions'][repo] = version
                    profile['sources'][repo] = refs
                    profile['archives'][repo] = archive
                except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
                    if repo == changed:
                        raise
                    errors[repo] = 'Dependent capture unavailable: ' + str(error)
        profiles[row['id']] = profile
    context['projects'] = {n: c for profile in profiles.values() for n, c in profile['projects'].items() if n in profile['sources']}
    for name, data in [('profiles', profiles), ('sources', {target: profile['sources'] for target, profile in profiles.items()}), ('context', context),
                       ('targets', target_rows), ('revisions', revisions)]:
        (bundle / f'{name}.json').write_text(json.dumps(data, indent=2) + '\n')
    (bundle / 'checksums.json').write_text(json.dumps({str(path.relative_to(bundle)): digest(path)
        for path in [*archives.iterdir(), bundle / 'profiles.json', bundle / 'targets.json', bundle / 'revisions.json']}, indent=2) + '\n')
    unchanged(bundle)
    return None


def select(bundle, target, project, baseline=None):
    activate(bundle, target, baseline, project)
    profile = json.loads((bundle / 'profiles.json').read_text())[target]
    if project not in REPOSITORIES:
        raise ValueError('Unknown build project')
    if baseline is not None:
        profile['baseline'] = baseline
    previous = profile['baseline']
    profile['context']['build_project'] = project
    if os.environ.get('PUBLISHED_REF'):
        profile['context']['dependency_commit'] = os.environ['PUBLISHED_REF']
    # Record the actual retained counterpart, not the source planned for its next build.
    for values, old in [(profile['sources'], previous.get('sources', {})),
                        (profile['context']['source_tags'], previous.get('context', {}).get('source_tags', {})),
                        (profile['context']['versions'], previous.get('context', {}).get('versions', {}))]:
        own = values[project]
        values.clear()
        values.update(old)
        values[project] = own
    for key in ['context', 'sources']:
        (bundle / f'{key}.json').write_text(json.dumps(profile[key], indent=2) + '\n')
    (bundle / 'baseline.json').write_text(json.dumps(previous))
    archive = profile['archives'][project]
    shutil.copy2(bundle / 'archives' / archive, bundle / f'{project}-{profile["context"]["versions"][project]}.tar.gz')
    return profile


def project_file(name, project, projects=None):
    projects = PROJECTS if projects is None else projects
    filename = Path(name).name
    normalized = filename.replace(project + '-', projects[project]['package'] + '-', 1).replace(project + '_', projects[project]['package'] + '_', 1) if project in projects else filename
    return project in projects and filename.endswith(('.deb', '.rpm', '.ipk', '.apk', '.tar.zst')) and package_owner(normalized, projects) == project


def reuse(bundle, target, destination):
    profile = json.loads((bundle / 'profiles.json').read_text())[target]
    row = next(r for r in json.loads((bundle / 'targets.json').read_text()) if r['id'] == target)
    info = json.loads((bundle / 'baseline.json').read_text())
    owners = ownership(info)
    others = dependencies(json.loads((bundle / 'context.json').read_text())['build_project'])
    destination.mkdir(parents=True, exist_ok=True)
    for name, checksum in info.get('files', {}).items():
        filename = Path(name).name
        if any(project_file(filename, project, owners) for project in others):
            directory = f'{row["distribution"]}/pool/{row["suite"]}' if filename.endswith('.deb') else profile['directory']
            path = destination / filename
            ref = os.environ.get('PUBLISHED_REF') or profile['context']['packages_commit']
            fetch(f'https://raw.githubusercontent.com/SNodeC/Packages/{ref}/{directory}/{name}', path)
            if digest(path) != checksum:
                raise RuntimeError(f'Published dependency checksum mismatch: {name}')
    if row['family'] != 'openwrt':
        for project in others:
            names = [name for name in info.get('packages', []) if package_owner(name, owners) == project]
            if names:
                (destination / (owners[project]['package'] + '.packages')).write_text('\n'.join(names) + '\n')
    return None


def fetch(url, destination=None):
    """Retry transient transport failures, never validation or local I/O failures."""
    delays = (60, 300, 900)
    for attempt in range(len(delays) + 1):
        try:
            with tempfile.TemporaryDirectory(dir=destination.parent if destination is not None else None) as directory:
                path = Path(directory) / 'download'
                with urllib.request.urlopen(url, timeout=120) as response, path.open('wb') as output:
                    shutil.copyfileobj(response, output)
                    length = response.headers.get('Content-Length')
                    if length is not None and output.tell() < int(length):
                        raise urllib.error.ContentTooShortError('Incomplete download', None)
                if destination is None:
                    return path.read_bytes()
                os.replace(path, destination)
                return
        except (urllib.error.URLError, OSError, http.client.IncompleteRead) as error:
            if isinstance(error, urllib.error.HTTPError):
                retryable = error.code in (429, 502, 503, 504)
            else:
                reason = getattr(error, 'reason', error)
                retryable = (isinstance(error, urllib.error.ContentTooShortError)
                             or isinstance(reason, (ConnectionResetError, ConnectionAbortedError,
                                                    TimeoutError, http.client.IncompleteRead))
                             or isinstance(reason, socket.gaierror) and reason.errno == socket.EAI_AGAIN)
            if not retryable or attempt == len(delays):
                raise
            delay = delays[attempt]
            if isinstance(error, urllib.error.HTTPError) and error.code in (429, 503):
                header = (error.headers or {}).get('Retry-After', '').strip()
                try:
                    if header.isascii() and header.isdigit():
                        seconds = int(header)
                    else:
                        deadline = parsedate_to_datetime(header)
                        if deadline.tzinfo is None:
                            raise ValueError('Retry-After date lacks a timezone')
                        seconds = ceil(deadline.timestamp() - time.time())
                    delay = min(1800, max(0, seconds))
                except (ValueError, TypeError, OverflowError):
                    pass  # Missing or malformed Retry-After: retain bounded backoff.
            print(f'Transient download failure ({error}); retry {attempt + 1}/3 in {delay} seconds',
                  file=sys.stderr)
            time.sleep(delay)


def download_sdk(row, destination):
    base = f'https://downloads.openwrt.org/releases/{row["release"]}/targets/{row["target"]}/'
    profile = json.loads(fetch(base + 'profiles.json'))
    if profile['arch_packages'] != row['arch']:
        raise RuntimeError(f'Wrong SDK architecture: {profile["arch_packages"]}')
    entries = [line.split() for line in fetch(base + 'sha256sums').decode().splitlines()
               if 'openwrt-sdk-' in line]
    if len(entries) != 1:
        raise RuntimeError(f'Expected one SDK in {base}')
    checksum, filename = entries[0]
    filename = filename.lstrip('*')
    archive = destination.parent / filename
    fetch(base + filename, archive)
    if digest(archive) != checksum:
        raise RuntimeError('SDK checksum mismatch')
    destination.mkdir()
    run('tar', '-xf', str(archive), '--strip-components=1', '-C', str(destination))
    archive.unlink()
    (destination / 'ci-sdk.json').write_text(json.dumps(dict(row, sdk_url=base + filename, sha256=checksum)))


def stage(sdk, bundle, output):
    """Stage project packages and unsigned indexes; official feeds supply other dependencies."""
    info = json.loads((sdk / 'ci-sdk.json').read_text())
    feed = sdk / 'bin/packages' / info['arch'] / 'snodec'
    extension = '.ipk' if info['series'] == '24.10' else '.apk'
    packages = sorted(feed.glob('*' + extension))
    destination = output / 'openwrt' / info['series'] / info['arch']
    destination.mkdir(parents=True)
    indexes = ['Packages', 'Packages.gz'] if extension == '.ipk' else ['packages.adb']
    development = list(sdk.glob('*-openwrt-build-deps-*.tar.zst'))
    for path in packages + [feed / name for name in indexes] + development:
        shutil.copy2(path, destination / path.name)
    files = {p.name: digest(p)
             for p in destination.iterdir()}
    info.update(sources=json.loads((bundle / 'sources.json').read_text()), files=files,
                revision=os.environ['PACKAGE_RELEASE'],
                context=json.loads((bundle / 'context.json').read_text()))
    info['versions'] = {repo: package_version(dict(distribution="openwrt"), version, info["revision"])
                        for repo, version in info['context']['versions'].items()}
    baseline = json.loads((bundle / 'baseline.json').read_text())
    info['versions'].update({project: version for project, version in baseline.get('versions', {}).items()
                             if project != info['context']['build_project']})
    (destination / 'build.json').write_text(json.dumps(info, indent=2) + '\n')
    return None


def sdk_dependency(sdk, bundle, archives):
    """Import registered prerequisite development exports, rejecting conflicting files."""
    info = json.loads((sdk / 'ci-sdk.json').read_text())
    baseline = json.loads((bundle / 'baseline.json').read_text())
    owners = ownership(baseline)
    for dependency in dependencies(json.loads((bundle / 'context.json').read_text())['build_project']):
        prefix = owners[dependency]['package'] + '-openwrt-build-deps-'
        names = [name for name in baseline.get('files', {}) if name.startswith(prefix) and name.endswith('.tar.zst')]
        if len(names) != 1 or any(baseline[key] != info[key] for key in ('release', 'target', 'arch', 'sha256')):
            raise RuntimeError('Missing or incompatible published development export: ' + dependency)
        archive = archives / names[0]
        if digest(archive) != baseline['files'][names[0]]:
            raise RuntimeError('Development export checksum mismatch')
        with tempfile.TemporaryDirectory(dir=sdk) as tmp:
            root = Path(tmp)
            run('tar', '--zstd', '-xf', str(archive), '-C', tmp)
            origin = json.loads((root / 'sdk-development.json').read_text())
            if origin['sdk'] != info:
                raise RuntimeError('Development export SDK mismatch')
            for path in sorted(root.rglob('*')):
                if path.is_file() or path.is_symlink():
                    relative = path.relative_to(root)
                    if relative.as_posix() != 'sdk-development.json':
                        if path.suffix in {'.cmake', '.pc', '.la'} and not path.is_symlink():
                            path.write_text(path.read_text().replace(origin['path'] + '/', str(sdk) + '/'))
                        destination = sdk / relative
                        if destination.exists() and not destination.is_dir() and (path.is_symlink() != destination.is_symlink() or
                                (os.readlink(path) != os.readlink(destination) if path.is_symlink() else digest(path) != digest(destination))):
                            raise RuntimeError('Conflicting development exports: ' + str(relative))
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        if not destination.exists():
                            shutil.copy2(path, destination, follow_symlinks=False)
        shutil.copy2(archive, sdk / names[0])
    return None


def sdk_export(sdk, bundle, *files):
    """The project recipe declares its installed development files, never build trees."""
    context = json.loads((bundle / 'context.json').read_text())
    project = context['build_project']
    archive = sdk / f'{PROJECTS[project]["package"]}-openwrt-build-deps-{context["versions"][project]}-r{os.environ["PACKAGE_RELEASE"]}.tar.zst'
    if any(Path(name).is_absolute() or '..' in Path(name).parts for name in files):
        raise ValueError('Development export paths must stay inside the SDK')
    with tempfile.TemporaryDirectory(dir=sdk) as tmp:
        (Path(tmp) / 'sdk-development.json').write_text(json.dumps(dict(sdk=json.loads((sdk / 'ci-sdk.json').read_text()), path=str(sdk))))
        run('tar', '--zstd', '-cf', str(archive), '-C', tmp, 'sdk-development.json', '-C', str(sdk), *files)
    return None


def package_version(row, version, revision):
    """One package-version policy for native CPack, feed metadata and status pages."""
    distribution = row['distribution']
    if distribution in {'debian', 'ubuntu', 'raspberrypios'}:
        return f"{version}-{revision}~{row['suite']}"
    if distribution in {'rocky', 'fedora'}:
        return f"{version}-{revision}.{'el' if distribution == 'rocky' else 'fc'}{row['suite']}"
    if distribution == 'openwrt':
        return f'{version}-r{revision}'
    raise ValueError('Unknown package distribution')


def project_revision(info, project, projects=None):
    versions = info.get('versions', {})
    version = versions.get(project, versions.get((PROJECTS if projects is None else projects).get(project, {}).get('package')))
    if version is None:
        result = int(info['revision']) if info.get('context', {}).get('build_project') == project else 0
    else:
        match = re.search(r'-r?(\d+)(?:[.~]|$)', version)
        if not match:
            raise RuntimeError(f'Invalid package revision: {version}')
        result = int(match[1])
    return result


def dependency_identity(info, project, projects=None):
    projects = ownership(info)
    return dict(source=info.get('sources', {}).get(project), revision=project_revision(info, project, projects),
                files={name: checksum for name, checksum in info.get('files', {}).items() if project_file(name, project, projects)})


def binding(info, required, projects=None):
    return hashlib.sha256(json.dumps({p: dependency_identity(info, p, projects) for p in required}, sort_keys=True).encode()).hexdigest()


def publication_needed(previous, incoming):
    needed = True
    if not isinstance(previous, Path) or previous.exists():
        previous = json.loads(previous.read_text()) if isinstance(previous, Path) else previous
        old = project_revision(previous, incoming['context']['build_project'], ownership(previous) if previous.get('sources') else None)
        new = int(incoming['revision'])
        if old > new:
            raise RuntimeError('Superseded publication: a newer project revision is already published')
        if old == new:
            if not (all(previous.get(key) == incoming.get(key) for key in ('sources', 'context'))
                    and previous.get('unsigned_files', previous.get('files')) == incoming.get('files')):
                raise RuntimeError('Different package content under the same publication revision')
            needed = False
    return needed


def publish(incoming, checkout, bundle):
    unchanged(bundle)
    expected = {(r['series'], r['arch']) for r in matrix()}
    found = {(p.parent.parent.name, p.parent.name) for p in incoming.glob('openwrt/*/*/build.json')}
    if not found or not found <= expected:
        raise RuntimeError(f'Unexpected OpenWrt targets: {found - expected}')
    for series, arch in sorted(found):
        directory = incoming / 'openwrt' / series / arch
        metadata = json.loads((directory / 'build.json').read_text())
        if metadata['sources'] != json.loads((bundle / 'sources.json').read_text()):
            raise RuntimeError('Mixed source generations')
        for name, checksum in metadata['files'].items():
            if Path(name).name != name or digest(directory / name) != checksum:
                raise RuntimeError(f'Package/index checksum mismatch: {name}')
        destination = checkout / 'openwrt' / series / arch
        if not publication_needed(destination / 'build.json', metadata):
            continue
        from ci.publish.openwrt import sign
        sign(directory, metadata)
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(directory, destination, dirs_exist_ok=True)
    unchanged(bundle)


if __name__ == '__main__':
    command, *args = sys.argv[1:]
    if command == 'package-version':
        print(package_version(dict(distribution=args[0], suite=args[1]), args[2], args[3]))
    elif command == 'matrix':
        print(json.dumps({'include': matrix()}))
    elif command == 'linux-matrix':
        print(json.dumps({'include': linux_matrix()}))
    elif command == 'sdk':
        download_sdk(json.loads(args[0]), Path(args[1]).resolve())
    elif command == 'select':
        checkpoint = Path(args[3])
        baseline = json.loads(next(checkpoint.rglob('build.json')).read_text()) if checkpoint.exists() else None
        select(Path(args[0]).resolve(), args[1], args[2], baseline)
    elif command == 'reuse':
        reuse(Path(args[0]).resolve(), args[1], Path(args[2]).resolve())
    else:
        {'prepare': prepare, 'check': unchanged, 'stage': stage, 'publish': publish,
         'sdk-dependency': sdk_dependency, 'sdk-export': sdk_export}[command](
            *(Path(arg).resolve() for arg in args))
