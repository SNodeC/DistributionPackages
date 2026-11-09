from pathlib import Path
import re
import subprocess
import tempfile
from unittest.mock import patch
from support import entry, rejects
from coreci import publish, sdk, sign_native
from coreci.lease import prepare_commit
from coreci.contract import package_metadata


def git(root, *arguments):
    result = subprocess.check_output(['git', '-C', str(root), *arguments], text=True).strip()
    return result


def deb(root, version, arch='amd64', name='a'):
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary)
        (source / 'DEBIAN').mkdir()
        (source / 'DEBIAN/control').write_text(
            f'Package: {name}\nVersion: {version}\nArchitecture: {arch}\n'
            'Maintainer: Fixture <fixture@example.invalid>\nDescription: retention fixture\n')
        target = root / f'debian/pool/stable/{name}_{version}_{arch}.deb'
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['dpkg-deb', '--build', str(source), str(target)], check=True, capture_output=True)
    return target


def signature(gpg, keyring, path, clear=False):
    result = Path(str(path) + ('.inrelease' if clear else '.gpg'))
    result.write_bytes(b'fixture signature; cryptographic checks are covered separately')
    return result


def native():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        target = entry()
        manifest = dict(package='a', entry=target, target=target['id'], version='0.9.0', revision=1,
                        files={'a.deb': 'a' * 64})
        old = deb(root, '0.9.0-1')  # Before core-ci: no ledger, no suite release suffix.
        protected = [deb(root, '0.8.0-1', 'all'), deb(root, '0.8.0-1', 'arm64'),
                     deb(root, '0.8.0-1', name='another')]
        for name in ('receipts/a/1.json', 'coreci/published/t1/old.sha256', 'ubuntu/unrelated',
                     'debian/dists/stable/main/binary-arm64/Packages'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'protected bytes')
            protected.append(path)
        baseline = {str(path.relative_to(root)): path.read_bytes() for path in protected}
        git(root, 'init', '-b', 'main')
        git(root, 'add', '.')
        git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'fixture')
        publish.sparse_checkout(root, manifest)
        assert not protected[1].exists() and not (root / 'ubuntu/unrelated').exists()
        assert protected[0].is_file() and protected[-1].is_file()
        assert subprocess.check_output(['git', '-C', str(root), 'show', 'HEAD:debian/pool/stable/a_0.8.0-1_arm64.deb']) == baseline['debian/pool/stable/a_0.8.0-1_arm64.deb']
        before = publish.snapshot(root)
        versions = ['1.0.0-1~stable', '1.0.0-2~stable', '1.1.0-1~stable', '1.1.0-2~stable']
        history = ['0.9.0-1']
        for version in versions:
            deb(root, version)
            deb(root, version, name='a-extra')
            history.append(version)
            removed = publish.retention(root, manifest)
            assert all(not (root / name).exists() for name in removed)
            actual = {package_metadata(path, 'deb')['version']
                      for path in (root / 'debian/pool/stable').glob('a*_amd64.deb')
                      if path.name.startswith(('a_', 'a-extra_'))}
            assert actual == set(history[-2:]), (version, actual)
            with patch.object(sign_native, 'sign_file', signature):
                sign_native.apt_indexes(root, 'debian', 'stable', 'amd64', [], root / 'fixture-key')
            index = (root / 'debian/dists/stable/main/binary-amd64/Packages').read_text()
            assert set(re.findall(r'^Version: (.+)$', index, re.M)) == set(history[-2:] + ['0.8.0-1'])
        assert not old.exists()
        ledger = root / 'coreci/published/t1/a_0.9.0-1.sha256'
        ledger.write_text(publish.ledger(manifest))
        rejects(publish.immutable, root, manifest, [str(old.relative_to(root))], text='retired')
        after = publish.snapshot(root)
        changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
        prepare_commit(root, changed, orphan=True, removed=changed - after.keys())
        for name, contents in baseline.items():
            assert subprocess.check_output(['git', '-C', str(root), 'show', 'HEAD:' + name]) == contents
    return 0


def openwrt():
    for fmt in ('ipk', 'apk', 'rpm'):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = entry(fmt)
            namespace = root / target['distribution'] / target['suite'] / target['arch']
            namespace.mkdir(parents=True)
            exports = root / 'dev' / target['id']
            exports.mkdir(parents=True)
            manifest = dict(package='a', entry=target)
            identities = {}
            for version, revision in [('1.0.0-alpha', 1), ('1.0.0', 1), ('1.0.0', 10), ('1.1.0', 1)]:
                encoded = publish.versions(version, revision, fmt, target)['full']
                path = namespace / f'a-{encoded}.{fmt}'
                path.write_bytes(b'fixture')
                identities[path] = dict(name='a', version=encoded, arch=target['arch'])
                if fmt != 'rpm':
                    (exports / f'a_{version}-r{revision}.tar.gz').write_bytes(b'export')
            independent = namespace / ('a-common.' + fmt)
            independent.write_bytes(b'keep')
            identities[independent] = dict(name='a-common', version='0.1.0-1', arch='noarch')
            with patch('coreci.contract.package_metadata', side_effect=lambda path, _: identities[path]):
                removed = publish.retention(root, manifest)
            assert len(removed) == (2 if fmt == 'rpm' else 4)
            assert independent.read_bytes() == b'keep'
            assert {path.name for path in exports.glob('*.tar.gz')} == (
                set() if fmt == 'rpm' else {'a_1.0.0-r10.tar.gz', 'a_1.1.0-r1.tar.gz'})
    return 0


def emulation():
    for family, arch, platform, host, expected in [
            ('native', 'amd64', 'linux/amd64', 'x86_64', ''),
            ('native', 'arm64', 'linux/arm64', 'aarch64', ''),
            ('native', 'armhf', 'linux/arm/v7', 'x86_64', 'arm'),
            ('native', 'riscv64', 'linux/riscv64', 'x86_64', 'riscv64'),
            ('openwrt', 'x86_64', '', 'x86_64', ''),
            ('openwrt', 'aarch64_generic', '', 'x86_64', 'arm64'),
            ('openwrt', 'mipsel_24kc', '', 'x86_64', 'mipsel')]:
        target = dict(family=family, arch=arch, build=dict(platform=platform, release='24.10.8'))
        with patch.object(sdk, 'read_json', return_value={'entry': target}), \
             patch.object(sdk.platform, 'machine', return_value=host), \
             patch.object(sdk, 'sdk', side_effect=ValueError('stop before SDK metadata')), \
             patch.object(sdk, 'github_outputs') as outputs:
            if family == 'openwrt':
                rejects(sdk.cache, 'manifest', text='stop before SDK metadata')
            else:
                sdk.cache('manifest')
            outputs.assert_called_once_with(emulator=expected)
    return 0


def main():
    native()
    openwrt()
    emulation()
    print('speed/retention: sparse tree preservation, two publications across versions, legacy removal, independent files, indices, retired, targeted emulation passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
