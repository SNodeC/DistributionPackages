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
    def test_receipt_requires_upstream_workflow_capture_and_attempt(self):
        target = publication.targets()[0]['id']
        payload = dict(project='snode.c', target=target, capture='456', run='456', attempt='1')
        origin = dict(event='push', head_branch='v2.0.0', path='.github/workflows/packages.yml',
                      head_repository={'full_name': 'SNodeC/snode.c'}, run_attempt=2,
                      display_title='Packages · 456 · -', html_url='https://example.invalid/456')
        with patch.object(dispatch, 'api', return_value=origin):
            result = dispatch.receive(payload)
            # A retry of another matrix job must not invalidate this successful attempt's artifact.
            self.assertEqual(result['artifact'], f'packages-snode.c-{target}-1')
            self.assertEqual(result['attempt'], '1')
            self.assertEqual(result['capture_repository'], 'SNodeC/snode.c')
        for changes in [dict(event='pull_request'), dict(path='.github/workflows/untrusted.yml'),
                        dict(head_repository={'full_name': 'other/fork'}), dict(run_attempt=0),
                        dict(display_title='Packages · 999 · -'), dict(head_branch='master'), dict(event='repository_dispatch')]:
            with self.subTest(changes=changes), patch.object(dispatch, 'api', return_value=origin | changes):
                with self.assertRaises(ValueError):
                    dispatch.receive(payload)

    def test_receipt_locates_capture_for_application_tag_and_dependency_build(self):
        target = publication.targets()[0]['id']
        payload = dict(project='mqttsuite', target=target, capture='123', run='123', attempt='1')
        origin = dict(event='push', head_branch='v1.0.2', path='.github/workflows/packages.yml',
                      head_repository={'full_name': 'SNodeC/mqttsuite'}, run_attempt=1,
                      display_title='Packages · 123 · -', html_url='https://example.invalid/123')
        with patch.object(dispatch, 'api', return_value=origin):
            self.assertEqual(dispatch.receive(payload)['capture_repository'], 'SNodeC/mqttsuite')
            with self.assertRaises(ValueError):
                dispatch.receive(payload | {'capture': '999'})
        origin.update(event='repository_dispatch', display_title=f'Packages · 123 · {target}')
        with patch.object(dispatch, 'api', return_value=origin):
            self.assertEqual(dispatch.receive(payload | {'run': '456'})['capture_repository'], 'SNodeC/snode.c')

    def test_source_plan_selects_full_release_or_single_dependent_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            rows = publication.targets()[:2]
            publication.write(bundle / 'targets.json', rows)
            publication.write(bundle / 'revisions.json', {'snode.c': '1', 'mqttsuite': '2'})
            for project in ['snode.c', 'mqttsuite']:
                publication.write(bundle / 'context.json', dict(run_id='123', release_project=project))
                env = os.environ | {'PYTHONPATH': str(repository.ROOT), 'CAPTURE_RUN': '123'}
                result = subprocess.run(['python3', '-m', 'ci.dispatch', 'plan', str(bundle), project, '-'],
                                        env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout.splitlines()[0].split('=', 1)[1])['include'], rows)
            publication.write(bundle / 'context.json', dict(run_id='123', release_project='snode.c'))
            command = ['python3', '-m', 'ci.dispatch', 'plan', str(bundle), 'mqttsuite', rows[0]['id']]
            result = subprocess.run(command, env=env | {'PUBLISHED_REF': 'a' * 40}, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout.splitlines()[0].split('=', 1)[1])['include'], rows[:1])
            for overrides in [{'CAPTURE_RUN': '999', 'PUBLISHED_REF': 'a' * 40}, {'PUBLISHED_REF': 'main'}]:
                result = subprocess.run(command, env=env | overrides, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)

    def test_dispatch_retry_reuses_existing_run_and_keeps_exact_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            publication.write(bundle / 'context.json', dict(run_id='123', captured_at='2026-10-10T00:00:00Z'))
            target = publication.targets()[0]['id']
            with patch.object(dispatch, 'run', return_value='[{"workflow_runs": []}]'), patch.object(dispatch, 'api') as send:
                dispatch.build(bundle, 'mqttsuite', target, 'a' * 40)
                self.assertEqual(send.call_args.args[0], 'repos/SNodeC/mqttsuite/dispatches')
                self.assertEqual(send.call_args.args[1]['client_payload'], dict(capture='123', target=target, publication='a' * 40))
            existing = json.dumps([dict(workflow_runs=[dict(display_title=f'Packages · 123 · {target}')])])
            with patch.object(dispatch, 'run', return_value=existing), patch.object(dispatch, 'api') as send:
                dispatch.build(bundle, 'mqttsuite', target, 'a' * 40)
                send.assert_not_called()

    def test_application_selects_dispatched_signed_dependency_not_main(self):
        row = next(row for row in publication.targets() if row['distribution'] == 'debian')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / 'bundle'
            sources = {'snode.c': {'refs/tags/v2.0.0': 'commit'}}
            publication.write(bundle / 'context.json', dict(run_id='123'))
            publication.write(bundle / 'revisions.json', {'snode.c': '5', 'mqttsuite': '7'})
            publication.write(bundle / 'profiles.json', {row['id']: dict(sources=sources, directory='debian/dists/trixie')})
            info = dict(context=dict(run_id='123', build_project='snode.c'), sources=sources, revision='5')
            with patch.object(dispatch, 'Path', side_effect=lambda path: root / path), patch.object(repository, 'fetch', return_value=json.dumps(dict(targets={row['arch']: info})).encode()) as fetch:
                dispatch.baseline(bundle, row['id'], 'a' * 40)
                self.assertIn('/' + 'a' * 40 + '/', fetch.call_args.args[0])
                self.assertEqual(publication.read(root / 'published-snodec/build.json'), info)
            with patch.object(repository, 'fetch', return_value=json.dumps(info | {'revision': '6'}).encode()):
                with self.assertRaisesRegex(ValueError, 'corresponding'):
                    dispatch.baseline(bundle, row['id'], 'b' * 40)

    def test_signed_publication_retry_compares_original_unsigned_bytes(self):
        incoming = dict(context=dict(build_project='snode.c'), sources={}, revision='1', files={'package.rpm': 'unsigned'})
        published = incoming | dict(unsigned_files=incoming['files'], files={'package.rpm': 'signed'})
        self.assertFalse(repository.publication_needed(published, incoming))
        with self.assertRaisesRegex(RuntimeError, 'Different package content'):
            repository.publication_needed(published, incoming | {'files': {'package.rpm': 'changed'}})

    def test_source_finalize_preserves_handoffs_and_skips_failed_dependents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, bundle = Path(temporary) / 'root', Path(temporary) / 'bundle'
            rows = publication.targets()[:3]
            context = dict(run_id='123', run_url='url', destination='SNodeC/Packages', release_project='snode.c')
            for name, value in dict(context=context, targets=rows, revisions={'snode.c': '1', 'mqttsuite': '1'}, profiles={}, sources={}).items():
                publication.write(bundle / (name + '.json'), value)
            state = dict(repository='SNodeC/Packages', branch='main', targets={}, runs={})
            generation = publication.record_run(bundle, state, context)
            for row, status in zip(rows, ['running', 'publishing', 'published']):
                publication.event(state, generation, row, 'snode.c', status, 1)
                publication.event(state, generation, row, 'mqttsuite', 'pending', 0)
            publication.write(root / 'status.json', state)
            with patch.dict(os.environ, {'BUILD_PROJECT': 'snode.c', 'TARGET_ID': '-', 'GITHUB_RUN_ATTEMPT': '1'}), patch('sys.argv', ['publication', 'finalize', str(root), str(bundle), 'cancelled']):
                publication.main()
            values = publication.read(root / 'status.json')['targets']
            self.assertEqual(values[rows[0]['id'] + '/snode.c']['status'], 'cancelled')
            self.assertEqual(values[rows[0]['id'] + '/mqttsuite']['status'], 'skipped')
            for row in rows[1:]:
                self.assertEqual(values[row['id'] + '/mqttsuite']['status'], 'pending')
            self.assertEqual(values[rows[1]['id'] + '/snode.c']['status'], 'publishing')
            # A dependent workflow cancelled before acquiring its slot still owns its pending target.
            with patch.dict(os.environ, {'BUILD_PROJECT': 'mqttsuite', 'TARGET_ID': rows[1]['id'], 'GITHUB_RUN_ATTEMPT': '1'}), patch('sys.argv', ['publication', 'finalize', str(root), str(bundle), 'cancelled']):
                publication.main()
            values = publication.read(root / 'status.json')['targets']
            self.assertEqual(values[rows[1]['id'] + '/mqttsuite']['status'], 'cancelled')
            self.assertEqual(values[rows[2]['id'] + '/mqttsuite']['status'], 'pending')

    def test_dependency_retry_does_not_consume_application_attempt_numbers(self):
        row = publication.targets()[0]
        generation = dict(revisions={'snode.c': '1', 'mqttsuite': '1'}, run_id='capture', run_url='url',
                          targets=[row], context={'release_project': 'snode.c'})
        state = {'targets': {}}
        publication.event(state, generation, row, 'mqttsuite', 'pending', 0)
        publication.event(state, generation, row, 'snode.c', 'failed', 1)
        publication.event(state, generation, row, 'snode.c', 'failed', 2)
        self.assertEqual(state['targets'][row['id'] + '/mqttsuite']['status'], 'skipped')
        publication.event(state, generation, row, 'snode.c', 'published', 3)
        publication.event(state, generation, row, 'mqttsuite', 'running', 1)
        self.assertEqual(state['targets'][row['id'] + '/mqttsuite']['status'], 'running')
        publication.event(state, generation, row, 'mqttsuite', 'failed', 1)
        publication.event(state, generation, row, 'mqttsuite', 'running', 2)
        self.assertEqual(state['targets'][row['id'] + '/mqttsuite']['attempt'], 2)

    def test_publisher_retry_of_committed_artifact_does_not_touch_feeds(self):
        from contextlib import redirect_stdout
        from io import StringIO
        with tempfile.TemporaryDirectory() as temporary:
            root, bundle = Path(temporary) / 'root', Path(temporary) / 'bundle'
            row = publication.targets()[0]
            context = dict(run_id='123', run_url='capture-url', destination='SNodeC/Packages', release_project='snode.c')
            for name, value in dict(context=context, targets=[row], revisions={'snode.c': '1', 'mqttsuite': '1'}, profiles={}, sources={}).items():
                publication.write(bundle / (name + '.json'), value)
            state = dict(repository='SNodeC/Packages', branch='main', targets={}, runs={})
            generation = publication.record_run(bundle, state, context)
            publication.update(state, row, generation, 'snode.c', 'published', 2, 'source-build-url')
            publication.write(root / 'status.json', state)
            before = (root / 'status.json').read_bytes()
            env = {'BUILD_ATTEMPT': '2', 'GITHUB_RUN_ATTEMPT': '7', 'BUILD_RUN_URL': 'source-build-url'}
            with patch.dict(os.environ, env), patch.object(publication, 'publish') as publish, patch('sys.argv',
                    ['publication', 'feed', str(root), str(bundle), json.dumps(row), 'snode.c', 'unused']), redirect_stdout(StringIO()) as output:
                self.assertEqual(publication.main(), 0)
                publish.assert_not_called()
                self.assertEqual(output.getvalue(), 'published\n')
            self.assertEqual((root / 'status.json').read_bytes(), before)


@unittest.skipUnless(shutil.which('usign') and shutil.which('apk'), 'OpenWrt signing tools not on PATH')
class OpenWrtSigningTest(unittest.TestCase):
    def test_real_ipk_and_apk_index_signatures_and_final_checksums(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            keys = root / 'keys'
            keys.mkdir()
            private = root / 'private'
            private.mkdir()
            repository.run('usign', '-G', '-s', str(private / 'usign'), '-p', str(keys / 'snodec-usign.pub'))
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
