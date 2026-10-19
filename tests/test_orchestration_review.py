"""Coordinator capture and API regressions; no source callback authority remains."""
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
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_missing_capture_is_retried_only_when_no_upload_succeeded(self):
        for conclusion in ['failure', 'success']:
            pages = [{'steps': [{'name': 'Save immutable release capture', 'conclusion': conclusion}]}]
            with self.subTest(conclusion=conclusion), patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '3', 'GITHUB_RUN_ID': '123'}), \
                 patch.object(dispatch, 'listing', return_value=pages) as run:
                if conclusion == 'success':
                    with self.assertRaisesRegex(ValueError, 'refusing to recapture'):
                        dispatch.retry_capture()
                else:
                    dispatch.retry_capture()
                    self.assertEqual(run.call_count, 2)
        with patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '1'}), patch.object(dispatch, 'listing') as run:
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

    def test_incomplete_api_listing_is_never_treated_as_absence(self):
        with patch.object(dispatch, 'api', return_value=dict(total_count=1000,workflow_runs=[])):
            with self.assertRaisesRegex(ValueError,'truncated'):
                dispatch.listing('repos/demo/actions/runs?status=queued','workflow_runs')

    def test_run_ids_are_canonical(self):
        for value in ['0123','0','-1','../123','１２３']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                dispatch.identity(value)
