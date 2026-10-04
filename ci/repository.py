"""Capture a release-tag generation; commit IDs are evidence, not pinned refs."""
from contextlib import contextmanager
import tempfile
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
REPOSITORIES = ('snode.c', 'mqttsuite')


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
    project = json.loads((bundle / 'context.json').read_text()).get('build_project')
    for repo, expected in json.loads((bundle / 'sources.json').read_text()).items():
        if project and repo != project:
            continue  # Published dependencies are checked by package inventory, not mutable source tags.
        observed = dict(line.split()[::-1] for line in run(
            'git', 'ls-remote', f'https://github.com/SNodeC/{repo}.git', *expected).splitlines())
        if observed != expected:
            raise RuntimeError('Source tags changed: refusing superseded build')


def prepare(published_root, bundle):
    from ci.publish.publication import targets, published
    bundle.mkdir(parents=True)
    archives = bundle / 'archives'
    archives.mkdir()
    changed = os.environ.get('RELEASE_PROJECT', '')
    tag = os.environ.get('RELEASE_TAG', '')
    if changed not in REPOSITORIES:
        raise ValueError('Unknown release project')
    # A fixed migration floor preserves increasing revisions in this new repository.
    revision_base = int(os.environ['PACKAGE_REVISION_BASE'])
    revisions = {repo: str(revision_base + 2 * int(os.environ['GITHUB_RUN_NUMBER']) + index)
                 for index, repo in enumerate(REPOSITORIES) if changed == 'snode.c' or repo == changed}
    context = dict(recipe_ref=os.environ.get('RECIPE_REF', 'main'),
                   recipe_commit=run('git', '-C', str(ROOT), 'rev-parse', 'HEAD'),
                   destination='SNodeC/Packages',
                   release_project=changed, run_id=os.environ.get('GITHUB_RUN_ID', 'local'),
                   run_url=f'https://github.com/{os.environ.get("GITHUB_REPOSITORY", "SNodeC/DistributionPackages")}/actions/runs/{os.environ.get("GITHUB_RUN_ID", "local")}')
    mqtt_tag = None
    if changed == 'snode.c':
        # A library release rebuilds the current application release.
        refs = run('git', 'ls-remote', '--tags', 'https://github.com/SNodeC/mqttsuite.git', 'refs/tags/v*')
        candidates = [line.split()[1].removeprefix('refs/tags/') for line in refs.splitlines()
                      if re.fullmatch(r'refs/tags/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', line.split()[1])]
        mqtt_tag = max(candidates, key=lambda value: tuple(map(int, value[1:].split('.'))))
    profiles, captured, observed = {}, {}, {}
    for row in targets():
        baseline, directory = published(published_root, row)
        if (baseline and min(map(int, revisions.values())) <= int(baseline['revision'])
                and baseline.get('context', {}).get('run_id') != context['run_id']):
            raise RuntimeError('Package revision must exceed the published revision; check PACKAGE_REVISION_BASE')
        tags = ({'snode.c': tag, 'mqttsuite': mqtt_tag} if changed == 'snode.c' else
                dict(baseline.get('context', {}).get('source_tags', {}), mqttsuite=tag))
        if set(tags) != set(REPOSITORIES):
            raise RuntimeError(f'{row["id"]}: no published SNode.C dependency; publish a SNode.C release first')
        profile = dict(context=context | dict(source_tags=tags, versions={}), sources={}, archives={},
                       baseline=baseline, directory=directory)
        for repo, source_tag in tags.items():
            if changed == 'mqttsuite' and repo == 'snode.c':
                profile['sources'][repo] = baseline['sources'][repo]
                continue
            key = (repo, source_tag)
            if key not in captured:
                refs = sources({repo: source_tag})[repo]
                commit = refs.get(f'refs/tags/{source_tag}^{{}}', refs[f'refs/tags/{source_tag}'])
                with tempfile.TemporaryDirectory() as tmp:
                    source = Path(tmp) / repo
                    run('git', 'clone', '--depth', '1', '--branch', source_tag, '--recurse-submodules',
                        f'https://github.com/SNodeC/{repo}.git', str(source))
                    if run('git', '-C', str(source), 'rev-parse', 'HEAD') != commit:
                        raise RuntimeError('Source tag changed during capture')
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
                       ('targets', targets()), ('revisions', revisions)]:
        (bundle / f'{name}.json').write_text(json.dumps(data, indent=2) + '\n')
    run('tar', '-czf', str(bundle / 'feed.tar.gz'), '--exclude=.git', '--exclude=__pycache__', '-C', str(ROOT), '.')
    unchanged(bundle)


