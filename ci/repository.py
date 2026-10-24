"""Capture an immutable release generation from exact source commits."""
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from email.parser import Parser
import io
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
import tarfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
TAG = r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'


def version(tag):
    if not isinstance(tag, str) or not re.fullmatch(TAG, tag):
        raise ValueError('Expected vMAJOR.MINOR.PATCH without leading zeros: ' + str(tag))
    return tuple(map(int, tag[1:].split('.')))


def source_tag(info, project):
    refs = info.get('sources', {}).get(project, {})
    return next((k.removeprefix('refs/tags/') for k in refs if not k.endswith('^{}')),
                info.get('context', {}).get('source_tags', {}).get(project))


def release_view(info, project, tag=None):
    releases = info.get('releases', {}).get(project, {})
    return (releases.get(tag or max(releases, key=version, default=None), {}) if 'releases' in info else info)


def generation_tag(generation, project, target=None):
    tags = [source_tag(dict(sources=values), project) for key, values in generation.get('sources', {}).items()
            if (target is None or target == key) and project in values]
    context = generation.get('context', {})
    fallback = context.get('tag') if context.get('release_project') == project else None
    return max((t for t in tags if t), key=version, default=fallback)

def load_master(path):
    value = json.loads(path.read_text())
    defaults = dict(capacity='plan', headroom=2, rebuild_overlap=True)
    if not isinstance(value, dict) or set(value) - {'repositories', 'settings', 'feed'}:
        raise ValueError('Master configuration contains repositories and optional settings only')
    names = value.get('repositories')
    if not isinstance(names, list) or not names or any(not isinstance(n, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,100}', n) or n in {'.', '..'} for n in names) or len({n.casefold() for n in names}) != len(names):
        raise ValueError('repositories must be unique repository names')
    settings = value.get('settings', {})
    if isinstance(settings, dict) and 'dependent_version' in settings:
        raise ValueError('Cascades always select the highest semantic version; remove dependent_version')
    if not isinstance(settings, dict) or set(settings) - defaults.keys():
        raise ValueError('Unknown coordinator setting')
    defaults.update(settings)
    if (defaults['capacity'] != 'plan' and (type(defaults['capacity']) is not int or defaults['capacity'] < 3)
            or type(defaults['headroom']) is not int or defaults['headroom'] < 1
            or type(defaults['rebuild_overlap']) is not bool
            or type(defaults['capacity']) is int and defaults['headroom'] >= defaults['capacity']):
        raise ValueError('Invalid capacity, headroom or rebuild_overlap setting')
    if not isinstance(value.get('feed', {}), dict):
        raise ValueError('feed must be an object with repository and branch')
    feed = dict(repository='Packages', branch='main') | value.get('feed', {})
    if (set(feed) != {'repository', 'branch'} or any(not isinstance(v, str) for v in feed.values()) or not re.fullmatch(r'[A-Za-z0-9._-]+', feed['repository'])
            or feed['repository'] in {'.', '..'} or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_/-]*', feed['branch'])
            or '//' in feed['branch'] or feed['branch'].endswith('/')):
        raise ValueError('feed needs a safe repository name and branch')
    return dict(repositories=names, settings=defaults, feed=feed)


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
    return {name: projects[name] for name in order if name in projects}


def load_projects(path):
    return validate_projects(json.loads(path.read_text())['projects']) if path.exists() else {}


def requested_projects(requests):
    return {project: values[max(values, key=version)]['definition'] for project, values in requests.items() if values}


def bind_projects(projects, baseline, project):
    projects = dict(projects)
    pending, visited = list(projects[project]['depends_on']), set()
    while pending:
        dependency = pending.pop()
        if dependency not in visited:
            visited.add(dependency)
            ref = source_commit(baseline.get('sources', {}).get(dependency))
            if ref is not None and projects.get(dependency, {}).get('_commit') != ref:
                supplied = json.loads(os.environ.get('PACKAGE_REQUEST', '{}')).get('definitions', {})
                if os.environ.get('GITHUB_REPOSITORY') not in (None, '', COORDINATOR):
                    if supplied.get(dependency, {}).get('_commit') != ref:
                        raise ValueError(f'Pinned definition unavailable for {dependency}@{ref} in coordinator request')
                    projects[dependency] = supplied[dependency]
                else:
                    projects[dependency] = definition(dependency, ref)
            pending.extend(projects.get(dependency, {}).get('depends_on', []))
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
    value = api(f'repos/{OWNER}/{project}/contents/{path}?ref={ref}')
    if value.get('encoding') == 'none':
        value = api(f'repos/{OWNER}/{project}/git/blobs/{value["sha"]}')
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
                  if not source or source == COORDINATOR else supplied.get(project, {}))
        if source.casefold() == (OWNER + '/' + project).casefold() and PROJECTS.get(project, {}).get('_commit') == commit:
            config = PROJECTS[project]
        if config.get('_commit') != commit or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', config.get('package', '')):
            raise ValueError(f'Pinned ownership unavailable for {project}@{commit}; supply its matching package namespace')
        facts[project] = dict(_commit=commit, package=config['package'])
    return facts


