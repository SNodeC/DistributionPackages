"""Check packaging boundaries without building applications or contacting GitHub."""
import copy
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ci import repository
from ci.publish import publication


class PackagingTest(unittest.TestCase):
    def capture(self, directory, project='snode.c'):
        root, bundle = Path(directory) / 'published', Path(directory) / 'bundle'
        root.mkdir()
        row = publication.targets()[0]
        revisions = publication.reserve(root, project, '100')
        context = dict(run_id='100', run_url='https://example.invalid/run/100',
                       destination='SNodeC/Packages', release_project=project)
        for name, value in dict(context=context, targets=[row], revisions=revisions,
                                sources={}, profiles={}).items():
            publication.write(bundle / f'{name}.json', value)
        return root, bundle, row

    def operation(self, *args, attempt=1, details=None, jobs=()):
        details = details or dict(run_attempt=attempt, status='in_progress', conclusion=None)
        with patch('sys.argv', ['publication', *map(str, args)]), patch.dict(os.environ, {
                'GITHUB_RUN_ATTEMPT': str(attempt), 'GITHUB_REPOSITORY': 'SNodeC/DistributionPackages'}), \
                patch.object(publication, 'run', side_effect=[json.dumps(details), '\n'.join(map(json.dumps, jobs))]):
            try:
                publication.main()
            except SystemExit as result:
                self.assertEqual(result.code, 0)

    def test_single_workflow_preserves_every_target_dependency(self):
        workflows = list((repository.ROOT / '.github/workflows').glob('*.yml'))
        self.assertEqual([p.name for p in workflows], ['release.yml'])
        text = workflows[0].read_text()
        jobs = dict(re.findall(r'^  ([a-zA-Z0-9_]+):\n(.*?)(?=^  [a-zA-Z0-9_]+:\n|\Z)', text.split('\njobs:\n', 1)[1], re.M | re.S))
        self.assertEqual(len(jobs), 1 + 2 * len(publication.targets()))
        self.assertEqual(text.count('&build_and_publish_steps'), 1)
        self.assertEqual(text.count('*build_and_publish_steps'), 2 * len(publication.targets()) - 1)
        self.assertNotIn('workflow_call', text)
        self.assertNotIn('workflow_dispatch', text)
        self.assertNotIn('gh workflow run', text)
        for row in publication.targets():
            suffix = re.sub('[^a-zA-Z0-9_]', '_', row['id'])
            snodec = 'snodec_' + suffix
            for prefix, project in [('snodec', 'snode.c'), ('mqttsuite', 'mqttsuite')]:
                body = jobs[prefix + '_' + suffix]
                needs = re.search(r'^    needs:\n((?:      - .*\n)+)', body, re.M).group(1)
                dependencies = [line.removeprefix('      - ') for line in needs.splitlines()]
                self.assertEqual(dependencies, ['prepare'] if prefix == 'snodec' else ['prepare', snodec])
                self.assertIn('TARGET_ID: ' + row['id'], body)
                self.assertIn('BUILD_PROJECT: ' + project, body)
                self.assertIn("outputs.targets)['" + row['id'] + "'].runner", body)
                self.assertIn("outputs.targets)['" + row['id'] + "'].build_slot", body)
                if prefix == 'mqttsuite':
                    self.assertIn("needs." + snodec + ".result == 'success'", body)
                    self.assertIn("github.event.client_payload.repository == 'SNodeC/mqttsuite'", body)
        build = text.index('name: Build and test OpenWrt packages')
        running = text.index('name: Publish running badge')
        built = text.index('name: Publish build result badge')
        publishing = text.index('name: Publish publishing badge')
        published = text.index('name: Publish packages and published badge')
        self.assertLess(running, build)
        self.assertLess(build, built)
        self.assertLess(built, publishing)
        self.assertLess(publishing, published)

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
            root, bundle, row = self.capture(directory)
            self.operation('start', root, bundle)
            self.operation('finish', root, bundle, json.dumps(row), 'failure', 'unused', 'snode.c')
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
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publication.write(root / 'status.json', {'counters': {'snode.c': 128, 'mqttsuite': 129}})
            self.assertEqual(publication.reserve(root, 'mqttsuite', 'one'), {'mqttsuite': '130'})
            self.assertEqual(publication.reserve(root, 'snode.c', 'two'), {'snode.c': '129', 'mqttsuite': '131'})
            self.assertEqual(publication.reserve(root, 'mqttsuite', 'one'), {'mqttsuite': '130'})
            self.assertEqual(publication.reserve(root, 'mqttsuite', 'three'), {'mqttsuite': '132'})
            with self.assertRaisesRegex(RuntimeError, 'release project'):
                publication.reserve(root, 'snode.c', 'one')

    def test_first_release_starts_both_counters_at_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(publication.reserve(root, 'snode.c', 'first'),
                             {'snode.c': '1', 'mqttsuite': '1'})
            self.assertEqual(publication.reserve(root, 'mqttsuite', 'second'), {'mqttsuite': '2'})
            self.assertEqual(publication.reserve(root, 'snode.c', 'first'),
                             {'snode.c': '1', 'mqttsuite': '1'})
            self.assertEqual(publication.read(root / 'status.json')['counters'],
                             {'snode.c': 1, 'mqttsuite': 2})

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

    def test_status_initialization_publication_and_retry_preserve_public_output(self):
        for project in ('snode.c', 'mqttsuite'):
            with self.subTest(project=project), tempfile.TemporaryDirectory() as directory:
                root, bundle, row = self.capture(directory, project)
                other_row = publication.targets()[1]
                publication.write(bundle / 'targets.json', [row, other_row])
                (root / 'README.md').write_text('Keep the public landing page')
                self.operation('start', root, bundle)
                state = publication.read(root / 'status.json')
                selected = ('snode.c', 'mqttsuite') if project == 'snode.c' else ('mqttsuite',)
                self.assertEqual(set(state['targets']), {f"{r['id']}/{p}" for r in (row, other_row) for p in selected})
                self.assertEqual({item['status'] for item in state['targets'].values()}, {'pending'})
                self.assertEqual((root / 'README.md').read_text(), 'Keep the public landing page')
                # Another target's publication refreshes this running build without changing its feed.
                manifest = root / publication.feed_paths(row)[0] / 'build.json'
                publication.write(manifest, {'versions': {'mqttsuite': '1.0.2-r9'}})
                original_manifest = manifest.read_bytes()
                jobs = [dict(name=f"Build and publish {project} · {row['id']}", status='in_progress',
                             conclusion=None, html_url='https://example.invalid/job', run_attempt=1)]
                self.operation('finish', root, bundle, json.dumps(other_row), 'failure', 'unused', project, jobs=jobs)
                self.assertIn('>running</text>', (root / 'status' / f"{row['id']}-{project}.svg").read_text())
                self.assertIn('`1.0.2-r9`', (root / 'docs/status.md').read_text())
                self.assertEqual(manifest.read_bytes(), original_manifest)
                self.assertEqual((root / 'README.md').read_bytes(), (repository.ROOT / 'README.md').read_bytes())
                # Retry only the selected project and any dependent application.
                state = publication.read(root / 'status.json')
                for item in state['targets'].values():
                    item['status'] = 'published'
                publication.write(root / 'status.json', state)
                self.operation('finish', root, bundle, json.dumps(row), 'skipped', 'unused', project, attempt=2)
                result = publication.read(root / 'status.json')['targets']
                self.assertEqual(result[f"{row['id']}/{project}"]['status'], 'skipped')
                for other in set(selected) - {project}:
                    self.assertEqual(result[f"{row['id']}/{other}"]['status'], 'skipped')

    def test_status_lifecycle_from_job_results_and_committed_publications(self):
        row = publication.targets()[0]
        generation = dict(run_id='100', run_url='run', revisions={'snode.c': '1', 'mqttsuite': '1'},
                          targets=[row], context={'release_project': 'snode.c'})
        cases = [
            ('in_progress', None, 'in_progress', None, 'running', 'pending'),
            ('completed', 'failure', 'in_progress', None, 'failed', 'skipped'),
            ('completed', 'cancelled', 'completed', 'cancelled', 'cancelled', 'cancelled'),
            ('completed', 'timed_out', 'completed', 'failure', 'failed', 'skipped'),
            # A successful job without a committed publication is not published.
            ('completed', 'success', 'completed', 'success', 'failed', 'skipped'),
        ]
        for js, jc, rs, rc, sn, mq in cases:
            with self.subTest(job=jc, run=rs):
                state = {'runs': {'100': generation}, 'targets': {}}
                for project in generation['revisions']:
                    publication.update(state, row, generation, project, 'pending', 1)
                jobs = [dict(name=f'Build and publish snode.c · {row["id"]}', status=js, conclusion=jc)]
                with patch.dict(os.environ, {'GITHUB_REPOSITORY': 'SNodeC/DistributionPackages'}), \
                        patch.object(publication, 'run', side_effect=[json.dumps(dict(run_attempt=1, status=rs, conclusion=rc)),
                                                                      '\n'.join(map(json.dumps, jobs))]):
                    publication.reconcile(state, '100', 1)
                self.assertEqual([state['targets'][f"{row['id']}/{p}"]['status'] for p in generation['revisions']], [sn, mq])

        state = {'runs': {'100': generation}, 'targets': {}}
        for project in generation['revisions']:
            publication.update(state, row, generation, project, 'published', 1)
        original = copy.deepcopy(state)
        jobs = [dict(name=f'Build and publish mqttsuite · {row["id"]}', status='in_progress', run_attempt=2),
                dict(name=f'Build and publish snode.c · {row["id"]}', status='completed', conclusion='success', run_attempt=1)]
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': 'SNodeC/DistributionPackages'}), \
                patch.object(publication, 'run', side_effect=[json.dumps(dict(run_attempt=2, status='in_progress')),
                                                              '\n'.join(map(json.dumps, jobs))]):
            publication.reconcile(state, '100', 2)
        self.assertEqual(state['targets'][f"{row['id']}/snode.c"], original['targets'][f"{row['id']}/snode.c"])
        self.assertEqual(state['targets'][f"{row['id']}/mqttsuite"]['status'], 'running')
        # Cancellation keeps already committed packages; it ends unfinished work.
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': 'SNodeC/DistributionPackages'}), \
                patch.object(publication, 'run', side_effect=[json.dumps(dict(run_attempt=2, status='completed', conclusion='cancelled')), '']):
            publication.reconcile(state, '100', 2)
        self.assertEqual(state['targets'][f"{row['id']}/snode.c"]['status'], 'published')
        self.assertEqual(state['targets'][f"{row['id']}/mqttsuite"]['status'], 'cancelled')
        # Retrying SNode.C also schedules its dependent MQTTSuite, before its job appears.
        jobs = [dict(name=f'Build and publish snode.c · {row["id"]}', status='in_progress', run_attempt=3)]
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': 'SNodeC/DistributionPackages'}), \
                patch.object(publication, 'run', side_effect=[json.dumps(dict(run_attempt=3, status='in_progress')),
                                                              '\n'.join(map(json.dumps, jobs))]):
            publication.reconcile(state, '100', 3)
        self.assertEqual(state['targets'][f"{row['id']}/snode.c"]['status'], 'running')
        self.assertEqual(state['targets'][f"{row['id']}/mqttsuite"]['status'], 'pending')
        newer = generation | dict(run_id='101', revisions={'mqttsuite': '2'})
        publication.update(state, row, newer, 'mqttsuite', 'pending', 1)
        snapshot = copy.deepcopy(state)
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': 'SNodeC/DistributionPackages'}), \
                patch.object(publication, 'run', side_effect=[json.dumps(dict(run_attempt=3, status='in_progress')), '']):
            publication.reconcile(state, '100', 3)
        self.assertEqual(state, snapshot)

    def test_direct_badge_transitions_preserve_capture_and_publication(self):
        for project in ('snode.c', 'mqttsuite'):
            with self.subTest(project=project), tempfile.TemporaryDirectory() as directory:
                root, bundle, row = self.capture(directory, project)
                self.operation('start', root, bundle)
                # Build selection changes context/sources; status uses the registered generation.
                context = publication.read(bundle / 'context.json') | {'build_project': project}
                publication.write(bundle / 'context.json', context)
                publication.write(bundle / 'sources.json', {'selected': 'target'})
                for status in ('running', 'built', 'publishing', 'failed'):
                    self.operation('status', root, bundle, json.dumps(row), status, 'unused', project)
                    self.assertIn('>' + status + '</text>', (root / 'status' / f"{row['id']}-{project}.svg").read_text())
                # A retry can start again; the other project and original counters remain unchanged.
                self.operation('status', root, bundle, json.dumps(row), 'running', 'unused', project, attempt=2)
                self.operation('status', root, bundle, json.dumps(row), 'cancelled', 'unused', project, attempt=2)
                state = publication.read(root / 'status.json')
                self.assertEqual(state['targets'][f"{row['id']}/{project}"]['status'], 'cancelled')
                generation = state['runs']['100']
                publication.update(state, row, generation, project, 'published', 3)
                publication.write(root / 'status.json', state)
                self.operation('status', root, bundle, json.dumps(row), 'cancelled', 'unused', project, attempt=3)
                state = publication.read(root / 'status.json')
                self.assertEqual(state['targets'][f"{row['id']}/{project}"]['status'], 'published')
                self.assertEqual(state['counters'], {'snode.c': int(project == 'snode.c'), 'mqttsuite': 1})

    def test_publication_retry_keeps_original_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root, bundle, row = self.capture(directory)
            self.operation('start', root, bundle)
            before = {name: (bundle / name).read_bytes() for name in ('context.json', 'sources.json')}
            def selecting_publish(*args):
                publication.write(bundle / 'context.json', {'selected': 'context'})
                publication.write(bundle / 'sources.json', {'selected': 'sources'})
            with patch.object(publication, 'publish', side_effect=selecting_publish):
                for _ in range(2):
                    self.operation('finish', root, bundle, json.dumps(row), 'success', 'unused', 'snode.c')
                    self.assertEqual({name: (bundle / name).read_bytes() for name in before}, before)
            self.assertIn('>published</text>', (root / 'status' / f"{row['id']}-snode.c.svg").read_text())

    def test_snapshot_writer_reapplies_after_contention_without_losing_other_files(self):
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
            other = root / 'other'
            git('clone', str(remote), str(other), cwd=root)
            git('config', 'user.name', 'Packaging test', cwd=other)
            git('config', 'user.email', 'test@example.invalid', cwd=other)
            git('sparse-checkout', 'set', '--no-cone', '/selected-feed', cwd=work)
            callback = root / 'write.sh'
            callback.write_text('set -eu\nprintf \'new package\' > "$1/selected-feed"\nif [ ! -f "$3" ]; then\n    touch "$3"\n    printf \'running\' > "$2/other-badge"\n    git -C "$2" add .\n    git -C "$2" -c commit.gpgsign=false commit -qm \'competing badge update\'\n    git -C "$2" push origin main\nfi\n')
            script = repository.ROOT / 'ci/publish/push.sh'
            result = subprocess.run(['bash', str(script), str(work), 'publish', 'bash', str(callback),
                                     str(work), str(other), str(root / 'once')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(git('show', 'main:other-feed', cwd=remote), 'unchanged')
            self.assertEqual(git('show', 'main:other-badge', cwd=remote), 'running')
            self.assertEqual(git('show', 'main:selected-feed', cwd=remote), 'new package')
            self.assertEqual(git('rev-list', '--count', 'main', cwd=remote), '1')
            before = git('rev-parse', 'main', cwd=remote)
            callback.write_text('printf broken > "$1/selected-feed"; exit 1')
            result = subprocess.run(['bash', str(script), str(work), 'broken', 'bash', str(callback), str(work)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(git('rev-parse', 'main', cwd=remote), before)


if __name__ == '__main__':
    unittest.main()