def select(bundle, target, project, baseline=None):
    profile = json.loads((bundle / 'profiles.json').read_text())[target]
    if project not in REPOSITORIES:
        raise ValueError('Unknown build project')
    if baseline is not None:
        profile['baseline'] = baseline
    other = next(repo for repo in REPOSITORIES if repo != project)
    previous = profile['baseline']
    profile['context']['build_project'] = project
    # Record the actual retained counterpart, not the source planned for its next build.
    for values, old in [(profile['sources'], previous.get('sources', {})),
                        (profile['context']['source_tags'], previous.get('context', {}).get('source_tags', {})),
                        (profile['context']['versions'], previous.get('context', {}).get('versions', {}))]:
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
    prefixes = ('snodec_', 'snodec-', 'snode.c_', 'snode.c-') if project == 'snode.c' else ('mqttsuite_', 'mqttsuite-')
    return filename.endswith(('.deb', '.rpm', '.ipk', '.apk', '.tar.zst')) and filename.startswith(prefixes)


def reuse(bundle, target, destination):
    profile = json.loads((bundle / 'profiles.json').read_text())[target]
    row = next(r for r in json.loads((bundle / 'targets.json').read_text()) if r['id'] == target)
    info = json.loads((bundle / 'baseline.json').read_text())
    built = json.loads((bundle / 'context.json').read_text())['build_project']
    project = next(repo for repo in REPOSITORIES if repo != built)
    if project == 'snode.c' and row['family'] == 'openwrt' and len([n for n in info.get('files', {}) if n.startswith('snode.c-sdk-') and n.endswith('.tar.zst')]) != 1:
        raise RuntimeError(f'{target}: published SNode.C development files are missing; publish a SNode.C release first')
    destination.mkdir(parents=True, exist_ok=True)
    for name, checksum in info.get('files', {}).items():
        filename = Path(name).name
        if not project_file(filename, project):
            continue
        directory = f'{row["distribution"]}/pool/{row["suite"]}' if filename.endswith('.deb') else profile['directory']
        path = destination / filename
        urllib.request.urlretrieve(f'https://raw.githubusercontent.com/SNodeC/Packages/main/{directory}/{name}', path)
        if digest(path) != checksum:
            raise RuntimeError(f'Published dependency checksum mismatch: {name}')
    if row['family'] != 'openwrt':
        prefix = 'snodec' if project == 'snode.c' else project
        names = [n for n in info.get('packages', []) if n == prefix or n.startswith(prefix + '-')]
        if names:
            (destination / f'{prefix}.packages').write_text('\n'.join(names) + '\n')