def work_index(state):
    work, captures = {}, {}
    for capture, generation in state['runs'].items():
        for target, sources in generation['sources'].items():
            for project, revision in generation['revisions'].items():
                if project in sources:
                    key = target, project, generation_tag(generation, project, target)
                    previous = work.get(key, (0, None, 0))
                    node = generation.get('nodes', {}).get(target + '/' + project, {})
                    dependent = node.get('cause', generation['context'].get('cause')) == 'dependent'
                    expected = max(previous[2], int(revision) if dependent else 0)
                    work[key] = max(previous[:2], (int(revision), capture), key=lambda item: item[0]) + (expected,)
        captures.update({(capture, key): node for key, node in generation.get('nodes', {}).items()
                         if key.rsplit('/', 1)[1] not in generation['revisions']
                         and generation['context'].get('cascade', capture) == capture})
    return work, captures


def cascade_blockers(info, required, state, target, index):
    from ci.publish.publication import TERMINAL
    work, captures = index
    result = {}
    for project in required:
        own = release_view(info, project)
        receipt = own.get('publications', {}).get(project, {})
        node = state['runs'].get(receipt.get('capture'), {}).get('nodes', {}).get(target + '/' + project, {})
        if (not info.get('sources', {}).get(project) or node.get('dependencies') is not None
                and node['dependencies'] != binding(info, node.get('requires', []))):
            result[project] = ('pending', 'Awaiting a current prerequisite publication: ' + project)
        published = version(source_tag(own, project) or 'v0.0.0'), project_revision(own, project)
        expected = max(((version(tag), revision, capture) for (row, name, tag), (_, capture, revision) in work.items()
                        if row == target and name == project and revision), default=((), 0, None))
        if expected[:2] > published:
            selected = state['runs'][expected[2]].get('nodes', {}).get(target + '/' + project, {})
            result[project] = (selected.get('status', 'pending'), selected.get('reason', 'Awaiting selected arm: ' + project))
        if any(key == target + '/' + project and node['status'] not in TERMINAL for (_, key), node in captures.items()):
            result[project] = ('pending', 'Awaiting prerequisite capture: ' + project)
    return result


def dependent_source(name, requests):
    if not requests.get(name):
        raise ValueError('Cascade cannot select an inactive repository: ' + name)
    refs = dict(line.split()[::-1] for line in run(
        'git', 'ls-remote', '--tags', f'https://github.com/{OWNER}/{name}.git', 'refs/tags/v*').splitlines())
    tags = [r.removeprefix('refs/tags/') for r in refs if re.fullmatch('refs/tags/' + TAG, r)]
    if not tags:
        raise ValueError(name + ': no semantic version tag exists')
    tag = max(tags, key=version)
    commit = refs.get('refs/tags/' + tag + '^{}', refs['refs/tags/' + tag])
    result = dict(definition(name, commit), _tag=tag)
    validate_project(name, result)
    return result


def configure(root, project, commit, claimed):
    current = definition(project, commit)
    if {k: v for k, v in current.items() if not k.startswith('_')} != claimed:
        raise ValueError('Notification matrix does not match its source commit')
    requests = json.loads((root / 'status.json').read_text()).get('requests', {})
    selected = requested_projects({p: values for p, values in requests.items() if p in REPOSITORIES})
    selected = validate_projects(selected | {project: current})
    PROJECTS.clear()
    PROJECTS.update(selected)
    ROW_PROJECTS.clear()
    ROW_PROJECTS.update({r['id']: selected for r in rows(current)})
    DEFINITIONS.write_text(json.dumps(dict(projects=selected, targets=ROW_PROJECTS)))
    return None


