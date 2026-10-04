"""Signed RPM packages and DNF metadata for the selected target distribution."""
import json
import os
from pathlib import Path
import shutil
import tempfile

from ci.repository import ROOT, digest, run, signer, unchanged, publication_needed, project_file


def stage(row, packages, bundle, output):
    unchanged(bundle)
    directory = output / row['distribution'] / row['suite'] / row['arch']
    pool = directory / 'Packages'
    pool.mkdir(parents=True)
    project = json.loads((bundle / 'context.json').read_text())['build_project']
    required = packages / ('snodec.packages' if project == 'snode.c' else 'mqttsuite.packages')
    if not required.is_file():
        raise RuntimeError('Missing built project package inventory')
    expected = {name for inventory in packages.glob('*.packages') for name in inventory.read_text().splitlines()}
    names = set()
    versions = {}
    for package in packages.glob('*.rpm'):
        name, arch = run('rpm', '-qp', '--qf', '%{NAME} %{ARCH}', str(package)).split()
        if arch != row['arch'] or name in names:
            raise RuntimeError(f'Unexpected RPM: {name}/{arch}')
        names.add(name)
        if name in {'snodec', 'mqttsuite'}:
            versions[name] = run('rpm', '-qp', '--qf', '%{VERSION}-%{RELEASE}', str(package))
        shutil.copy2(package, pool / package.name)
    if names != expected:
        raise RuntimeError('Incomplete RPM component inventory')
    with signer() as home:
        key = next(line.split(':')[9] for line in run('gpg', '--homedir', home, '--with-colons',
                                                     '--list-secret-keys').splitlines() if line.startswith('fpr:'))
        for package in pool.glob('*.rpm'):
            if not project_file(package.name, project):
                continue
            run('rpmsign', '--define', f'_gpg_name {key}', '--define', f'_gpg_path {home}',
                '--define', '_gpgbin /usr/bin/gpg', '--define', '_gpg_digest_algo sha256',
                '--addsign', str(package))
        run('createrepo_c', str(directory))
        index = directory / 'repodata/repomd.xml'
        run('gpg', '--homedir', home, '--batch', '--yes', '--armor', '--output', str(index) + '.asc',
            '--detach-sign', str(index))
    info = dict(row, packages=sorted(names), versions=versions, revision=os.environ['PACKAGE_RELEASE'],
                sources=json.loads((bundle / 'sources.json').read_text()),
                context=json.loads((bundle / 'context.json').read_text()),
                files={str(p.relative_to(directory)): digest(p) for p in directory.rglob('*') if p.is_file()})
    (directory / 'build.json').write_text(json.dumps(info, indent=2) + '\n')
    unchanged(bundle)


def publish(rows, incoming, checkout, bundle):
    unchanged(bundle)
    changed = []
    for row in rows:
        relative = Path(row['distribution']) / row['suite'] / row['arch']
        directory = incoming / relative
        info = json.loads((directory / 'build.json').read_text())
        if info['sources'] != json.loads((bundle / 'sources.json').read_text()):
            raise RuntimeError('Mixed source generations')
        if any(info[k] != v for k, v in row.items()):
            raise RuntimeError('Unexpected RPM target')
        for name, checksum in info['files'].items():
            if Path(name).is_absolute() or '..' in Path(name).parts or digest(directory / name) != checksum:
                raise RuntimeError(f'RPM checksum mismatch: {name}')
        with tempfile.TemporaryDirectory() as home:
            key = str(ROOT / 'keys/snodec-apt.asc')
            run('gpg', '--homedir', home, '--batch', '--import', key)
            index = directory / 'repodata/repomd.xml'
            run('gpg', '--homedir', home, '--batch', '--verify', str(index) + '.asc', str(index))
            db = str(Path(home) / 'rpmdb')
            run('rpm', '--dbpath', db, '--initdb')
            run('rpm', '--dbpath', db, '--import', key)
            names = []
            for name in info['files']:
                if not name.endswith('.rpm'):
                    continue
                path = str(directory / name)
                signature = run('rpm', '--dbpath', db, '--checksig', path)
                if 'signatures OK' not in signature:
                    raise RuntimeError(f'Unsigned RPM: {name}')
                package, arch = run('rpm', '--dbpath', db, '-qp', '--qf', '%{NAME} %{ARCH}', path).split()
                if arch != row['arch']:
                    raise RuntimeError('RPM architecture mismatch')
                names.append(package)
            if sorted(names) != info['packages']:
                raise RuntimeError('Unexpected RPM inventory')
        previous = checkout / relative / 'build.json'
        if publication_needed(previous, info):
            changed.append(row)
    for row in changed:
        relative = Path(row['distribution']) / row['suite'] / row['arch']
        shutil.copytree(incoming / relative, checkout / relative, dirs_exist_ok=True)
    unchanged(bundle)
