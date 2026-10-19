"""Capture an immutable release generation from exact source commits."""
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import http.client
from graphlib import TopologicalSorter
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

def load_projects(path):
    projects = json.loads(path.read_text())
    if not isinstance(projects, dict) or not projects:
        raise ValueError('Project registry must be a nonempty object')
    packages = set()
    for name, config in projects.items():
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', name)
                or not isinstance(config, dict) or set(config) != {'title', 'package', 'depends_on', 'families'}
                or not isinstance(config['title'], str) or not config['title']
                or not isinstance(config['package'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', config['package'])
                or config['package'] in packages):
            raise ValueError('Invalid project metadata: ' + name)
        packages.add(config['package'])
        for key, allowed in [('depends_on', projects), ('families', ('openwrt', 'linux', 'raspberrypi'))]:
            values = config[key]
            if not isinstance(values, list) or any(not isinstance(value, str) or value not in allowed for value in values) or len(values) != len(set(values)):
                raise ValueError('Invalid ' + key + ': ' + name)
        if not config['families']:
            raise ValueError('A project needs supported families: ' + name)
    order = tuple(TopologicalSorter({name: config['depends_on'] for name, config in projects.items()}).static_order())
    for name in order:
        for dependency in projects[name]['depends_on']:
            if not set(projects[name]['families']) <= set(projects[dependency]['families']):
                raise ValueError('Dependency does not support every project family: ' + name)
    return {name: projects[name] for name in order}


PROJECTS = load_projects(ROOT / 'ci/projects.json')
REPOSITORIES = tuple(PROJECTS)


def affected(project):
    selected = {project}
    for name, config in PROJECTS.items():
        if selected.intersection(config['depends_on']):
            selected.add(name)
    return tuple(name for name in PROJECTS if name in selected)


def dependencies(project, projects=None):
    projects = PROJECTS if projects is None else projects
    selected = set(projects[project]['depends_on'])
    for name in reversed(projects):
        if name in selected:
            selected.update(projects[name]['depends_on'])
    return tuple(name for name in projects if name in selected)


def supports(project, row):
    return row['family'] in PROJECTS[project]['families']


def package_owner(name):
    matches = [repo for repo, config in PROJECTS.items()
               if name == config['package'] or name.startswith((config['package'] + '-', config['package'] + '_'))]
    result = max(matches, key=lambda repo: len(PROJECTS[repo]['package']), default=None)
    return result


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


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
    config = json.loads((ROOT / 'ci/targets/openwrt.json').read_text())
    return [dict(release=release, series=release.rsplit('.', 1)[0], target=target,
                 arch='riscv64_riscv64' if arch == 'riscv64_generic' and release.startswith('24.') else arch)
            for release in config['releases'] for arch, target in config['targets'].items()]


def linux_matrix():
    platforms = {'amd64': 'linux/amd64', 'x86_64': 'linux/amd64',
                 'arm64': 'linux/arm64', 'aarch64': 'linux/arm64',
                 'armhf': 'linux/arm/v7', 'riscv64': 'linux/riscv64'}
    return [dict(distribution=row['distribution'], suite=row['suite'], image=row['image'],
                 arch=arch, platform=platforms[arch],
                 runner='ubuntu-24.04-arm' if arch in {'arm64', 'aarch64', 'armhf'} else 'ubuntu-24.04')
            for row in json.loads((ROOT / 'ci/targets/linux.json').read_text()) for arch in row['architectures']]


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


def prepare(published_root, bundle):
    from ci.publish.publication import targets, published
    bundle.mkdir(parents=True)
    archives = bundle / 'archives'
    archives.mkdir()
    changed = os.environ.get('RELEASE_PROJECT', '')
    tag = os.environ.get('RELEASE_TAG', '')
    if changed not in REPOSITORIES:
        raise ValueError('Unknown release project')
    revisions = json.loads((published_root / 'status.json').read_text())['allocations'][os.environ['GITHUB_RUN_ID']]
    if set(revisions) != set(affected(changed)):
        raise RuntimeError('Reserved revisions do not match the release project')
    context = dict(contract=2, projects=PROJECTS, captured_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), recipe_ref=os.environ.get('RECIPE_REF', 'main'),
                   recipe_commit=run('git', '-C', str(ROOT), 'rev-parse', 'HEAD'),
                   destination='SNodeC/Packages', packages_commit=run('git', '-C', str(published_root), 'rev-parse', 'HEAD'),
                   release_project=changed, run_id=os.environ.get('GITHUB_RUN_ID', 'local'),
                   run_url=f'https://github.com/{os.environ.get("GITHUB_REPOSITORY", "SNodeC/DistributionPackages")}/actions/runs/{os.environ.get("GITHUB_RUN_ID", "local")}')
    release_tags = {changed: tag}
    for dependent in affected(changed):
        if dependent != changed:
            refs = run('git', 'ls-remote', '--tags', f'https://github.com/SNodeC/{dependent}.git', 'refs/tags/v*')
            candidates = [line.split()[1].removeprefix('refs/tags/') for line in refs.splitlines()
                          if re.fullmatch(r'refs/tags/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', line.split()[1])]
            release_tags[dependent] = max(candidates, key=lambda value: tuple(map(int, value[1:].split('.'))), default=None)
    for project in release_tags:
        if any(release_tags.get(dependency, True) is None for dependency in dependencies(project)):
            release_tags[project] = None
    profiles, captured, observed = {}, {}, {project: None for project, value in release_tags.items() if value is None}
    rows = [row for row in targets() if supports(changed, row)]
    for row in rows:
        baseline, directory = published(published_root, row)
        if (baseline and any(int(value) <= project_revision(baseline, repo) for repo, value in revisions.items())
                and baseline.get('context', {}).get('run_id') != context['run_id']):
            raise RuntimeError('Package revision must exceed the published revision; check the reserved project revisions')
        tags = {repo: value for repo, value in release_tags.items() if value is not None and supports(repo, row)}
        required = {dependency for project in tags for dependency in dependencies(project)} - tags.keys()
        for dependency in required:
            dependency_tag = baseline.get('context', {}).get('source_tags', {}).get(dependency)
            if not dependency_tag:
                raise RuntimeError(f'{row["id"]}: no published {dependency} dependency; publish it first')
            tags[dependency] = dependency_tag
        profile = dict(context=context | dict(source_tags=tags, versions={}), sources={}, archives={},
                       baseline=baseline, directory=directory)
        for repo, source_tag in tags.items():
            if repo not in revisions:
                profile['sources'][repo] = baseline['sources'][repo]
                continue
            key = (repo, source_tag)
            if key not in captured:
                refs = ({f'refs/tags/{source_tag}': os.environ['RELEASE_SHA']} if repo == changed else sources({repo: source_tag})[repo])
                commit = refs.get(f'refs/tags/{source_tag}^{{}}', refs[f'refs/tags/{source_tag}'])
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
                captured[key] = (version, refs, archive)
            version, refs, archive = captured[key]
            profile['context']['versions'][repo] = version
            profile['sources'][repo] = refs
            profile['archives'][repo] = archive
            observed.setdefault(repo, {}).update(refs)
        profiles[row['id']] = profile
    for name, data in [('profiles', profiles), ('sources', observed), ('context', context),
                       ('targets', rows), ('revisions', revisions)]:
        (bundle / f'{name}.json').write_text(json.dumps(data, indent=2) + '\n')
    run('tar', '-czf', str(bundle / 'feed.tar.gz'), '--exclude=.git', '--exclude=__pycache__', '-C', str(ROOT), '.')
    (bundle / 'checksums.json').write_text(json.dumps({str(path.relative_to(bundle)): digest(path)
        for path in [*archives.iterdir(), bundle / 'feed.tar.gz']}, indent=2) + '\n')
    unchanged(bundle)