def source_commit(value):
    result = (next((v for k, v in value.items() if k.endswith('^{}')), next(iter(value.values())))
              if isinstance(value, dict) and value else None)
    if result is not None and not re.fullmatch(r'[0-9a-f]{40}', result):
        raise ValueError('Expected an exact source commit')
    return result


CONFIG = load_master(Path(os.environ.get('CI_MASTER', ROOT / 'ci/projects.json')))
COORDINATOR = os.environ.get('PACKAGE_COORDINATOR') or re.sub(
    r'^.*github.com[:/]|\.git$', '', subprocess.check_output(['git', '-C', str(ROOT), 'remote', 'get-url', 'origin'], text=True).strip())
OWNER, COORDINATOR_NAME = COORDINATOR.split('/')
FEED, FEED_BRANCH = OWNER + '/' + CONFIG['feed']['repository'], CONFIG['feed']['branch']
REPOSITORIES = tuple(CONFIG["repositories"])
DEFINITIONS = Path(os.environ.get("CI_DEFINITIONS", ROOT / "ci/definitions.json"))
PROJECTS = load_projects(DEFINITIONS)
ROW_PROJECTS = json.loads(DEFINITIONS.read_text()).get("targets") or {r['id']: PROJECTS for c in PROJECTS.values() for r in rows(c)} if DEFINITIONS.exists() else {}

def missing_prerequisites(project, info, revisions, projects):
    return [dependency for dependency in dependencies(project, projects) if not info.get('sources', {}).get(dependency) and dependency not in revisions]


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
    return tuple(name for name in projects if name in selected) + tuple(sorted(selected - projects.keys()))


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
    return subprocess.check_output(args, text=True, **(dict(timeout=120) if args[0] in {'gh', 'git'} else {}), **kwargs).strip()


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


def package_metadata(path):
    """Read controls from package bytes; the publisher applies the pinned policy."""
    control, fields = '', {}
    if path.suffix == '.deb':
        control = run('dpkg-deb', '-f', str(path))
    elif path.suffix == '.rpm':
        name, release, arch, epoch = run('rpm', '-qp', '--qf', '%{NAME}\n%{VERSION}-%{RELEASE}\n%{ARCH}\n%{EPOCHNUM}', str(path)).splitlines()
        fields = dict(name=name, version=(epoch + ':' if epoch not in {'0', '(none)'} else '') + release, arch=arch)
    elif path.suffix == '.ipk':
        with tarfile.open(path, 'r:gz') as outer:
            members = [m for m in outer if m.name.removeprefix('./') == 'control.tar.gz' and m.isfile()]
            if len(members) != 1:
                raise ValueError('IPK needs exactly one control archive: ' + path.name)
            with tarfile.open(fileobj=io.BytesIO(outer.extractfile(members[0]).read()), mode='r:gz') as inner:
                controls = [m for m in inner if m.name.removeprefix('./') == 'control' and m.isfile()]
                if len(controls) != 1:
                    raise ValueError('IPK needs exactly one control file: ' + path.name)
                control = inner.extractfile(controls[0]).read().decode()
    elif path.suffix == '.apk':
        fields = json.loads(run('apk', 'adbdump', '--format', 'json', str(path)))['info']
    else:
        raise ValueError('Unsupported package metadata: ' + path.name)
    if control:
        parsed = Parser().parsestr(control)
        if (parsed.defects or parsed.is_multipart() or parsed.get_payload().strip()
                or any(len(parsed.get_all(k, [])) != 1 for k in ['Package', 'Version', 'Architecture'])):
            raise ValueError('Package needs one control paragraph with unique name, version and architecture: ' + path.name)
        if path.suffix == '.ipk' and any(k in parsed for k in ['Filename', 'Size', 'SHA256sum']):
            raise ValueError('IPK control must not supply generated index fields: ' + path.name)
        fields = dict(zip(['name', 'version', 'arch'], (parsed[k] for k in ['Package', 'Version', 'Architecture'])), control=control)
    if any(not isinstance(fields.get(k), str) or not fields[k] for k in ['name', 'version', 'arch']):
        raise ValueError('Incomplete package metadata: ' + path.name)
    return fields


