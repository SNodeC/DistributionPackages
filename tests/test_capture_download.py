"""One verified capture download shared by callback and reconciliation."""
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from ci import dispatch
from ci.publish import publication
from support import CoordinatorCase


class CaptureDownloadTest(CoordinatorCase):
    def callback(self):
        self.tick()
        node = self.finish()
        request = node['request'] | dict(status='publishing', run=node['source']['run'], attempt=1,
            job=self.jobs['SNodeC/snode.c', node['source']['run']][0]['id'], artifact=dict(id=1234, digest='sha256:' + 'f' * 64))
        self.artifacts[dispatch.COORDINATOR, 100] = [dict(name='source-pair', expired=False)]
        return request

    def downloader(self, downloads, tampered=False):
        original = dispatch.run
        def run(*args, **kwargs):
            result = ''
            if args[:3] == ('gh', 'run', 'download'):
                downloads.append(args)
                if len(downloads) > 1:
                    raise subprocess.CalledProcessError(1, args, stderr='HTTP 503: Egress is over the account limit')
                destination = Path(args[args.index('-D') + 1])
                shutil.copytree(self.bundle, destination, dirs_exist_ok=True)
                if tampered:
                    publication.write(destination / 'checksums.json', {'profiles.json': '0' * 64})
            else:
                result = original(*args, **kwargs)
            return result
        return run

    def test_callback_and_tick_download_once_and_admit_publication_in_the_same_pass(self):
        request = self.callback()
        downloads = []
        before = copy.deepcopy(self.node())
        with patch.dict(os.environ, PACKAGE_REPORT=json.dumps(request), PACKAGE_RETRY='', GITHUB_EVENT_NAME='workflow_dispatch'), \
                patch.object(sys, 'argv', ['dispatch', 'control', str(self.root)]), \
                patch.object(dispatch, 'run', side_effect=self.downloader(downloads)):
            dispatch.main()
        node = self.node()
        self.assertEqual(len(downloads), 1)
        self.assertEqual(node['publications'], 1)
        self.assertEqual(node['builds'], before['builds'])
        self.assertEqual(node['source'], before['source'])
        self.assertEqual(node['artifact'], request['artifact'])
        self.assertEqual(node['status'], 'publishing')
        self.assertEqual(len([1 for path, _ in self.posts if 'sign-and-publish-packages.yml' in path]), 1)
        return None

    def test_tampered_callback_capture_is_rejected_without_ledger_mutation_and_still_ticks(self):
        request = self.callback()
        downloads = []
        before = (self.root / 'status.json').read_bytes()
        with patch.dict(os.environ, PACKAGE_REPORT=json.dumps(request), PACKAGE_RETRY='', GITHUB_EVENT_NAME='workflow_dispatch'), \
                patch.object(sys, 'argv', ['dispatch', 'control', str(self.root)]), \
                patch.object(dispatch, 'run', side_effect=self.downloader(downloads, tampered=True)), \
                patch.object(dispatch, 'tick', return_value=False) as tick:
            with self.assertRaisesRegex(RuntimeError, '[Ii]ntegrity|[Cc]hecksum|Captured source archive changed'):
                dispatch.main()
        tick.assert_called_once()
        self.assertEqual((self.root / 'status.json').read_bytes(), before)
        self.assertEqual(len(downloads), 1)
        return None

    def test_expired_callback_capture_is_rejected_before_download_and_still_ticks(self):
        request = self.callback()
        self.artifacts[dispatch.COORDINATOR, 100][0]['expired'] = True
        before = (self.root / 'status.json').read_bytes()
        downloads = []
        with patch.dict(os.environ, PACKAGE_REPORT=json.dumps(request), PACKAGE_RETRY='', GITHUB_EVENT_NAME='workflow_dispatch'), \
                patch.object(sys, 'argv', ['dispatch', 'control', str(self.root)]), \
                patch.object(dispatch, 'run', side_effect=self.downloader(downloads)), \
                patch.object(dispatch, 'tick', return_value=False) as tick:
            with self.assertRaisesRegex(dispatch.ApiError, 'Capture unavailable'):
                dispatch.main()
        tick.assert_called_once()
        self.assertEqual((self.root / 'status.json').read_bytes(), before)
        self.assertEqual(downloads, [])
        return None
