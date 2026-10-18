"""Recorded filesystem facts drive all package-status presentation."""
import copy
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from ci import repository
from ci.publish import publication


class PackagePagesTest(unittest.TestCase):
    def setUp(self):
        original_run = subprocess.run
        # Tests can select a checkout via environment; no production override or cache.
        tooling = os.environ.get('SNODEC_TEST_TOOLING', '')
        def fixtures(args, **kwargs):
            if 'clone' in args and 'https://github.com/SNodeC/.github.git' in args:
                control = Path(args[-1])
                for name in ('tools', 'navigation', 'brand'):
                    shutil.copytree(Path(tooling) / name, control / name)
                shutil.copy2(Path(tooling) / 'catalog.yml', control / 'catalog.yml')
                return subprocess.CompletedProcess(args, 0)
            if 'sparse-checkout' in args:
                return subprocess.CompletedProcess(args, 0)
            return original_run(args, **kwargs)
        if os.environ.get('SNODEC_TEST_TOOLING'):
            self.addCleanup(patch.stopall)
            patch('ci.publish.publication.subprocess.run', side_effect=fixtures).start()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.row = next(row for row in publication.targets() if row['id'] == 'debian-sid-armhf')
        self.key = self.row['id']
        self.generation = dict(revisions={'snode.c': '9', 'mqttsuite': '9'}, run_id='capture', run_url='run-url',
                               context={'captured_at': '2026-10-10T10:00:00Z'},
                               sources={'snode.c': {'refs/tags/v2.0.0': 'sha'}, 'mqttsuite': {'refs/tags/v1.0.2': 'sha'}})
        self.state = dict(targets={}, runs={'capture': self.generation})
        shutil.copy2(repository.ROOT / 'site/README.md', self.root / 'README.md')
        shutil.copytree(repository.ROOT / 'site/docs', self.root / 'docs')

    def feed(self, row=None, revision=9):
        row = row or self.row
        info = dict(versions={config['package']: repository.package_version(row, version, revision)
                    for config, version in zip(repository.PROJECTS.values(), ['2.0.0', '1.0.2'])},
                    context={'build_project': 'mqttsuite'}, published_at='2026-10-09T05:05:00Z')
        path = self.root / publication.feed_paths(row)[0] / 'build.json'
        if len(publication.feed_paths(row)) == 2:
            existing = publication.read(path, {'targets': {}})
            existing['targets'][row['arch']] = info
            info = existing
        publication.write(path, info)

    def event(self, project, status, row=None, attempt=1, log='job-url'):
        with patch.dict(os.environ, EVENT_TIME='2026-10-10T11:00:00Z', EVENT_STAGE='publication' if status == 'published' else 'build'):
            publication.update(self.state, row or self.row, self.generation, project, status, attempt, log)

    def text(self, package='snodec'):
        return (self.root / f'status/{package}.md').read_text()

    def table_row(self, architecture='armhf', package='snodec'):
        section = self.text(package).split('### Debian sid', 1)[1].split('## ', 1)[0]
        return next(line for line in section.splitlines() if line.startswith(f'| `{architecture}` |'))

    def test_idle_all_current_and_full_coverage(self):
        for row in publication.targets():
            self.feed(row)
            for project in self.generation['revisions']:
                self.event(project, 'published', row)
        publication.render(self.root, self.state)
        for package in ['snodec', 'mqttsuite']:
            rows = [line for line in self.text(package).splitlines() if line.startswith('| `')]
            self.assertEqual(len(rows), 76)
            self.assertTrue(all('alt="current"' in line and 'alt="published"' not in line for line in rows))
            self.assertTrue(all(line.split('|')[4].strip() == '—' for line in rows))
        self.assertIn('2.0.0 · r9', (self.root / 'README.md').read_text())
        self.assertIn('1.0.2 · r9', (self.root / 'status/README.md').read_text())
        self.assertNotIn('Available targets', (self.root / 'README.md').read_text())

    def test_platform_releases_follow_target_and_status_order(self):
        publication.render(self.root, self.state)
        table = (self.root / 'README.md').read_text().split('<!-- packages:begin platforms -->', 1)[1].split('<!-- packages:end platforms -->', 1)[0]
        cells = {}
        for distribution, (title, guide) in publication.DISTRIBUTIONS.items():
            with self.subTest(distribution=distribution):
                expected = list(dict.fromkeys(row['suite'] for row in publication.targets()
                                              if row['distribution'] == distribution))
                line = next(line for line in table.splitlines() if line.startswith(f'| [{title}]('))
                cells[distribution] = line.split('|')[2].strip()
                self.assertEqual(cells[distribution].split(', '), expected)
                for project, config in repository.PROJECTS.items():
                    if not any(repository.supports(project, row) for row in publication.targets() if row['distribution'] == distribution):
                        self.assertNotIn(f'| {title} |', self.text(config['package']))
                    else:
                        jump = next(line for line in self.text(config['package']).splitlines()
                                    if line.startswith(f'| {title} |'))
                        self.assertEqual(re.findall(r'\[([^]]+)\]\(', jump), expected)
        self.assertEqual(cells['debian'], 'trixie, forky, sid')
        self.assertEqual(cells['rocky'], '9, 10')

    def test_cancelled_and_skipped_replacements_keep_old_packages(self):
        self.feed(revision=5)
        self.event('snode.c', 'cancelled')
        self.event('mqttsuite', 'skipped', attempt=0)
        publication.render(self.root, self.state)
        snode, mqtt = self.table_row(), self.table_row(package='mqttsuite')
        for text in [snode, mqtt]:
            self.assertIn('alt="outdated"', text)
            self.assertEqual(text.count('|'), 6)
            self.assertNotIn('<br>', text)
        self.assertIn('alt="cancelled"', snode)
        self.assertIn('`2.0.0-5~sid`', snode)
        self.assertIn('`2.0.0-9~sid`', snode)
        self.assertIn('alt="skipped"', mqtt)
        self.assertIn('`1.0.2-9~sid`', mqtt)
        self.assertIn('2026-10-09 05:05', mqtt)
        self.assertNotIn('2026-10-09 05:05', snode)

    def test_mixed_in_progress_release_and_missing_values(self):
        for row, status in zip(publication.targets(), ['pending', 'running', 'publishing', 'published', 'failed', 'superseded']):
            self.feed(row, revision=9 if status == 'published' else 5)
            self.event('snode.c', status, row)
        publication.render(self.root, self.state)
        rows = [line for line in self.text().splitlines() if line.startswith('| `')]
        for label in ['pending', 'running', 'publishing', 'failed', 'superseded']:
            self.assertTrue(any(f'alt="{label}"' in line for line in rows))
        self.assertTrue(any('| — | — | — |' in line for line in rows))
        self.assertNotIn('Captured:', self.text())
        self.assertNotIn('Needs attention', self.text())
        self.assertNotIn('[Record]', self.text())
        self.assertNotIn('attempt 1', self.text())

    def test_build_log_selects_attempt_or_available_publication(self):
        self.feed(revision=5)
        self.state['timeline'] = {self.key + '/snode.c': {'published': {'revision': '5', 'at': '2026-10-09T12:00:00Z', 'job_url': 'old-job'}}}
        self.event('snode.c', 'running', log='new-job')
        publication.render(self.root, self.state)
        self.assertIn('[Build log](new-job)', self.table_row())
        self.assertIn('2026-10-09 12:00', self.table_row())
        # An attempt for a previous revision is not In build for the latest release.
        self.state['targets'][self.key + '/snode.c']['revision'] = '4'
        publication.render(self.root, self.state)
        self.assertIn('[Build log](old-job)', self.table_row())
        self.assertNotIn('alt="running"', self.table_row())
        del self.state['timeline'][self.key + '/snode.c']['published']['job_url']
        publication.render(self.root, self.state)
        self.assertNotIn('[Build log]', self.table_row())

    def test_publication_job_and_time_survive_later_attempt(self):
        self.feed()
        self.event('snode.c', 'published', log='published-job')
        self.assertEqual(self.state['timeline'][self.key + '/snode.c']['published']['job_url'], 'published-job')
        self.generation = self.generation | dict(run_id='next', revisions={'snode.c': '10'})
        self.state['runs']['next'] = self.generation
        self.event('snode.c', 'running', log='next-job')
        publication.render(self.root, self.state)
        self.assertIn('2026-10-10 11:00', self.table_row())
        self.assertIn('[Build log](next-job)', self.table_row())

    def test_publication_without_job_id_never_borrows_previous_generation_job(self):
        self.event('snode.c', 'published', log='old-job')
        self.generation = self.generation | dict(run_id='next', run_url='new-run', revisions={'snode.c': '10'})
        self.state['runs']['next'] = self.generation
        self.event('snode.c', 'published', log=None)
        self.assertEqual(self.state['timeline'][self.key + '/snode.c']['published']['job_url'], 'new-run')

    def test_unknown_latest_source_never_invents_attempt_version(self):
        self.generation['sources'] = {}
        self.event('snode.c', 'running')
        publication.render(self.root, self.state)
        self.assertIn('latest release —', self.text())
        self.assertNotIn('alt="running"', self.table_row())

    def test_source_version_mismatch_is_outdated_even_at_same_revision(self):
        self.feed()
        path = self.root / publication.feed_paths(self.row)[0] / 'build.json'
        info = publication.read(path)
        info['targets']['armhf']['versions']['snodec'] = '1.9.0-9~sid'
        publication.write(path, info)
        publication.render(self.root, self.state)
        self.assertIn('alt="outdated"', self.table_row())

    def test_package_formats_match_build_policy(self):
        for distribution, suite, expected in [('debian', 'sid', '2.0.0-9~sid'), ('raspberrypios', 'trixie', '2.0.0-9~trixie'),
                ('rocky', '10', '2.0.0-9.el10'), ('fedora', '44', '2.0.0-9.fc44'), ('openwrt', '24.10', '2.0.0-r9')]:
            with self.subTest(distribution=distribution):
                self.assertEqual(repository.package_version(dict(distribution=distribution, suite=suite), '2.0.0', '9'), expected)

    def test_openwrt_release_specific_architectures(self):
        publication.render(self.root, self.state)
        first, second = self.text().split('### OpenWrt 24.10')[1].split('### OpenWrt 25.12')
        self.assertIn('`riscv64_riscv64`', first)
        self.assertNotIn('`riscv64_generic`', first)
        self.assertIn('`riscv64_generic`', second)

    def test_deterministic_projection_preserves_state_feeds_and_authored_text(self):
        self.feed()
        self.event('snode.c', 'running')
        (self.root / 'README.md').write_text((self.root / 'README.md').read_text() + '\nAUTHORED SENTINEL\n')
        before = copy.deepcopy(self.state)
        publication.render(self.root, self.state)
        first = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        publication.render(self.root, self.state)
        self.assertEqual(first, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(before, self.state)
        self.assertIn('AUTHORED SENTINEL', (self.root / 'README.md').read_text())
        for anchor in {row['distribution'] + '-' + row['suite'].replace('.', '') for row in publication.targets()}:
            for package in ['snodec', 'mqttsuite']:
                self.assertIn(f'<a id="{anchor}"></a>', self.text(package))

    def test_third_project_requires_only_registry_entry(self):
        with patch.dict(repository.PROJECTS, {'new-project': dict(title='New project', package='new-package', depends_on=())}):
            publication.render(self.root, self.state)
        self.assertTrue((self.root / 'status/new-package.md').exists())
        self.assertNotIn('alt="Catalog"', self.text('new-package'))
        (self.root / 'docs/catalogs/new-package.md').write_text('New catalog')
        with patch.dict(repository.PROJECTS, {'new-project': dict(title='New project', package='new-package', depends_on=())}):
            publication.render(self.root, self.state)
        for path in ['README.md', 'status/README.md']:
            self.assertIn('[New project](https://github.com/SNodeC/new-project#banner)', (self.root / path).read_text())





    def test_replayed_regressive_terminal_events_do_not_change_metadata(self):
        self.event('snode.c', 'running')
        before = copy.deepcopy(self.state)
        self.event('snode.c', 'running')
        self.event('snode.c', 'pending')
        self.assertEqual(before, self.state)
        self.event('snode.c', 'published')
        before = copy.deepcopy(self.state)
        self.event('snode.c', 'failed')
        self.assertEqual(before, self.state)

    def test_failure_stage_and_retry_remain_recorded(self):
        self.event('snode.c', 'running')
        self.event('snode.c', 'failed')
        self.event('snode.c', 'running', attempt=2)
        self.event('snode.c', 'publishing', attempt=2)
        with patch.dict(os.environ, EVENT_TIME='2026-10-10T12:00:00Z', EVENT_STAGE='publication'):
            publication.update(self.state, self.row, self.generation, 'snode.c', 'failed', 2)
        event = self.state['timeline'][self.key + '/snode.c']['event']
        self.assertEqual(event['stage'], 'publication')
        self.assertEqual(event['started_at'], '2026-10-10T11:00:00Z')




    def test_public_render_command_preserves_authoritative_state(self):
        self.feed()
        self.event('snode.c', 'running')
        publication.write(self.root / 'status.json', self.state)
        before = (self.root / 'status.json').read_bytes()
        subprocess.run(['python3', '-m', 'ci.publish.publication', 'render', str(self.root)], cwd=repository.ROOT, check=True)
        self.assertEqual((self.root / 'status.json').read_bytes(), before)
        self.assertIn('2.0.0 · r9', self.text())

    def test_manual_workflow_only_renders_with_existing_publication_concurrency(self):
        workflow = (repository.ROOT / '.github/workflows/publish-guides-and-status.yml').read_text()
        self.assertIn('workflow_dispatch:', workflow)
        self.assertNotIn('schedule:', workflow)
        self.assertNotIn('push:', workflow)
        self.assertIn('group: package-publication', workflow)
        self.assertIn('github.event.repository.default_branch', workflow)
        self.assertIn('status.sh published render', workflow)
        self.assertNotIn('SIGNING_KEY:', workflow)

    def test_current_doc_overlay_preserves_capture_pinned_executables(self):
        workflow = (repository.ROOT / '.github/workflows/sign-and-publish-packages.yml').read_text()
        shell = workflow.split('          # Separate authored presentation', 1)[1].split('\n', 1)[1].split("          echo 'paths<<EOF'", 1)[0]
        shell = shell.replace('$DOCS_BRANCH', 'trunk')
        current = self.root / 'feed'
        current.mkdir()
        def git(*args):
            return subprocess.check_output(['git', '-c', 'commit.gpgsign=false', '-C', str(current), *args], text=True).strip()
        git('init', '-b', 'trunk')
        git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.invalid')
        (current / 'docs').mkdir()
        (current / 'docs/old.md').write_text('old')
        (current / 'README.md').write_text('old')
        (current / 'tool.py').write_text('CAPTURED')
        git('add', '.')
        git('commit', '-m', 'capture')
        commit = git('rev-parse', 'HEAD')
        shutil.copytree(repository.ROOT / 'site', current / 'site')
        (current / 'tool.py').write_text('NEW')
        git('add', '.')
        git('commit', '-m', 'current')
        git('update-ref', 'refs/remotes/origin/trunk', 'HEAD')
        tmp = self.root / 'runner'
        tmp.mkdir()
        env = os.environ | {'RUNNER_TEMP': str(tmp), 'GITHUB_ENV': str(self.root / 'env'),
                            'GITHUB_OUTPUT': str(self.root / 'output'), 'ImageOS': 'ubuntu24', 'ImageVersion': 'fixture'}
        subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', 'commit=' + commit + '\n' + shell], cwd=self.root, env=env, check=True, capture_output=True)
        self.assertIn('signer-platform=ubuntu24-fixture', (self.root / 'output').read_text())
        self.assertEqual((current / 'README.md').read_bytes(), (repository.ROOT / 'site/README.md').read_bytes())
        self.assertFalse((current / 'docs/old.md').exists())
        self.assertEqual((current / 'tool.py').read_text(), 'CAPTURED')





    def test_navigation_is_a_jump_table_and_body_links_are_text(self):
        publication.render(self.root, self.state)
        text = self.text()
        self.assertIn('| Distribution | Jump to release |', text)
        self.assertIn('[sid](#debian-sid)', text)
        self.assertIn('[↑ Distributions](#distributions)', text)
        self.assertIn('[Debian install guide](../docs/installation/debian.md#banner)', text)
        self.assertNotIn('src="menu/', text)
        self.assertIn('<!-- snodec:begin menu -->', text)
        self.assertNotIn('section-pages', (self.root / 'status/README.md').read_text())
        for path in ('README.md', 'status/README.md'):
            overview = (self.root / path).read_text()
            self.assertIn('[SNode.C status](', overview)
            self.assertIn('[MQTTSuite status](', overview)
            self.assertNotIn('status →', overview)

    def test_state_shapes_accessible_names_and_centered_geometry(self):
        import xml.etree.ElementTree as ET
        obsolete = self.root / 'status/badges/published.svg'
        obsolete.parent.mkdir(parents=True, exist_ok=True)
        obsolete.write_text('obsolete')
        publication.render(self.root, self.state)
        self.assertFalse(obsolete.exists())
        ns = '{http://www.w3.org/2000/svg}'
        badges = self.root / 'status/badges'
        self.assertEqual(len(list(badges.glob('*.svg'))), 10)
        for path in badges.glob('*.svg'):
            svg = ET.parse(path).getroot()
            self.assertEqual((svg.attrib['width'], svg.attrib['height'], svg.attrib['viewBox']), ('14', '14', '0 0 14 14'))
            self.assertEqual(svg.find(ns + 'title').text, path.stem.replace('-', ' '))
            circles = list(svg.iter(ns + 'circle'))
            self.assertTrue(all(c.attrib['cx'] == c.attrib['cy'] == '7' for c in circles))
            self.assertNotIn('text', [n.tag.removeprefix(ns) for n in svg])
        for label in ('pending', 'superseded', 'not-built', 'cancelled'):
            circle = ET.parse(badges / f'{label}.svg').getroot().find(ns + 'circle')
            self.assertEqual((circle.attrib['r'], circle.attrib['stroke-width'], circle.attrib['stroke']), ('5.25', '1.5', '#848d97'))
        self.assertIn('stroke="white"', (badges / 'current.svg').read_text())
        self.assertEqual(len(list(ET.parse(badges / 'outdated.svg').getroot().iter(ns + 'circle'))), 1)
        self.assertNotIn('alt="published"', self.text())
        for label in ('current', 'outdated', 'publishing', 'failed', 'skipped', 'cancelled'):
            self.assertIsNotNone(ET.parse(badges / f'{label}.svg').getroot().find(ns + 'path'))
        for label in ('current', 'outdated', 'skipped', 'running', 'publishing', 'failed', 'pending', 'superseded', 'not-built', 'cancelled'):
            self.assertEqual(self.text().count(f'alt="{label.replace("-", " ")}"'), 1)


if __name__ == '__main__':
    unittest.main()
