"""Check packaging boundaries without building applications or contacting GitHub."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ci import repository
from ci.publish import publication


class PackagingTest(unittest.TestCase):
    def test_complete_matrix_and_dependency_files(self):
        rows = publication.targets()
        self.assertEqual(len(rows), 76)
        self.assertEqual(len({r['id'] for r in rows}), 76)
        self.assertEqual({r['build_slot'] for r in rows}, set(range(19)))
        self.assertEqual(sum(r['family'] == 'openwrt' for r in rows), 50)
        self.assertEqual(sum(r['family'] == 'raspberrypi' for r in rows), 2)
        self.assertEqual(sum(r['family'] == 'linux' for r in rows), 24)
        for row in rows:
            if row['family'] == 'linux' and row['arch'] in {'armhf', 'riscv64'}:
                self.assertEqual(row['build_slot'], 0 if row['arch'] == 'armhf' else 1)
            else:
                self.assertIn(row['build_slot'], range(2, 19))
            self.assertEqual(len(publication.feed_paths(row)),
                             2 if row['distribution'] in {'debian', 'ubuntu', 'raspberrypios'} else 1)
        for name in ['snode.c-sdk-2.0.0-r124.tar.zst', 'snodec-core_2.0.0-124~trixie_arm64.deb']:
            self.assertTrue(repository.project_file(name, 'snode.c'))
            self.assertFalse(repository.project_file(name, 'mqttsuite'))

    def test_public_documentation_and_installer_are_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publication.render(root, {'targets': {}})
            for source in [repository.ROOT / 'README.md',
                           *(repository.ROOT / 'docs').rglob('*.md'),
                           repository.ROOT / 'install/install.sh']:
                self.assertEqual((root / source.relative_to(repository.ROOT)).read_bytes(), source.read_bytes())
            status = (root / 'docs/status.md').read_text()
            self.assertTrue(status.startswith('# Package status'))
            self.assertIn('](../status/', status)
            self.assertNotIn('<!-- targets:', status)
            self.assertFalse((root / 'snodec').exists())
            self.assertFalse((root / 'mqttsuite').exists())
            scope = subprocess.check_output(
                ['python3', '-m', 'ci.publish.publication', 'scope', json.dumps(publication.targets()[0])], text=True)
            self.assertIn('/docs/', scope.splitlines())
            self.assertIn('/install/', scope.splitlines())

    def test_installer_openwrt_series_and_urls(self):
        source = (repository.ROOT / 'install/install.sh').read_text().split('fetch() {', 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / 'openwrt_release'
            script = root / 'installer.sh'
            source = source.replace('/etc/openwrt_release', str(fixture))
            source = source.replace('set -eu', 'set -eu\nid() { printf "0\\n"; }', 1)
            script.write_text(source + '\nprintf "%s|%s|%s\\n" "$manager" "$metadata" "$prepare"\n')
            for series, manager, index in [('24.10', 'opkg', 'Packages.gz'), ('25.12', 'apk', 'packages.adb')]:
                for suffix in ['', '.0', '.8', '-SNAPSHOT', '.0-rc1']:
                    fixture.write_text(f"DISTRIB_RELEASE='{series}{suffix}'\nDISTRIB_ARCH='aarch64_cortex-a53'\n")
                    for args, prepare in [([], 'false'), (['--prepare'], 'true')]:
                        result = subprocess.run(['sh', str(script), *args], text=True, capture_output=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout.strip(), f'{manager}|https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/{series}/aarch64_cortex-a53/{index}|{prepare}')
            fixture.write_text("DISTRIB_RELEASE='SNAPSHOT'\nDISTRIB_ARCH='aarch64_cortex-a53'\n")
            self.assertNotEqual(subprocess.run(['sh', str(script)], capture_output=True).returncode, 0)
            self.assertEqual(subprocess.run(['sh', str(script), '--suite', '25.12'], capture_output=True).returncode, 0)

    def test_revision_floor_rejects_downgrade_before_source_download(self):
        row = publication.targets()[0]
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'RELEASE_PROJECT': 'mqttsuite', 'RELEASE_TAG': 'v1.0.2',
            'GITHUB_RUN_ID': 'new'}), \
                patch.object(publication, 'targets', return_value=[row]), \
                patch.object(publication, 'published', return_value=({'revision': '121', 'versions': {'mqttsuite': '1.0.2-r121'}}, 'feed')), \
                patch.object(repository, 'run', return_value='recipe-commit'), \
                patch.object(repository, 'sources') as fetch:
            (Path(directory) / 'status.json').write_text(json.dumps({'allocations': {'new': {'mqttsuite': '120'}}}))
            with self.assertRaisesRegex(RuntimeError, 'Package revision must exceed'):
                repository.prepare(Path(directory), Path(directory) / 'bundle')
            fetch.assert_not_called()

    def test_independent_reservations_survive_retries_and_cancelled_runs(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'PACKAGE_REVISION_BASE': '122'}), \
                patch.object(publication, 'targets', return_value=[]):
            root = Path(directory)
            publication.write(root / 'status.json', {'runs': {'active': {'revisions': {'snode.c': '128', 'mqttsuite': '129'}}}})
            self.assertEqual(publication.reserve(root, 'mqttsuite', 'one'), {'mqttsuite': '130'})
            self.assertEqual(publication.reserve(root, 'snode.c', 'two'), {'snode.c': '129', 'mqttsuite': '131'})
            self.assertEqual(publication.reserve(root, 'mqttsuite', 'one'), {'mqttsuite': '130'})
            self.assertEqual(publication.reserve(root, 'mqttsuite', 'three'), {'mqttsuite': '132'})
            with self.assertRaisesRegex(RuntimeError, 'release project'):
                publication.reserve(root, 'snode.c', 'one')

    def test_reservation_seeds_from_each_published_project(self):
        info = {'versions': {'snodec': '2.0.0-150~trixie', 'mqttsuite': '1.0.2-170.el9'}}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'PACKAGE_REVISION_BASE': '122'}), \
                patch.object(publication, 'targets', return_value=[{}]), \
                patch.object(publication, 'published', return_value=(info, 'feed')):
            self.assertEqual(publication.reserve(Path(directory), 'snode.c', 'new'),
                             {'snode.c': '151', 'mqttsuite': '171'})

    def test_publication_orders_only_the_affected_project(self):
        for version in ['2.0.0-r128', '2.0.0-128~trixie', '2.0.0-128.el9']:
            old = {'versions': {'snodec': version, 'mqttsuite': '1.0.2-r200'}, 'revision': '200'}
            incoming = {'context': {'build_project': 'snode.c'}, 'revision': '129', 'files': {}, 'sources': {}}
            self.assertTrue(repository.publication_needed(old, incoming))
            incoming['revision'] = '127'
            with self.assertRaisesRegex(RuntimeError, 'Superseded'):
                repository.publication_needed(old, incoming)
            incoming['revision'] = '129'
            self.assertFalse(repository.publication_needed(incoming, incoming))
            with self.assertRaisesRegex(RuntimeError, 'Different package content'):
                repository.publication_needed(incoming, incoming | {'files': {'changed': 'hash'}})

    def test_newer_attempt_cannot_be_overwritten_by_older_generation(self):
        row = publication.targets()[0]
        state = {'targets': {}}
        generation = dict(revisions={'snode.c': '124'}, run_id='new', run_url='new-url')
        publication.update(state, row, generation, 'snode.c', 'published', 2)
        old = dict(revisions={'snode.c': '122'}, run_id='old', run_url='old-url')
        publication.update(state, row, old, 'snode.c', 'failed', 3)
        item = state['targets'][row['id'] + '/snode.c']
        self.assertEqual((item['revision'], item['status'], item['run_id']), ('124', 'published', 'new'))

    def test_snapshot_writer_preserves_other_feeds_and_rejects_stale_writer(self):
        def git(*args, cwd):
            return subprocess.check_output(['git', '-c', 'commit.gpgsign=false', *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / 'remote.git'
            git('init', '--bare', '-b', 'main', str(remote), cwd=root)
            work = root / 'work'
            git('clone', str(remote), str(work), cwd=root)
            git('config', 'user.name', 'Packaging test', cwd=work)
            git('config', 'user.email', 'test@example.invalid', cwd=work)
            (work / 'other-feed').write_text('unchanged')
            git('add', '.', cwd=work)
            git('commit', '-m', 'initial', cwd=work)
            git('push', 'origin', 'main', cwd=work)
            initial = git('rev-parse', 'HEAD', cwd=work)
            (work / 'selected-feed').write_text('new package')
            script = repository.ROOT / 'ci/publish/push.sh'
            result = subprocess.run(['bash', str(script), str(work), initial, 'publish'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(git('show', 'main:other-feed', cwd=remote), 'unchanged')
            self.assertEqual(git('show', 'main:selected-feed', cwd=remote), 'new package')
            self.assertEqual(git('rev-list', '--count', 'main', cwd=remote), '1')
            (work / 'selected-feed').write_text('stale replacement')
            result = subprocess.run(['bash', str(script), str(work), initial, 'stale'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(git('show', 'main:selected-feed', cwd=remote), 'new package')


if __name__ == '__main__':
    unittest.main()