def select(bundle, target, project, baseline=None):
    profile = json.loads((bundle / 'profiles.json').read_text())[target]
    if project not in REPOSITORIES:
        raise ValueError('Unknown build project')
    if baseline is not None:
        profile['baseline'] = baseline
    previous = profile['baseline']
    profile['context']['build_project'] = project
    # Record the actual retained counterpart, not the source planned for its next build.
    for values, old in [(profile['sources'], previous.get('sources', {})),
                        (profile['context']['source_tags'], previous.get('context', {}).get('source_tags', {})),
                        (profile['context']['versions'], previous.get('context', {}).get('versions', {}))]:
        for other in REPOSITORIES:
            if other != project:
                values.pop(other, None)
                if other in old:
                    values[other] = old[other]
    for key in ['context', 'sources']:
        (bundle / f'{key}.json').write_text(json.dumps(profile[key], indent=2) + '\n')
    (bundle / 'baseline.json').write_text(json.dumps(previous))
    archive = profile['archives'][project]
    shutil.copy2(bundle / 'archives' / archive, bundle / f'{project}-{profile["context"]["versions"][project]}.tar.gz')
    return profile


def project_file(name, project):
    filename = Path(name).name
    extension = filename.endswith(('.deb', '.rpm', '.ipk', '.apk', '.tar.zst'))
    normalized = filename.replace('snode.c-', 'snodec-', 1).replace('snode.c_', 'snodec_', 1)
    return extension and package_owner(normalized) == project


