"""Cross-repository boundaries and signing, without GitHub writes or production keys."""
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ci import dispatch, repository
from ci.publish import publication, openwrt


class HandoffTest(unittest.TestCase):
    def test_application_selects_dispatched_signed_dependency_not_main(self):
        row = next(row for row in publication.targets() if row['distribution'] == 'debian')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / 'bundle'
            sources = {'snode.c': {'refs/tags/v2.0.0': 'commit'}}
            publication.write(bundle / 'context.json', dict(run_id='123'))
            publication.write(bundle / 'targets.json', [row])
            publication.write(bundle / 'revisions.json', {'snode.c': '5', 'mqttsuite': '7'})
            publication.write(bundle / 'profiles.json', {row['id']: dict(sources=sources, baseline={}, directory='debian/dists/trixie')})
            info = dict(context=dict(run_id='123', build_project='snode.c'), sources=sources, revision='5')
            with patch.dict(os.environ, {'BUILD_PROJECT': 'mqttsuite'}), \
                 patch.object(dispatch, 'Path', side_effect=lambda path: root / path), \
                 patch.object(repository, 'fetch', return_value=json.dumps(dict(targets={row['arch']: info})).encode()) as fetch:
                dispatch.baseline(bundle, row['id'], 'a' * 40)
                self.assertIn('/' + 'a' * 40 + '/', fetch.call_args.args[0])
                self.assertEqual(publication.read(root / 'published-snodec/build.json'), info)
            with patch.dict(os.environ, {'BUILD_PROJECT': 'mqttsuite'}), patch.object(repository, 'fetch', return_value=json.dumps(info | {'revision': '6'}).encode()):
                with self.assertRaisesRegex(ValueError, 'corresponding'):
                    dispatch.baseline(bundle, row['id'], 'b' * 40)

    def test_signed_publication_retry_compares_original_unsigned_bytes(self):
        incoming = dict(context=dict(build_project='snode.c'), sources={}, revision='1', files={'package.rpm': 'unsigned'})
        published = incoming | dict(unsigned_files=incoming['files'], files={'package.rpm': 'signed'})
        self.assertFalse(repository.publication_needed(published, incoming))
        with self.assertRaisesRegex(RuntimeError, 'Different package content'):
            repository.publication_needed(published, incoming | {'files': {'package.rpm': 'changed'}})


