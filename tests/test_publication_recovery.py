"""Publication facts recover failed status without inventing a source job."""
import unittest
from ci.publish import publication


class RecoveryTest(unittest.TestCase):
    def test_verified_publication_recovers_failure_and_remains_terminal(self):
        state = {'targets': {}}
        row = publication.targets()[0]
        generation = dict(run_id='100', run_url='coordinator', revisions={'snode.c': '1'})
        for status in ['pending', 'publishing', 'failed', 'published', 'cancelled']:
            publication.update(state, row, generation, 'snode.c', status, 1)
        result = publication.projection(state)['targets'][row['id'] + '/snode.c']
        self.assertEqual(result['status'], 'published')
        self.assertIsNone(result['job_url'])
        newer = generation | dict(run_id='200', revisions={'snode.c': '2'})
        publication.update(state, row, newer, 'snode.c', 'pending', 0)
        self.assertIsNone(publication.projection(state)['targets'][row['id'] + '/snode.c']['job_url'])
        self.assertIsNone(publication.projection(state)['timeline'][row['id'] + '/snode.c']['published']['job_url'])

class ReceiptIntegrityTest(unittest.TestCase):
    def test_idempotent_receipt_still_verifies_downloaded_bytes(self):
        import hashlib
        import json
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root, bundle, incoming = (Path(temporary) / name for name in ('feed', 'bundle', 'incoming'))
            row = next(r for r in publication.targets() if r['id'] == 'debian-trixie-amd64')
            directory = incoming / 'linux/debian/trixie/amd64'
            directory.mkdir(parents=True)
            data = b'original package'
            (directory / 'snodec_1.deb').write_bytes(data)
            files = {'snodec_1.deb': hashlib.sha256(data).hexdigest()}
            receipt = dict(capture='100', artifact=dict(id=42, digest='sha256:' + 'a' * 64))
            publication.write(directory / 'build.json', dict(files=files))
            publication.write(root / 'debian/dists/trixie/build.json', {'targets': {'amd64': dict(
                publications={'snode.c': receipt | dict(unsigned_files=files)})}})
            with patch.dict(os.environ, BUILD_RECEIPT=json.dumps(receipt)):
                publication.publish(root, bundle, incoming, row, dict(context=dict(contract=2)), 'snode.c')
                (directory / 'snodec_1.deb').write_bytes(b'corrupted download')
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    publication.publish(root, bundle, incoming, row, dict(context=dict(contract=2)), 'snode.c')
