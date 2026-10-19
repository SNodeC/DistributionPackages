"""Cross-workflow regressions found during the coordinated release review."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ci import dispatch
from ci.publish import publication


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / 'bundle'
        self.rows = publication.targets()[:3]
        self.context = dict(run_id='123', run_url='capture-url', destination='SNodeC/Packages', release_project='snode.c')
        for name, value in dict(context=self.context, targets=self.rows,
                                revisions={'snode.c': '1', 'mqttsuite': '1'}, profiles={}, sources={}).items():
            publication.write(self.bundle / (name + '.json'), value)
        self.payload = dict(project='snode.c', target='-', status='failed', capture='123', run='456', attempt='1')
        self.capture = dict(event='repository_dispatch', path='.github/workflows/orchestrate-packages.yml',
                            head_repository={'full_name': dispatch.COORDINATOR})
        self.origin = dict(event='repository_dispatch', path='.github/workflows/build-distribution-packages.yml',
                           head_repository={'full_name': 'SNodeC/snode.c'}, run_attempt=1,
                           display_title='Packages · 123 · -', html_url='https://example.invalid/run')

    def job(self, row, conclusion, handed_off=False):
        return dict(name=f"build / {row['distribution']} · {row['suite']} · {row['arch']}",
                    run_id=456, run_attempt=1, conclusion=conclusion,
                    steps=[dict(name='Request signed publication', conclusion='success' if handed_off else 'skipped')])

    def test_finalization_before_publication_does_not_fail_successful_handoffs(self):
        # Even a job that fails during post-job cleanup must retain its successful handoff.
        jobs = [self.job(self.rows[0], 'success', True), self.job(self.rows[1], 'failure', True),
                self.job(self.rows[2], 'failure')]
        with patch.object(dispatch, 'api', side_effect=[self.capture, self.origin]), \
             patch.object(dispatch, 'run', return_value=json.dumps([{'jobs': jobs}])):
            receipt = dispatch.receive(self.payload, self.bundle, 'package-build-status')
        selected = json.loads(receipt['final_targets'])
        self.assertEqual(selected, self.rows[2:])
        state = dict(repository='SNodeC/Packages', branch='main', targets={}, runs={})
        generation = publication.record_run(self.bundle, state, self.context)
        for row in self.rows:
            publication.event(state, generation, row, 'snode.c', 'running', 1)
            publication.event(state, generation, row, 'mqttsuite', 'pending', 0)
        published = self.root / 'published'
        publication.write(published / 'status.json', state)
        with patch.dict(os.environ, {'BUILD_PROJECT': 'snode.c', 'BUILD_ATTEMPT': '1'}), \
             patch.object(publication, 'render'), patch('sys.argv',
                ['publication', 'finalize', str(published), str(self.bundle), 'failed', json.dumps(selected)]):
            publication.main()
        state = publication.read(published / 'status.json')
        for row in self.rows[:2]:
            publication.event(state, generation, row, 'snode.c', 'publishing', 1)
            publication.event(state, generation, row, 'snode.c', 'published', 1)
            self.assertEqual(state['targets'][row['id'] + '/snode.c']['status'], 'published')
            self.assertEqual(state['targets'][row['id'] + '/mqttsuite']['status'], 'pending')
        self.assertEqual(state['targets'][self.rows[2]['id'] + '/snode.c']['status'], 'failed')
        self.assertEqual(state['targets'][self.rows[2]['id'] + '/mqttsuite']['status'], 'skipped')

    def test_retry_finalization_retains_earlier_handoffs_not_rerun(self):
        jobs = [self.job(self.rows[0], 'success', True), self.job(self.rows[1], 'success', True),
                self.job(self.rows[1], 'failure') | {'run_attempt': 2},
                self.job(self.rows[2], 'success', True) | {'run_attempt': 3}]
        with patch.object(dispatch, 'api', side_effect=[self.capture, self.origin | {'run_attempt': 3}]), \
             patch.object(dispatch, 'run', return_value=json.dumps([{'jobs': jobs}])) as run:
            receipt = dispatch.receive(self.payload | {'attempt': '2'}, self.bundle, 'package-build-status')
        self.assertEqual(json.loads(receipt['final_targets']), self.rows[1:])
        self.assertIn('filter=all', run.call_args.args[-1])

    def test_capture_owns_target_row_when_current_matrix_changes(self):
        row = self.rows[0]
        payload = self.payload | dict(target=row['id'], job='789', status='running')
        job = self.job(row, None) | dict(html_url='https://example.invalid/job')
        with patch.object(dispatch, 'api', side_effect=[self.capture, self.origin, job]), \
             patch.object(publication, 'targets', side_effect=AssertionError('must use the capture')):
            receipt = dispatch.receive(payload, self.bundle, 'package-build-status')
        self.assertEqual(json.loads(receipt['target']), row)
        self.assertEqual(receipt['run_url'], job['html_url'])
        self.assertEqual(receipt['final_targets'], 'null')

    def test_finalizer_only_covers_its_requested_target(self):
        payload = self.payload | dict(project='mqttsuite', target=self.rows[1]['id'])
        origin = self.origin | dict(head_repository={'full_name': 'SNodeC/mqttsuite'},
                                   display_title=f"Packages · 123 · {self.rows[1]['id']}")
        with patch.object(dispatch, 'api', side_effect=[self.capture, origin]), \
             patch.object(dispatch, 'run', return_value='[{"jobs": []}]'):
            receipt = dispatch.receive(payload, self.bundle, 'package-build-status')
        self.assertEqual(json.loads(receipt['final_targets']), self.rows[1:2])

    def test_event_type_and_canonical_run_ids_are_enforced(self):
        for invalid in ['0123', '0', '-1', '../123', '１２３']:
            with self.subTest(identity=invalid), self.assertRaises(ValueError):
                dispatch.identity(invalid)
        for action, status in [('sign-and-publish-packages', 'running'), ('package-build-status', 'publishing')]:
            with self.subTest(action=action), self.assertRaises(ValueError), patch.object(dispatch, 'api') as api:
                dispatch.receive(self.payload | dict(target=self.rows[0]['id'], status=status), self.bundle, action)
            api.assert_not_called()

    def test_newer_published_application_is_not_left_pending_by_older_generation(self):
        row = self.rows[0]
        generation = dict(self.context, targets=[row], revisions={'snode.c': '1', 'mqttsuite': '1'}, context=self.context)
        state = {'targets': {}}
        publication.event(state, generation, row, 'mqttsuite', 'pending', 0)
        newer = generation | dict(run_id='999', revisions={'mqttsuite': '2'})
        publication.event(state, newer, row, 'mqttsuite', 'published', 1)
        publication.event(state, generation, row, 'mqttsuite', 'pending', 0)
        info = dict(versions={'snode.c': '1.0.0-1', 'mqttsuite': '1.0.0-2'}, sources={'snode.c': 'source'})
        publication.write(self.bundle / 'profiles.json', {row['id']: dict(sources=info['sources'], baseline={})})
        with patch.object(dispatch, 'published', return_value=(info, 'feed')), patch.object(dispatch, 'build') as build:
            dispatch.dependents(self.bundle, row['id'], 'a' * 40, self.root)
            build.assert_not_called()
        current = state['targets'][row['id'] + '/mqttsuite']
        self.assertEqual((current['run_id'], current['revision'], current['status']), ('999', '2', 'published'))

    def test_missing_capture_is_retried_only_when_no_upload_succeeded(self):
        for conclusion in ['failure', 'success']:
            pages = json.dumps([{'jobs': [{'steps': [{'name': 'Save immutable release capture', 'conclusion': conclusion}]}]}])
            with self.subTest(conclusion=conclusion), patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '3', 'GITHUB_RUN_ID': '123'}), \
                 patch.object(dispatch, 'run', return_value=pages) as run:
                if conclusion == 'success':
                    with self.assertRaisesRegex(ValueError, 'refusing to recapture'):
                        dispatch.retry_capture()
                else:
                    dispatch.retry_capture()
                    self.assertEqual(run.call_count, 2)
        with patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '1'}), patch.object(dispatch, 'run') as run:
            dispatch.retry_capture()
            run.assert_not_called()

    def test_old_source_workflow_cannot_allocate_before_capture_fails(self):
        root = self.root / 'published'
        publication.write(root / 'status.json', dict(counters={'snode.c': 9}, allocations={}))
        before = (root / 'status.json').read_bytes()
        env = dict(RELEASE_PROJECT='snode.c', GITHUB_RUN_ID='123', GITHUB_REPOSITORY='SNodeC/snode.c',
                   GITHUB_WORKFLOW_REF='SNodeC/snode.c/.github/workflows/build-distribution-packages.yml@refs/tags/v1.0.0')
        with patch.dict(os.environ, env), patch('sys.argv', ['publication', 'reserve', str(root)]):
            with self.assertRaises(ValueError):
                publication.main()
        self.assertEqual((root / 'status.json').read_bytes(), before)
        env.update(GITHUB_REPOSITORY=dispatch.COORDINATOR,
                   GITHUB_WORKFLOW_REF=dispatch.COORDINATOR + '/.github/workflows/orchestrate-packages.yml@refs/heads/main')
        with patch.dict(os.environ, env), patch('sys.argv', ['publication', 'reserve', str(root)]):
            publication.main()
        self.assertEqual(publication.read(root / 'status.json')['counters']['snode.c'], 10)


if __name__ == '__main__':
    unittest.main()