@unittest.skipUnless(shutil.which('usign') and shutil.which('apk'), 'OpenWrt signing tools not on PATH')
class OpenWrtSigningTest(unittest.TestCase):
    def test_real_ipk_and_apk_index_signatures_and_final_checksums(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            keys = root / 'keys'
            keys.mkdir()
            private = root / 'private'
            private.mkdir()
            repository.run('usign', '-G', '-s', str(private / 'usign'), '-p', str(keys / 'snodec-opkg.pub'))
            repository.run('openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', str(private / 'apk'), stderr=subprocess.DEVNULL)
            repository.run('openssl', 'pkey', '-in', str(private / 'apk'), '-pubout', '-out', str(keys / 'snodec-apk.pem'))
            env = {'OPENWRT_USIGN_KEY': (private / 'usign').read_text(), 'OPENWRT_APK_KEY': (private / 'apk').read_text()}
            for series in ['24.10', '25.12']:
                with self.subTest(series=series):
                    feed = root / series
                    feed.mkdir()
                    if series == '24.10':
                        (feed / 'Packages').write_text('Package: test\nVersion: 1\n\n')
                    else:
                        payload = root / 'payload'
                        payload.mkdir()
                        (payload / 'test').write_text('test package')
                        repository.run('apk', 'mkpkg', '--info', 'name:test', '--info', 'version:1-r1', '--info', 'arch:x86_64', '--files', str(payload), '--output', str(feed / 'test.apk'))
                        repository.run('apk', 'mkndx', '--allow-untrusted', '--output', str(feed / 'packages.adb'), str(feed / 'test.apk'))
                    before = {path.name: repository.digest(path) for path in feed.iterdir()}
                    info = dict(series=series, files=before.copy())
                    with patch.object(openwrt, 'ROOT', root), patch.dict(os.environ, env):
                        openwrt.sign(feed, info)
                    self.assertEqual(info['unsigned_files'], before)
                    self.assertTrue(all(repository.digest(feed / name) == checksum for name, checksum in info['files'].items()))
                    self.assertEqual(publication.read(feed / 'build.json'), info)
                    self.assertNotEqual(info['files'], before)
                    if series == '25.12':
                        self.assertEqual(info['files']['test.apk'], before['test.apk'])


@unittest.skipUnless(all(shutil.which(tool) for tool in ['rpmbuild', 'rpmsign', 'createrepo_c', 'gpg']), 'RPM signing tools not on PATH')
class RpmSigningTest(unittest.TestCase):
    def test_build_stage_is_unsigned_and_publisher_signs_once(self):
        rpm = importlib.import_module('ci.publish.rpm')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec = root / 'fixture.spec'
            spec.write_text('''Name: snodec
Version: 2.0.0
Release: 1.el10
Summary: Signing fixture
License: MIT
BuildArch: x86_64
%description
Signing fixture.
%install
mkdir -p %{buildroot}/usr/share/snodec-fixture
printf fixture > %{buildroot}/usr/share/snodec-fixture/data
%files
/usr/share/snodec-fixture/data
''')
            repository.run('rpmbuild', '--define', f'_topdir {root}', '-bb', str(spec), stderr=subprocess.DEVNULL)
            packages = root / 'RPMS/x86_64'
            (packages / 'snodec.packages').write_text('snodec\n')
            bundle, output, checkout = root / 'bundle', root / 'output', root / 'checkout'
            row = next(row for row in repository.linux_matrix() if row['distribution'] == 'rocky' and row['suite'] == '10' and row['arch'] == 'x86_64')
            publication.write(bundle / 'sources.json', {})
            publication.write(bundle / 'context.json', dict(build_project='snode.c'))
            # stage must succeed with no private key or signer available.
            with patch.object(rpm, 'unchanged'), patch.dict(os.environ, {'PACKAGE_RELEASE': '1'}), patch.object(rpm, 'signer', side_effect=AssertionError('build must not sign')):
                rpm.stage(row, packages, bundle, output)
            manifest = output / 'rocky/10/x86_64/build.json'
            unsigned = publication.read(manifest)
            self.assertFalse((manifest.parent / 'repodata').exists())
            home, keys = root / 'gnupg', root / 'keys'
            home.mkdir(mode=0o700)
            keys.mkdir()
            repository.run('gpg', '--homedir', str(home), '--batch', '--pinentry-mode', 'loopback', '--passphrase', '', '--quick-generate-key', 'Package test <test@example.invalid>', 'rsa2048', 'sign', '1d', stderr=subprocess.DEVNULL)
            key = repository.run('gpg', '--homedir', str(home), '--batch', '--armor', '--export-secret-keys')
            (keys / 'snodec-apt.asc').write_text(repository.run('gpg', '--homedir', str(home), '--batch', '--armor', '--export'))
            with patch.object(rpm, 'unchanged'), patch.object(rpm, 'ROOT', root), patch.dict(os.environ, {'APT_SIGNING_KEY': key}):
                rpm.publish([row], output, checkout, bundle)
            final = publication.read(checkout / 'rocky/10/x86_64/build.json')
            self.assertEqual(final['unsigned_files'], unsigned['files'])
            self.assertNotEqual(final['files']['Packages/snodec-2.0.0-1.el10.x86_64.rpm'], unsigned['files']['Packages/snodec-2.0.0-1.el10.x86_64.rpm'])
            # Restore the original uploaded artifact. A publisher retry must not sign again.
            shutil.rmtree(output)
            with patch.object(rpm, 'unchanged'), patch.dict(os.environ, {'PACKAGE_RELEASE': '1'}):
                rpm.stage(row, packages, bundle, output)
                with patch.object(rpm, 'signer', side_effect=AssertionError('retry must not sign twice')):
                    rpm.publish([row], output, checkout, bundle)
            self.assertEqual(publication.read(checkout / 'rocky/10/x86_64/build.json'), final)
