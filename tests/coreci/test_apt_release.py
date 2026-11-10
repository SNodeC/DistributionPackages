"""Generated APT checksums cover only the completed suite indices."""

from contextlib import contextmanager
import gzip
import hashlib
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
    expected = {f'main/binary-{arch}/{name}' for arch in ('amd64', 'arm64')
                for name in ('Packages', 'Packages.gz')}
    algorithms = {'MD5Sum': 'md5', 'SHA1': 'sha1', 'SHA256': 'sha256', 'SHA512': 'sha512'}
    lists = {name: {} for name in algorithms}
    section = None
    for line in (suite / 'Release').read_text().splitlines():
        if line and not line[0].isspace():
            section = line.split(':', 1)[0]
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
    assert (suite / 'InRelease').is_file() and (suite / 'Release.gpg').is_file()


def main():
    with tempfile.TemporaryDirectory() as temporary:
        with generated_suite(Path(temporary)) as (root, key):
            check_checksums(root)
    print('APT Release: exactly four indices; MD5Sum/SHA1/SHA256/SHA512 sizes and digests match')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
