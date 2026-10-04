"""Signed APT feeds, sharing source provenance and publication with OpenWrt."""
import gzip
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from ci.repository import ROOT, digest, run, unchanged, linux_matrix, signer


def suites(distribution='raspberrypios'):
    if distribution == 'raspberrypios':
        return json.loads((ROOT / 'ci/targets/raspberrypi.json').read_text())
    return {row['suite']: row['image'] for row in linux_matrix() if row['distribution'] == distribution}


def architectures(distribution, suite):
    return ['arm64'] if distribution == 'raspberrypios' else sorted(
        row['arch'] for row in linux_matrix() if row['distribution'] == distribution and row['suite'] == suite)


def stage(suite, packages, bundle, output, distribution='raspberrypios'):
    image = suites(distribution)[suite]
    unchanged(bundle)
    names = set()
    versions = {}
    by_arch = {}
    for package in packages.glob('*.deb'):
        name, architecture = run('dpkg-deb', '-f', str(package), 'Package', 'Architecture').splitlines()
        name = name.removeprefix('Package: ')
        architecture = architecture.removeprefix('Architecture: ')
        if (name, architecture) in names:
            raise RuntimeError(f'Duplicate Debian package: {name}')
        names.add((name, architecture))
        if name in {'snodec', 'mqttsuite'}:
            versions[name] = run('dpkg-deb', '-f', str(package), 'Version')
        by_arch.setdefault(architecture, set()).add(name)
        if architecture not in architectures(distribution, suite):
            raise RuntimeError(f'Unexpected architecture: {architecture}')
    project = json.loads((bundle / 'context.json').read_text())['build_project']
    required = packages / ('snodec.packages' if project == 'snode.c' else 'mqttsuite.packages')
    if not required.is_file():
        raise RuntimeError('Missing built project package inventory')
    expected = {name for inventory in packages.glob('*.packages') for name in inventory.read_text().splitlines()}
    if not by_arch or any(names != expected for names in by_arch.values()):
        raise RuntimeError(f'Incomplete Debian package set: {names}')
    if len(by_arch) != 1:
        raise RuntimeError('Build artifact must contain exactly one architecture')
    arch = next(iter(by_arch))
    target = output / distribution / suite / arch
    target.mkdir(parents=True)
    for path in [*packages.glob('*.deb'), *packages.glob('*.packages')]:
        shutil.copy2(path, target / path.name)
    info = dict(suite=suite, distribution=distribution, image=image, architectures=[arch], packages=sorted(expected), versions=versions,
                revision=os.environ['PACKAGE_RELEASE'],
                sources=json.loads((bundle / 'sources.json').read_text()),
                context=json.loads((bundle / 'context.json').read_text()),
                files={p.name: digest(p) for p in target.iterdir() if p.is_file()})
    (target / 'build.json').write_text(json.dumps(info, indent=2) + '\n')
    unchanged(bundle)