def validate_package(owners, versions, filename, fields, row):
    owner = package_owner(fields['name'], owners)
    if (re.search(r'[\x00-\x1f\x7f]', filename + fields['name'])
            or owner not in versions or not project_file(filename, owner, owners)):
        raise ValueError('Package name and filename disagree with pinned ownership: ' + ascii(fields['name'])[1:-1])
    if fields['version'] != versions[owner]:
        raise ValueError('Package version disagrees with pinned release: ' + fields['name'])
    if row.get('arch') and fields['arch'] not in {row['arch'], 'noarch' if filename.endswith('.rpm') else 'all'}:
        raise ValueError('Package architecture disagrees with target: ' + fields['name'])
    return owner


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
        run('git', '-C', str(source), 'remote', 'add', 'origin', f'https://github.com/{OWNER}/{repo}.git')
        run('git', '-C', str(source), 'fetch', '--depth', '1', 'origin', commit)
        run('git', '-C', str(source), 'checkout', '--detach', 'FETCH_HEAD')
        run('git', '-C', str(source), 'submodule', 'update', '--init', '--recursive', '--depth', '1')
        if run('git', '-C', str(source), 'rev-parse', 'HEAD') != commit:
            raise RuntimeError('Source checkout does not match captured commit')
        if hashlib.sha256((source / 'ci/packages.json').read_bytes()).hexdigest() != config['_digest']:
            raise RuntimeError('Source definition differs from captured JSON')
        version_file = source / 'VERSION'
        release_version = version_file.read_text().strip()
        version('v' + release_version)
        if source_tag != f'v{release_version}':
            raise RuntimeError(f'{repo}: release tag and VERSION disagree')
        name = f'{repo}-{release_version}'
        archive = f'{name}-{commit}.tar.gz'
        run('tar', '-czf', str(archives / archive), '--exclude=.git',
            f'--transform=s,^,{name}/,', '-C', str(source), '.')
    return release_version, {f'refs/tags/{source_tag}': commit}, archive


def recipe_commit():
    return run('git', '-C', str(ROOT), 'rev-parse', 'HEAD')


def capture_inputs(root, row, project, tag, commit, recipe):
    from ci.publish.publication import published
    info, directory = published(root, row)
    required = dependencies(project, ROW_PROJECTS[row['id']])
    sources = {p: info['sources'][p] for p in required if p in info.get('sources', {})}
    inputs = dict(tag=tag, commit=commit, recipe=recipe, dependencies={p: release_identity(info, p) for p in required})
    return info, directory, sources, hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def prepare(published_root, bundle):
    archives = bundle / 'archives'
    archives.mkdir(parents=True)
    changed = os.environ.get('RELEASE_PROJECT', '')
    tag = os.environ.get('RELEASE_TAG', '')
    if changed not in REPOSITORIES:
        raise ValueError('Unknown release project')
    state = json.loads((published_root / 'status.json').read_text())
    revisions = state['allocations'][os.environ['GITHUB_RUN_ID']]
    selected_projects = {changed}
    if set(revisions) != selected_projects:
        raise RuntimeError('Reserved revisions do not match the release project')
    context = dict(contract=3, projects=PROJECTS, tag=tag, requested_at=os.environ.get('RELEASE_REQUESTED_AT', ''),
                   captured_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                   recipe_commit=recipe_commit(),
                   destination=FEED, packages_commit=run('git', '-C', str(published_root), 'rev-parse', 'HEAD'),
                   release_project=changed, run_id=os.environ.get('GITHUB_RUN_ID', 'local'),
                   run_url=f'https://github.com/{COORDINATOR}/actions/runs/{os.environ.get("GITHUB_RUN_ID", "local")}')
    release_version, refs, archive = archive_source(changed, PROJECTS[changed], tag, archives)
    profiles = {}
    parent = json.loads(os.environ.get('RELEASE_PARENT') or '{}')
    context.update(cascade=parent.get('root', context['run_id']), cause=os.environ.get('RELEASE_CAUSE', 'release'))
    target_rows = [r for r in rows(PROJECTS[changed]) if not parent or r['id'] == parent['target']]
    if not target_rows:
        raise ValueError('Highest version does not support requested cascade target')
    for row in target_rows:
        baseline, directory, profile_sources, _ = capture_inputs(
            published_root, row, changed, tag, PROJECTS[changed]['_commit'], context['recipe_commit'])
        projects = dict(ROW_PROJECTS[row['id']])
        profiles[row['id']] = dict(context={k: v for k, v in context.items() if k != 'projects'} |
            dict(source_tags={changed: tag}, versions={changed: release_version}), sources=profile_sources | {changed: refs},
            archives={changed: archive}, baseline=baseline, directory=directory, projects=projects, errors={})
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
    files = {name: checksum for p in others for name, checksum in dependency_identity(info, p)['files'].items()}
    for name, checksum in files.items():
        filename = Path(name).name
        if any(project_file(filename, project, owners) for project in others):
            directory = f'{row["distribution"]}/pool/{row["suite"]}' if filename.endswith('.deb') else profile['directory']
            path = destination / filename
            ref = os.environ.get('PUBLISHED_REF') or profile['context']['packages_commit']
            fetch(f'https://raw.githubusercontent.com/{FEED}/{ref}/{directory}/{name}', path)
            if digest(path) != checksum:
                raise RuntimeError(f'Published dependency checksum mismatch: {name}')
    if row['family'] != 'openwrt':
        for project in others:
            names = [name for name in release_view(info, project).get('packages', []) if package_owner(name, owners) == project]
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
    feed = sdk / 'bin/packages' / info['arch'] / 'package_ci'
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
    owners = ownership(info)
    names = set()
    for path in packages:
        fields = package_metadata(path)
        validate_package(owners, info['versions'], path.name, fields, info)
        names.add(fields['name'])
    info['packages'] = sorted(names)
    (destination / 'build.json').write_text(json.dumps(info, indent=2) + '\n')
    return None


