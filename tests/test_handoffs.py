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
    def test_receipt_requires_coordinator_and_upstream_build_identity(self):
        target = publication.targets()[0]['id']
        payload = dict(project='snode.c', target=target, capture='123', run='456', attempt='1')
        capture = dict(event='repository_dispatch', path='.github/workflows/orchestrate-packages.yml',
                       head_repository={'full_name': dispatch.COORDINATOR})
        origin = dict(event='repository_dispatch', path='.github/workflows/build-distribution-packages.yml',
                      head_repository={'full_name': 'SNodeC/snode.c'}, run_attempt=2,
                      display_title='Packages · 123 · -', html_url='https://example.invalid/456')
        with patch.object(dispatch, 'api', side_effect=[capture, origin]):
            result = dispatch.receive(payload)
            self.assertEqual(result['artifact'], f'packages-snode.c-{target}-1')
            self.assertEqual(result['capture_repository'], dispatch.COORDINATOR)
        for changes in [dict(event='push'), dict(event='pull_request'), dict(path='.github/workflows/untrusted.yml'),
                        dict(head_repository={'full_name': 'other/fork'}), dict(run_attempt=0),
                        dict(display_title='Packages · 999 · -')]:
            with self.subTest(changes=changes), patch.object(dispatch, 'api', side_effect=[capture, origin | changes]):
                with self.assertRaises(ValueError):
                    dispatch.receive(payload)
        for changes in [dict(event='push'), dict(path='.github/workflows/untrusted.yml'),
                        dict(head_repository={'full_name': 'SNodeC/snode.c'})]:
            with self.subTest(capture=changes), patch.object(dispatch, 'api', return_value=capture | changes):
                with self.assertRaises(ValueError):
                    dispatch.receive(payload)

    def test_release_intake_matches_tag_commit_repository_and_workflow(self):
        payload = dict(project='mqttsuite', tag='v1.2.3', sha='a' * 40, run='123')
        origin = dict(event='push', path='.github/workflows/build-distribution-packages.yml',
                      head_repository={'full_name': 'SNodeC/mqttsuite'}, head_branch='v1.2.3', head_sha='a' * 40)
        with patch.object(dispatch, 'api', return_value=origin), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(dispatch.intake(payload)['sha'], 'a' * 40)
            for changes in [dict(project='unknown'), dict(tag='main'), dict(tag='v01.2.3'),
                            dict(tag='v1.2.3;touch injected'), dict(sha='main'), dict(run='../123')]:
                with self.subTest(payload=changes), self.assertRaises(ValueError):
                    dispatch.intake(payload | changes)
        for changes in [dict(event='pull_request'), dict(head_branch='main'), dict(head_sha='b' * 40),
                        dict(path='.github/workflows/other.yml'), dict(head_repository={'full_name': 'other/fork'})]:
            with self.subTest(origin=changes), patch.object(dispatch, 'api', return_value=origin | changes):
                with self.assertRaises(ValueError):
                    dispatch.intake(payload)
        for current, expected in [('200', True), ('100', False)]:
            pages = json.dumps([dict(workflow_runs=[dict(id=100, display_title='Release · mqttsuite · v1.2.3 · 123')])])
            with patch.object(dispatch, 'api', return_value=origin), patch.object(dispatch, 'run', return_value=pages), \
                 patch.dict(os.environ, {'GITHUB_RUN_ID': current}):
                self.assertEqual(dispatch.intake(payload)['duplicate'], str(expected).lower())

    def test_plan_selects_release_or_single_target_from_coordinator_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            rows = publication.targets()[:2]
            publication.write(bundle / 'targets.json', rows)
            publication.write(bundle / 'revisions.json', {'snode.c': '1', 'mqttsuite': '2'})
            publication.write(bundle / 'context.json', dict(run_id='123', release_project='snode.c'))
            with patch.dict(os.environ, {'CAPTURE_RUN': '123', 'PUBLISHED_REF': 'a' * 40}):
                self.assertEqual(json.loads(dispatch.plan(bundle, 'snode.c', '-')['matrix'])['include'], rows)
                self.assertEqual(json.loads(dispatch.plan(bundle, 'mqttsuite', rows[0]['id'])['matrix'])['include'], rows[:1])
                for project, target in [('mqttsuite', '-'), ('unknown', '-'), ('snode.c', 'unknown')]:
                    with self.subTest(project=project, target=target), self.assertRaises(ValueError):
                        dispatch.plan(bundle, project, target)
            for overrides in [{'CAPTURE_RUN': '999', 'PUBLISHED_REF': 'a' * 40}, {'CAPTURE_RUN': '123', 'PUBLISHED_REF': 'main'}]:
                with patch.dict(os.environ, overrides), self.assertRaises(ValueError):
                    dispatch.plan(bundle, 'snode.c', '-')

    def test_dispatch_retry_reuses_existing_run_and_keeps_exact_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            rows = publication.targets()[:1]
            publication.write(bundle / 'context.json', dict(run_id='123', captured_at='2026-10-10T00:00:00Z', release_project='snode.c'))
            publication.write(bundle / 'targets.json', rows)
            publication.write(bundle / 'revisions.json', {'snode.c': '1', 'mqttsuite': '2'})
            target = rows[0]['id']
            with patch.object(dispatch, 'run', return_value='[{"workflow_runs": []}]'), patch.object(dispatch, 'api') as send:
                dispatch.build(bundle, 'mqttsuite', target, 'a' * 40)
                self.assertEqual(send.call_args.args[0], 'repos/SNodeC/mqttsuite/dispatches')
                self.assertEqual(send.call_args.args[1]['event_type'], 'build-packages')
                self.assertEqual(send.call_args.args[1]['client_payload'], dict(capture='123', target=target, publication='a' * 40))
                dispatch.build(bundle, 'snode.c', '-', 'b' * 40)
                self.assertEqual(send.call_args.args[1]['client_payload']['target'], '-')
            existing = json.dumps([dict(workflow_runs=[dict(display_title=f'Packages · 123 · {target}', path='.github/workflows/build-distribution-packages.yml')])])
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

    def test_coordinator_retry_preserves_build_attempts_and_target_status_scope(self):
        rows = publication.targets()[:3]
        for owner, target in [('mqttsuite', rows[0]), ('snode.c', None), ('mqttsuite', None)]:
            with self.subTest(owner=owner, dependent=target is not None), tempfile.TemporaryDirectory() as temporary:
                root, bundle = Path(temporary) / 'root', Path(temporary) / 'bundle'
                release = 'snode.c' if target or owner == 'snode.c' else 'mqttsuite'
                revisions = {'snode.c': '15', 'mqttsuite': '15'} if release == 'snode.c' else {'mqttsuite': '15'}
                context = dict(run_id='capture', run_url='capture-url', destination='SNodeC/Packages', release_project=release)
                for name, value in dict(context=context, targets=rows, revisions=revisions, profiles={}, sources={}).items():
                    publication.write(bundle / (name + '.json'), value)
                state = dict(repository='SNodeC/Packages', branch='main', targets={}, runs={})
                generation = publication.record_run(bundle, state, context)
                for row in rows:
                    for project in revisions:
                        publication.update(state, row, generation, project, 'published', 1, f'{project}/{row["id"]}')
                before = json.loads(json.dumps(state))
                publication.write(root / 'status.json', state)
                args = [json.dumps(target), owner] if target else ['-', '-']
                env = {'BUILD_PROJECT': owner, 'TARGET_ID': target['id'] if target else '-',
                       'GITHUB_RUN_ATTEMPT': '2', 'BUILD_RUN_URL': 'retry-job', 'BUILD_ATTEMPT': ''}
                with patch.dict(os.environ, env), patch.object(publication, 'render'), patch('sys.argv',
                        ['publication', 'status', str(root), str(bundle), *args, 'pending']):
                    publication.main()
                after = publication.read(root / 'status.json')
                self.assertEqual(after['runs'], before['runs'])
                for row in rows:
                    for project in revisions:
                        key = f'{row["id"]}/{project}'
                        if project == owner and target is not None and row == target:
                            self.assertEqual(after['targets'][key]['status'], 'pending')
                            self.assertEqual(after['targets'][key]['attempt'], 2)
                            self.assertEqual(after['targets'][key]['job_url'], 'retry-job')
                        else:
                            self.assertEqual(after['targets'][key], before['targets'][key])
                            self.assertEqual(after['timeline'][key], before['timeline'][key])

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


