"""Retain the Packages 6c1007a Release contract and completed-index checksums.

Header fixture: SNodeC/Packages@6c1007a debian/dists/trixie/Release.
"""

from contextlib import contextmanager
import gzip
import hashlib
from email.utils import parsedate_to_datetime
from pathlib import Path
import subprocess
import tempfile
from support import ROOT
from coreci.sign_native import apt_indexes


@contextmanager
def generated_suite(directory):
    root = directory / 'feed'
    source = directory / 'package'
    (source / 'DEBIAN').mkdir(parents=True)
    (source / 'DEBIAN/control').write_text(
        'Package: release-probe\nVersion: 1.0\nArchitecture: amd64\n'
        'Maintainer: Fixture <fixture@example.invalid>\nDescription: Release checksum fixture\n')
    pool = root / 'debian/pool/trixie'
    pool.mkdir(parents=True)
    subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(source),
                    str(pool / 'release-probe_1.0_amd64.deb')], check=True, capture_output=True)
    suite = root / 'debian/dists/trixie'
    other = suite / 'main/binary-arm64'
    other.mkdir(parents=True)
    (other / 'Packages').write_bytes(b'')
    (other / 'Packages.gz').write_bytes(gzip.compress(b'', mtime=0))
    (suite / 'not-an-index.txt').write_text('not included in Release checksums\n')
    for name in ('Release', 'InRelease', 'Release.gpg'):
        (suite / name).write_text('stale metadata\n')
    home = directory / 'gnupg'
    home.mkdir(mode=0o700)
    gpg = ['gpg', '--homedir', str(home), '--batch', '--yes', '--pinentry-mode', 'loopback',
           '--passphrase', '']
    key = directory / 'fixture-public.gpg'
    try:
        subprocess.run(gpg + ['--quick-generate-key', 'Release fixture <fixture@example.invalid>',
                             'ed25519', 'sign', '0'], check=True, capture_output=True)
        with key.open('wb') as outgoing:
            subprocess.run(gpg + ['--export'], stdout=outgoing, stderr=subprocess.PIPE, check=True)
        apt_indexes(root, 'debian', 'trixie', 'amd64', gpg, key)
        yield root, key
    finally:
        subprocess.run(['gpgconf', '--homedir', str(home), '--kill', 'gpg-agent'],
                       check=True, capture_output=True)


def check_checksums(root):
    suite = root / 'debian/dists/trixie'
    baseline = (ROOT / 'tests/coreci/data/apt-release-6c1007a').read_text().splitlines()
    fields = (suite / 'Release').read_text().splitlines()[:len(baseline)]
    assert [line.split(':', 1)[0] for line in fields] == [line.split(':', 1)[0] for line in baseline]
    for actual, original in zip(fields, baseline):
        name = original.split(':', 1)[0]
        if name == 'Architectures':
            assert actual == 'Architectures: amd64 arm64'
        elif name == 'Date':
            assert parsedate_to_datetime(actual.split(': ', 1)[1]).tzinfo is not None
        else:
            assert actual == original, (actual, original)
    expected = {f'main/binary-{arch}/{name}' for arch in ('amd64', 'arm64')
                for name in ('Packages', 'Packages.gz')}
    algorithms = {'SHA256': 'sha256'}
    lists = {name: {} for name in algorithms}
    section = None
    for line in (suite / 'Release').read_text().splitlines():
        if line and not line[0].isspace():
            section = line.split(':', 1)[0]
            assert section not in ('MD5Sum', 'SHA1', 'SHA512'), section
        elif section in algorithms:
            digest, size, name = line.split()
            assert name not in lists[section], (section, 'duplicate entry', name)
            lists[section][name] = (digest, int(size))
    for name, entries in lists.items():
        assert set(entries) == expected, (name, 'expected only index files', set(entries))
        assert all(Path(path).name not in ('Release', 'InRelease', 'Release.gpg') for path in entries)
        for path, (digest, size) in entries.items():
            data = (suite / path).read_bytes()
            assert len(data) == size, (name, path, 'size mismatch')
            assert hashlib.new(algorithms[name], data).hexdigest() == digest, (name, path, 'digest mismatch')
            assert (suite / Path(path).parent / 'by-hash/SHA256' / digest).read_bytes() == data
    assert (suite / 'InRelease').is_file() and (suite / 'Release.gpg').is_file()


def main():
    with tempfile.TemporaryDirectory() as temporary:
        with generated_suite(Path(temporary)) as (root, key):
            check_checksums(root)
    print('APT Release: exactly four indices; SHA256 sizes, digests and by-hash bytes match')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