def index(apt, suite, by_arch):
    dist = apt / 'dists' / suite
    records = run('apt-ftparchive', 'packages', f'pool/{suite}', cwd=apt).split('\n\n')
    for arch in sorted(by_arch):
        index = dist / f'main/binary-{arch}'
        index.mkdir(parents=True)
        contents = '\n\n'.join(record for record in records if f'Architecture: {arch}' in record.splitlines()) + '\n\n'
        (index / 'Packages').write_text(contents)
        (index / 'Packages.gz').write_bytes(gzip.compress(contents.encode(), mtime=0))
        for path in list(index.iterdir()):
            target = index / 'by-hash/SHA256' / digest(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    release = run('apt-ftparchive', '--md5=no', '--sha1=no', '--sha512=no',
                  '-o', f'APT::FTPArchive::Release::Codename={suite}',
                  '-o', f'APT::FTPArchive::Release::Suite={suite}',
                  '-o', 'APT::FTPArchive::Release::Architectures=' + ' '.join(sorted(by_arch)),
                  '-o', 'APT::FTPArchive::Release::Components=main',
                  '-o', 'APT::FTPArchive::Release::Origin=SNodeC',
                  '-o', 'APT::FTPArchive::Release::Acquire-By-Hash=yes',
                  'release', f'dists/{suite}', cwd=apt)
    (dist / 'Release').write_text(release + '\n')
    with signer() as home:
        for option, filename in [('--clearsign', 'InRelease'), ('--detach-sign', 'Release.gpg')]:
            run('gpg', '--homedir', home, '--batch', '--yes', '--armor',
                '--output', str(dist / filename), option, str(dist / 'Release'))

    with tempfile.TemporaryDirectory() as home:
        run('gpg', '--homedir', home, '--batch', '--import', str(ROOT / 'keys/snodec-apt.asc'))
        run('gpg', '--homedir', home, '--batch', '--verify', str(dist / 'InRelease'))
        run('gpg', '--homedir', home, '--batch', '--verify', str(dist / 'Release.gpg'), str(dist / 'Release'))


def active_targets(base, suite):
    """Read per-architecture generations; import older suite inventories once."""
    manifest = base / 'dists' / suite / 'build.json'
    if not manifest.exists():
        return {}
    previous = json.loads(manifest.read_text())
    for name, checksum in previous['files'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or digest(base / path) != checksum:
            raise RuntimeError(f'Existing APT inventory mismatch: {name}')
    if 'targets' in previous:
        return previous['targets']
    targets = {}
    for arch in previous['architectures']:
        records = (base / 'dists' / suite / f'main/binary-{arch}/Packages').read_text().split('\n\n')
        files, names = {}, []
        for record in records:
            fields = dict(line.split(': ', 1) for line in record.splitlines() if ': ' in line and not line.startswith(' '))
            if not fields:
                continue
            filename = fields['Filename']
            if fields['Architecture'] != arch or previous['files'].get(filename) != fields['SHA256']:
                raise RuntimeError('Cannot import existing APT index into architecture inventory')
            files[Path(filename).name] = fields['SHA256']
            names.append(fields['Package'])
        targets[arch] = dict(distribution=previous['distribution'], suite=suite,
                             image=previous['image'], architectures=[arch], packages=sorted(names),
                             revision=previous['revision'], sources=previous['sources'],
                             context=previous['context'], files=files)
    return targets


def publish(incoming, checkout, bundle, distribution='raspberrypios'):
    unchanged(bundle)
    expected = {(suite, arch) for suite in suites(distribution) for arch in architectures(distribution, suite)}
    found = {p.parent.relative_to(incoming / distribution).parts
             for p in (incoming / distribution).glob('*/*/build.json')}
    if not found or not found <= expected:
        raise RuntimeError(f'Unexpected {distribution} targets: {found - expected}')
    for suite in sorted({suite for suite, _ in found}):
        base = checkout / distribution
        targets = active_targets(base, suite)
        incoming_packages = {}
        changed = False
        for _, arch in sorted(pair for pair in found if pair[0] == suite):
            target = incoming / distribution / suite / arch
            info = json.loads((target / 'build.json').read_text())
            if (info['sources'] != json.loads((bundle / 'sources.json').read_text())
                    or info['context'] != json.loads((bundle / 'context.json').read_text())):
                raise RuntimeError('Mixed source generations')
            if (info['suite'] != suite or info['distribution'] != distribution
                    or info['architectures'] != [arch] or info['image'] != suites(distribution)[suite]):
                raise RuntimeError('Unexpected APT target')
            names = []
            for name, checksum in info['files'].items():
                path = target / name
                if Path(name).name != name or path.is_symlink() or digest(path) != checksum:
                    raise RuntimeError(f'APT checksum mismatch: {name}')
                if path.suffix == '.deb':
                    package, package_arch = run('dpkg-deb', '-f', str(path), 'Package', 'Architecture').splitlines()
                    if package_arch.removeprefix('Architecture: ') != arch:
                        raise RuntimeError(f'Unexpected package architecture: {name}')
                    names.append(package.removeprefix('Package: '))
                    existing = base / 'pool' / suite / name
                    if existing.exists() and digest(existing) != checksum:
                        raise RuntimeError(f'Refusing to replace existing package bytes: {name}')
                    incoming_packages[name] = path
            if sorted(names) != info['packages']:
                raise RuntimeError('Incomplete Debian package set')
            if arch in targets:
                old = targets[arch]
                if int(old['revision']) > int(info['revision']):
                    raise RuntimeError('Superseded publication: a newer architecture revision exists')
                if int(old['revision']) == int(info['revision']):
                    if {k: v for k, v in old.items() if k != 'published_at'} != info:
                        raise RuntimeError('Different APT content under the same publication revision')
                    continue
            targets[arch] = info
            changed = True
        if not changed:
            continue
        with tempfile.TemporaryDirectory() as temporary:
            apt = Path(temporary) / distribution
            pool = apt / 'pool' / suite
            pool.mkdir(parents=True)
            # Only current architecture inventories enter the regenerated indexes.
            # Retained older packages remain on disk, never in this staging pool.
            for info in targets.values():
                for name, checksum in info['files'].items():
                    if not name.endswith('.deb'):
                        continue
                    source = incoming_packages.get(name, base / 'pool' / suite / name)
                    if Path(name).name != name or digest(source) != checksum:
                        raise RuntimeError(f'Active APT package mismatch: {name}')
                    shutil.copy2(source, pool / name)
            index(apt, suite, targets)
            info = dict(distribution=distribution, suite=suite, architectures=sorted(targets), targets=targets,
                        revision=str(max(int(t['revision']) for t in targets.values())),
                        files={str(p.relative_to(apt)): digest(p)
                               for directory in (pool, apt / 'dists' / suite)
                               for p in directory.rglob('*') if p.is_file()})
            (apt / 'dists' / suite / 'build.json').write_text(json.dumps(info, indent=2) + '\n')
            unchanged(bundle)
            # Keep old .debs and by-hash indexes for clients with cached metadata.
            shutil.copytree(apt, base, dirs_exist_ok=True)
    unchanged(bundle)


if __name__ == '__main__':
    command, *args = sys.argv[1:]
    if command == 'stage':
        stage(args[0], *(Path(p).resolve() for p in args[1:]))
    else:
        publish(*(Path(p).resolve() for p in args))