def fetch(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


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
    urllib.request.urlretrieve(base + filename, archive)
    if digest(archive) != checksum:
        raise RuntimeError('SDK checksum mismatch')
    destination.mkdir()
    run('tar', '-xf', str(archive), '--strip-components=1', '-C', str(destination))
    archive.unlink()
    (destination / 'ci-sdk.json').write_text(json.dumps(dict(row, sdk_url=base + filename, sha256=checksum)))


def stage(sdk, bundle, output):
    """Stage project packages and signed indexes; official feeds supply other dependencies."""
    info = json.loads((sdk / 'ci-sdk.json').read_text())
    feed = sdk / 'bin/packages' / info['arch'] / 'snodec'
    extension = '.ipk' if info['series'] == '24.10' else '.apk'
    packages = sorted(feed.glob('*' + extension))
    destination = output / 'openwrt' / info['series'] / info['arch']
    destination.mkdir(parents=True)
    indexes = ['Packages', 'Packages.gz', 'Packages.sig'] if extension == '.ipk' else ['packages.adb']
    development = list(sdk.glob('snode.c-sdk-*.tar.zst'))
    if len(development) != 1:
        raise RuntimeError('Expected one SNode.C development archive')
    for path in packages + [feed / name for name in indexes] + development:
        shutil.copy2(path, destination / path.name)
    files = {p.name: digest(p)
             for p in destination.iterdir()}
    info.update(sources=json.loads((bundle / 'sources.json').read_text()), files=files,
                revision=os.environ['PACKAGE_RELEASE'],
                context=json.loads((bundle / 'context.json').read_text()))
    info['versions'] = {repo: f"{version}-r{info['revision']}"
                        for repo, version in info['context']['versions'].items()}
    baseline = json.loads((bundle / 'baseline.json').read_text())
    other = 'mqttsuite' if info['context']['build_project'] == 'snode.c' else 'snode.c'
    if other in baseline.get('versions', {}):
        info['versions'][other] = baseline['versions'][other]
    (destination / 'build.json').write_text(json.dumps(info, indent=2) + '\n')


def sdk_dependency(sdk, bundle, dependencies):
    """Export/reuse the SDK's installed development files, never build trees or stamps."""
    info = json.loads((sdk / 'ci-sdk.json').read_text())
    baseline = json.loads((bundle / 'baseline.json').read_text())
    if json.loads((bundle / 'context.json').read_text())['build_project'] == 'mqttsuite':
        if any(baseline[key] != info[key] for key in ('release', 'target', 'arch', 'sha256')):
            raise RuntimeError('Published SNode.C requires a different OpenWrt SDK; publish a SNode.C release first')
        name, = (n for n in baseline['files'] if n.startswith('snode.c-sdk-') and n.endswith('.tar.zst'))
        archive = dependencies / name
        if digest(archive) != baseline['files'][name]:
            raise RuntimeError('SNode.C development archive checksum mismatch')
        with tempfile.TemporaryDirectory(dir=sdk) as tmp:
            root = Path(tmp)
            run('tar', '--zstd', '-xf', str(archive), '-C', tmp)
            origin = json.loads((root / 'sdk-development.json').read_text())
            if origin['sdk'] != info:
                raise RuntimeError('SNode.C development archive SDK mismatch')
            # CMake and pkg-config exports can contain SDK-absolute dependency paths.
            # Relocate installed metadata only; sources and binary files stay untouched.
            for path in (root / 'staging_dir').rglob('*'):
                if path.is_file() and not path.is_symlink() and path.suffix in {'.cmake', '.pc', '.la'}:
                    path.write_text(path.read_text().replace(origin['path'] + '/', str(sdk) + '/'))
            run('cp', '-a', str(root / 'staging_dir') + '/.', str(sdk / 'staging_dir'))
        shutil.copy2(archive, sdk / name)
    else:
        target, = sdk.glob('staging_dir/target-*')
        context = json.loads((bundle / 'context.json').read_text())
        archive = sdk / f'snode.c-sdk-{context["versions"]["snode.c"]}-r{os.environ["PACKAGE_RELEASE"]}.tar.zst'
        with tempfile.TemporaryDirectory(dir=sdk) as tmp:
            (Path(tmp) / 'sdk-development.json').write_text(json.dumps(dict(sdk=info, path=str(sdk))))
            run('tar', '--zstd', '-cf', str(archive), '-C', tmp, 'sdk-development.json',
                '-C', str(sdk), str(target.relative_to(sdk) / 'usr/include'),
                str(target.relative_to(sdk) / 'usr/lib'),
                *(str(p.relative_to(sdk)) for p in sorted((target / 'pkginfo').glob('*.provides'))))


def publication_needed(previous, incoming):
    if not previous.exists():
        return True
    current = json.loads(previous.read_text())
    if int(current['revision']) > int(incoming['revision']):
        raise RuntimeError('Superseded publication: a newer revision is already published')
    if int(current['revision']) == int(incoming['revision']):
        if all(current.get(key) == incoming.get(key) for key in ('sources', 'context', 'files')):
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
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(directory, destination, dirs_exist_ok=True)
    unchanged(bundle)


if __name__ == '__main__':
    command, *args = sys.argv[1:]
    if command == 'matrix':
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
         'sdk-dependency': sdk_dependency}[command](
            *(Path(arg).resolve() for arg in args))