def sdk_dependency(sdk, bundle, archives):
    """Import registered prerequisite development exports, rejecting conflicting files."""
    info = json.loads((sdk / 'ci-sdk.json').read_text())
    baseline = json.loads((bundle / 'baseline.json').read_text())
    owners = ownership(baseline)
    for dependency in dependencies(json.loads((bundle / 'context.json').read_text())['build_project']):
        prefix = owners[dependency]['package'] + '-openwrt-build-deps-'
        names = [name for name in dependency_identity(baseline, dependency)['files']
                 if name.startswith(prefix) and name.endswith('.tar.zst')]
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


def project_revision(info, project):
    selected = release_view(info, project)
    value = selected.get('versions', {}).get(project)
    # Feed entries record revisions; unsigned artifacts also carry reused package versions.
    if 'releases' in info or selected.get('context', {}).get('build_project') == project:
        result = int(selected.get('revision', 0))
    elif value is not None:
        match = re.search(r'-r?(\d+)(?:[.~]|$)', value)
        if not match:
            raise RuntimeError(f'Invalid package revision: {value}')
        result = int(match[1])
    else:
        result = 0
    return result


def release_identity(info, project):
    info = release_view(info, project)
    return dict(source=info.get('sources', {}).get(project), revision=project_revision(info, project))


def dependency_identity(info, project):
    info = release_view(info, project)
    projects = ownership(info)
    return release_identity(info, project) | dict(
        files={name: checksum for name, checksum in info.get('files', {}).items() if project_file(name, project, projects)})


def binding(info, required):
    return hashlib.sha256(json.dumps({p: dependency_identity(info, p) for p in required}, sort_keys=True).encode()).hexdigest()


def publication_needed(previous, incoming):
    needed = True
    if not isinstance(previous, Path) or previous.exists():
        previous = json.loads(previous.read_text()) if isinstance(previous, Path) else previous
        project = incoming['context']['build_project']
        tag = source_tag(incoming, project)
        previous, incoming = release_view(previous, project, tag), release_view(incoming, project, tag)
        old = project_revision(previous, project)
        new = int(incoming['revision'])
        if old > new:
            raise RuntimeError('Superseded publication: a newer project revision is already published')
        if old == new:
            if not (all(previous.get(key) == incoming.get(key) for key in ('sources', 'context'))
                    and previous.get('unsigned_files') == incoming.get('files')):
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
    if command == 'deployment':
        print('\n'.join(f'{k}={v}' for k, v in dict(owner=OWNER, coordinator=COORDINATOR,
            name=COORDINATOR_NAME, feed=FEED, feed_name=CONFIG['feed']['repository'], branch=FEED_BRANCH,
            repositories=','.join([*REPOSITORIES, COORDINATOR_NAME]),
            readers=','.join(dict.fromkeys([*REPOSITORIES, COORDINATOR_NAME, CONFIG['feed']['repository']]))).items()))
    elif command == 'package-version':
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
            *(Path(arg).resolve() if command != 'sdk-export' or index < 2 else Path(arg) for index, arg in enumerate(args)))
