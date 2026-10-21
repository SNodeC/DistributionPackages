"""Cross-repository boundaries and signing, without GitHub writes or production keys."""
import copy
from support import CoordinatorCase
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from support import PinnedJsonCase
from unittest.mock import patch

from ci import dispatch, repository
from ci.publish import publication, openwrt


class HandoffTest(CoordinatorCase):
    def setUp(self):
        super().setUp()
        self.tick()
        node = self.finish()
        self.payload = node['request'] | dict(run=node['source']['run'],attempt=1,job=node['source']['run']+1000,
                    artifact=self.artifacts['SNodeC/snode.c',node['source']['run']][0] | {},status='publishing')
        self.payload['artifact'] = {k:self.payload['artifact'][k] for k in ['id','digest']}
        return None

    def test_receipt_requires_coordinator_and_upstream_build_identity(self):
        result = dispatch.receive(self.payload,self.bundle)
        self.assertEqual(result['artifact_id'],1234)
        receipt=json.loads(result['receipt'])
        self.assertEqual(receipt['source'],dict(run=501,attempt=1))
        self.assertEqual(receipt['job_url'],self.jobs['SNodeC/snode.c',501][0]['html_url'])
        for changes in [dict(event='push'),dict(event='pull_request'),dict(path='.github/workflows/other.yml'),dict(head_repository={'full_name':'someone/fork'}),dict(actor={'login':'other'})]:
            original=copy.deepcopy(self.runs['SNodeC/snode.c',501])
            self.runs['SNodeC/snode.c',501].update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                dispatch.receive(self.payload,self.bundle)
            self.runs['SNodeC/snode.c',501]=original
        return None

    def test_release_intake_matches_tag_commit_repository_and_workflow(self):
        payload=dict(project='snode.c',tag='v1.0.0',sha='a'*40,run='99',definition='{}')
        origin=dict(event='push',path='.github/workflows/build-distribution-packages.yml',head_repository={'full_name':'SNodeC/snode.c'},head_branch='v1.0.0',head_sha='a'*40,created_at='2026-10-20T00:00:00Z')
        with patch.object(dispatch,'api',return_value=origin),patch.object(dispatch,'configure') as configure,patch.dict(os.environ,{'GITHUB_RUN_ID':''}):
            self.assertEqual(dispatch.intake(payload)['sha'],'a'*40)
            configure.assert_called_once()
            for changes in [dict(project='unknown'),dict(tag='v01.2.3'),dict(tag='v1.2.3;touch injected'),dict(sha='main'),dict(run='../123')]:
                with self.subTest(payload=changes), self.assertRaises(ValueError):
                    dispatch.intake(payload | changes)
            for changes in [dict(event='pull_request'),dict(head_sha='b'*40),dict(head_branch='master'),dict(path='other.yml'),dict(head_repository={'full_name':'other/fork'})]:
                with patch.object(dispatch,'api',return_value=origin|changes),self.subTest(changes=changes),self.assertRaises(ValueError):
                    dispatch.intake(payload)
        return None

    def test_intake_deduplicates_validated_ledger_requests_not_failed_workflow_titles(self):
        payload=dict(project='snode.c',tag='v1.0.0',sha='a'*40,run='99',definition='{}')
        origin=dict(event='push',path='.github/workflows/build-distribution-packages.yml',head_repository={'full_name':'SNodeC/snode.c'},head_branch='v1.0.0',head_sha='a'*40,created_at='2026-10-20T00:00:00Z')
        state=self.base/'published/status.json'
        before=os.getcwd()
        try:
            os.chdir(self.base)
            with patch.object(dispatch,'api',return_value=origin),patch.object(dispatch,'configure'),patch.object(dispatch,'run',side_effect=AssertionError('A failed/unverified workflow title is not admission state')),patch.dict(os.environ,GITHUB_RUN_ID='101'):
                self.assertEqual(dispatch.intake(payload)['duplicate'],'false')
                publication.write(state,dict(requests={'snode.c':dict(run='99',capture='100',at=origin['created_at'])}))
                self.assertEqual(dispatch.intake(payload)['duplicate'],'true')
                with patch.dict(os.environ,GITHUB_RUN_ID='100'):
                    self.assertEqual(dispatch.intake(payload)['duplicate'],'false')
        finally:
            os.chdir(before)
        return None

    def test_plan_selects_only_the_admitted_captured_target(self):
        publication.write(self.bundle/'context.json',self.context)
        env=dict(PACKAGE_REQUEST=json.dumps(self.payload),BUILD_PROJECT='snode.c',GITHUB_OUTPUT=str(self.base/'outputs'))
        with patch.dict(os.environ,env),patch('sys.argv',['dispatch','authorize',str(self.bundle)]):
            dispatch.main()
        self.assertIn(self.row['id'],(self.base/'outputs').read_text())
        with patch.dict(os.environ,env|dict(BUILD_PROJECT='mqttsuite')),patch('sys.argv',['dispatch','authorize',str(self.bundle)]),self.assertRaises(ValueError):
            dispatch.main()
        return None

    def test_dispatch_retry_reuses_existing_run_and_keeps_exact_publication(self):
        self.tick()
        self.assertEqual(len(self.posts),2)
        publication_request=json.loads(self.posts[-1][1]['inputs']['request'])
        self.assertEqual(publication_request['publication'],self.payload['publication'])
        self.tick()
        self.assertEqual(len(self.posts),2)
        return None

    def test_application_selects_dispatched_signed_dependency_not_main(self):
        info=dict(sources={'snode.c':self.sources['snode.c']},versions={'snodec':'1.0.0-2~trixie'})
        with patch.object(repository,'definition',side_effect=lambda p,c:self.graph[p]|dict(_commit=c)),patch.object(repository,'fetch',return_value=json.dumps({'targets':{'amd64':info}})) as fetch,patch.dict(os.environ,BUILD_PROJECT='mqttsuite'),patch('pathlib.Path.cwd',return_value=self.base):
            before=os.getcwd()
            try:
                os.chdir(self.base)
                dispatch.baseline(self.bundle,self.row['id'],'b'*40)
            finally:
                os.chdir(before)
        self.assertIn('/'+'b'*40+'/',fetch.call_args.args[0])
        self.assertNotIn('/main/',fetch.call_args.args[0])
        return None

    def test_baseline_requires_a_corresponding_published_target(self):
        with patch.object(repository, 'fetch', return_value=json.dumps({'targets':{'arm64':{'sources':self.sources}}})), patch.dict(os.environ, BUILD_PROJECT='mqttsuite'):
            with self.assertRaisesRegex(ValueError, 'Missing published prerequisite'):
                dispatch.baseline(self.bundle, self.row['id'], 'b'*40)
        return None

    def test_source_finalize_preserves_successful_handoff_despite_cleanup_failure(self):
        self.runs['SNodeC/snode.c',501].update(conclusion='failure')
        dispatch.apply_report(self.root,self.payload,self.bundle)
        late=self.payload|dict(status='failed')
        late.pop('artifact')
        dispatch.apply_report(self.root,late,self.bundle)
        self.assertEqual(self.node()['status'],'publishing')
        self.assertEqual(self.node()['artifact']['id'],1234)
        return None

    def test_coordinator_retry_preserves_build_attempts_and_target_status_scope(self):
        before = copy.deepcopy(self.node('mqttsuite'))
        dispatch.apply_report(self.root,self.payload,self.bundle)
        dispatch.apply_report(self.root,self.payload,self.bundle)
        self.assertEqual(self.node()['source']['attempt'],1)
        self.assertEqual(self.node('mqttsuite')['attempt'],0)
        self.assertEqual(self.node('mqttsuite'), before)
        return None

    def test_dependency_retry_does_not_consume_application_attempt_numbers(self):
        generation=self.state['runs']['100']
        state=copy.deepcopy(self.state)
        publication.update(state, self.row, generation,'mqttsuite','pending',0)
        publication.update(state, self.row, generation,'snode.c','failed',2)
        publication.update(state, self.row, generation,'mqttsuite','running',1)
        self.assertEqual(publication.projection(state)['targets'][self.row['id']+'/mqttsuite']['attempt'],1)
        return None

    def test_job_url_requires_exact_repository_run_attempt_and_target(self):
        job=self.jobs['SNodeC/snode.c',501][0]
        for changes in [dict(run_id=999),dict(run_attempt=2),dict(name='other-target')]:
            original=copy.deepcopy(job)
            job.update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                dispatch.receive(self.payload,self.bundle)
            job.clear();job.update(original)
        return None

    def test_canonical_ids_artifact_binding_and_capture_are_enforced(self):
        for change in [dict(run='0'),dict(attempt='00'),dict(job='-1'),dict(capture='999'),dict(artifact={'id':1234,'digest':'sha256:'+'0'*64}),dict(status='invented')]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                dispatch.receive(self.payload|change,self.bundle)
        self.runs[dispatch.COORDINATOR,100]['event']='push'
        with self.assertRaises(ValueError):
            dispatch.receive(self.payload,self.bundle)
        return None

    def test_built_payload_carries_real_job_and_artifact_identity(self):
        def transport(path,payload=None,token=None):
            result={}
            if payload is None:
                result=self.api(path,payload,token)
            else:
                self.sent=json.loads(payload['inputs']['report'])
            return result
        env=dict(PACKAGE_REQUEST=json.dumps(self.payload),GITHUB_RUN_ID='501',GITHUB_RUN_ATTEMPT='1',BUILD_JOB_ID='1501',GITHUB_REPOSITORY='SNodeC/snode.c',NOTIFY_TOKEN='limited-notify')
        with patch.dict(os.environ,env),patch.object(dispatch,'api',side_effect=transport):
            dispatch.report(self.bundle,'publishing')
        self.assertEqual(self.sent['job'],'1501')
        self.assertEqual(self.sent['artifact'],self.payload['artifact'])
        return None

    def test_finalizer_does_not_invent_a_run_or_coordinator_job_link(self):
        payload=self.payload|dict(status='failed')
        payload.pop('artifact');payload.pop('job')
        with self.assertRaisesRegex(ValueError, 'job|identity'):
            dispatch.receive(payload,self.bundle)
        return None



    def test_failure_callback_cannot_close_a_successful_job_before_reconciliation(self):
        claim=self.payload|dict(status='failed')
        claim.pop('artifact')
        dispatch.apply_report(self.root,claim,self.bundle)
        self.assertEqual(self.node()['status'],'pending')
        self.tick()
        self.assertEqual(self.node()['status'],'publishing')
        self.assertEqual(self.node()['artifact']['id'],1234)
        self.assertIn('sign-and-publish-packages.yml',self.posts[-1][0])
        return None


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
class RpmSigningTest(PinnedJsonCase):
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
            temporary_files = root / 'tmp'
            temporary_files.mkdir()
            repository.run('rpmbuild', '--define', f'_topdir {root}', '--define', f'_tmppath {temporary_files}', '--define', f'_dbpath {root / "rpmdb"}', '-bb', str(spec))
            packages = root / 'RPMS/x86_64'
            (packages / 'snodec.packages').write_text('snodec\n')
            bundle, output, checkout = root / 'bundle', root / 'output', root / 'checkout'
            row = next(row for row in repository.linux_matrix() if row['distribution'] == 'rocky' and row['suite'] == '10' and row['arch'] == 'x86_64')
            publication.write(bundle / 'sources.json', {'snode.c': {'refs/tags/v2.0.0': 'a' * 40}})
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
        return None
