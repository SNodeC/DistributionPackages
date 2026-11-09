from pathlib import Path
import tempfile
from unittest.mock import patch
from support import entry
from coreci import publish


PACKAGES = ('snodec', 'snodec-idp', 'mqttsuite')


def probe(fmt):
    target = entry(fmt)
    target.update(id='debian-trixie-amd64' if fmt == 'deb' else 'rocky-10-x86_64',
                  distribution='debian' if fmt == 'deb' else 'rocky', suite='trixie' if fmt == 'deb' else '10')
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        directory = root / publish.target_directory(target)
        directory.mkdir(parents=True)
        records = {}
        protected = {}
        own_old = set()
        for package in PACKAGES:
            for component in (package, package + '-client-dev'):
                for revision in (1, 12, 13):
                    # Revision 1 has no ledger: it predates core-ci.
                    version = f'2.1.0-{revision}~trixie' if fmt == 'deb' else f'2.1.0-{revision}.el10'
                    name = f'{component}_{version}_{target["arch"]}.deb' if fmt == 'deb' else f'{component}-{version}.{target["arch"]}.rpm'
                    path = directory / name
                    path.write_text(name)
                    records[path] = dict(name=component, version=version, arch=target['arch'])
                    if package != 'snodec':
                        protected[path] = path.read_bytes()
                    elif revision == 1:
                        own_old.add(str(path.relative_to(root)))
        for arch in ('all', 'noarch', 'arm64'):
            path = directory / ('snodec-independent-' + arch + '.' + fmt)
            path.write_bytes(b'protected independent or foreign-architecture file')
            records[path] = dict(name='snodec-independent', version='1.0.0-1', arch=arch)
            protected[path] = path.read_bytes()
        manifest = dict(package='snodec', entry=target, version='2.1.0', revision=13)
        with patch('coreci.contract.package_metadata', side_effect=lambda path, _: records[path]):
            removed = publish.retention(root, manifest, PACKAGES)
        assert removed == own_old, removed
        assert all(path.read_bytes() == contents for path, contents in protected.items())
        assert all(publish.package_owner(records[root / name]['name'], PACKAGES) == 'snodec' for name in removed)
        assert publish.package_owner('snodec-idp-client-dev', PACKAGES) == 'snodec-idp'
        assert publish.package_owner('snodec-extra', PACKAGES) == 'snodec'
        assert publish.package_owner('snodeclient', PACKAGES) == ''
    return None


def main():
    probe('deb')
    probe('rpm')
    print('retention ownership: Debian trixie and Rocky 10 preserve every IDP/MQTTSuite, independent and foreign-architecture file; legacy component publications grouped')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