class JobIdentityTest(unittest.TestCase):
    def setUp(self):
        self.row = publication.targets()[0]
        self.payload = dict(project='snode.c', target=self.row['id'], capture='456', run='456', attempt='1', job='789')
        self.origin = dict(event='repository_dispatch', head_branch='v2.0.0', path='.github/workflows/build-distribution-packages.yml',
                           head_repository={'full_name': 'SNodeC/snode.c'}, run_attempt=2,
                           display_title='Packages · 456 · -', html_url='https://example.invalid/run')
        self.capture = dict(event='repository_dispatch', path='.github/workflows/orchestrate-packages.yml',
                            head_repository={'full_name': dispatch.COORDINATOR})
        self.job = dict(run_id=456, run_attempt=1, html_url='https://example.invalid/job',
                        name=f"{self.row['distribution']} · {self.row['suite']} · {self.row['arch']}")

    def test_job_url_requires_exact_repository_run_attempt_and_target(self):
        with patch.object(dispatch, 'api', side_effect=[self.capture, self.origin, self.job]) as api:
            self.assertEqual(dispatch.receive(self.payload)['run_url'], self.job['html_url'])
            self.assertEqual(api.call_args.args, ('repos/SNodeC/snode.c/actions/jobs/789',))
        for changes in [dict(run_id=999), dict(run_attempt=2), dict(name='prepare'), dict(name='Build and test · ' + self.job['name'])]:
            with self.subTest(changes=changes), patch.object(dispatch, 'api', side_effect=[self.capture, self.origin, self.job | changes]):
                with self.assertRaises(ValueError):
                    dispatch.receive(self.payload)
        for job in ['0', '-1', '../789', '']:
            with self.subTest(job=job), patch.object(dispatch, 'api', side_effect=[self.capture, self.origin]):
                with self.assertRaises(ValueError):
                    dispatch.receive(self.payload | {'job': job})

    def test_finalizer_preserves_run_url_without_job_api(self):
        with patch.object(dispatch, 'api', side_effect=[self.capture, self.origin]) as api:
            self.assertEqual(dispatch.receive({key: value for key, value in self.payload.items() if key != 'job'})['run_url'], self.origin['html_url'])
            self.assertEqual(api.call_count, 2)

    def test_built_payload_carries_job_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            publication.write(bundle / 'context.json', {'run_id': '456'})
            env = {'GITHUB_RUN_ID': '456', 'GITHUB_RUN_ATTEMPT': '1', 'BUILD_JOB_ID': '789'}
            with patch.dict(os.environ, env), patch('sys.argv', ['dispatch', 'built', str(bundle), self.row['id'], 'snode.c']):
                import runpy
                with patch('ci.repository.run', return_value='') as run:
                    # Exercise the public command; its API call is serialized through the shared runner.
                    runpy.run_path(str(repository.ROOT / 'ci/dispatch.py'), run_name='__main__')
                    args = run.call_args.kwargs['input']
            payload = json.loads(args)
            self.assertEqual(payload['client_payload']['job'], '789')