def reuse(bundle, target, destination):
    profile = json.loads((bundle / 'profiles.json').read_text())[target]
    row = next(r for r in json.loads((bundle / 'targets.json').read_text()) if r['id'] == target)
    info = json.loads((bundle / 'baseline.json').read_text())
    built = json.loads((bundle / 'context.json').read_text())['build_project']
    others = [repo for repo in REPOSITORIES if repo != built]
    destination.mkdir(parents=True, exist_ok=True)
    for name, checksum in info.get('files', {}).items():
        filename = Path(name).name
        if not any(project_file(filename, project) for project in others):
            continue
        directory = f'{row["distribution"]}/pool/{row["suite"]}' if filename.endswith('.deb') else profile['directory']
        path = destination / filename
        ref = os.environ.get('PUBLISHED_REF') or profile['context']['packages_commit']
        fetch(f'https://raw.githubusercontent.com/SNodeC/Packages/{ref}/{directory}/{name}', path)
        if digest(path) != checksum:
            raise RuntimeError(f'Published dependency checksum mismatch: {name}')
    if row['family'] != 'openwrt':
        for project in others:
            prefix = PROJECTS[project]['package']
            names = [name for name in info.get('packages', []) if package_owner(name) == project]
            if names:
                (destination / f'{prefix}.packages').write_text('\n'.join(names) + '\n')


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


def sdk_dependency(sdk, bundle, archives):
    """Import registered prerequisite development exports, rejecting conflicting files."""
    info = json.loads((sdk / 'ci-sdk.json').read_text())
    baseline = json.loads((bundle / 'baseline.json').read_text())
    project = json.loads((bundle / 'context.json').read_text())['build_project']
    for dependency in dependencies(project):
        prefix = PROJECTS[dependency]['package'] + '-openwrt-build-deps-'
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
    versions = info.get('versions', {})
    version = versions.get(project, versions.get(PROJECTS[project]['package']))
    if version is None:
        return int(info['revision']) if info.get('context', {}).get('build_project') == project else 0
    match = re.search(r'-r?(\d+)(?:[.~]|$)', version)
    if not match:
        raise RuntimeError(f'Invalid package revision: {version}')
    return int(match[1])


def publication_needed(previous, incoming):
    if isinstance(previous, Path):
        if not previous.exists():
            return True
        previous = json.loads(previous.read_text())
    project = incoming['context']['build_project']
    old = project_revision(previous, project)
    new = int(incoming['revision'])
    if old > new:
        raise RuntimeError('Superseded publication: a newer project revision is already published')
    if old == new:
        if (all(previous.get(key) == incoming.get(key) for key in ('sources', 'context'))
                and previous.get('unsigned_files', previous.get('files')) == incoming.get('files')):
            return False
        raise RuntimeError('Different package content under the same publication revision')
    return True


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
    elif command == 'sdk-export':
        sdk_export(Path(args[0]).resolve(), Path(args[1]).resolve(), *args[2:])
    else:
        {'prepare': prepare, 'check': unchanged, 'stage': stage, 'publish': publish,
         'sdk-dependency': sdk_dependency}[command](
            *(Path(arg).resolve() for arg in args))
