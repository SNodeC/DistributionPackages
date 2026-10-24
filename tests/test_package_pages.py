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
from support import feed_manifest, CoordinatorCase
from ci import repository, dispatch
from ci.publish import publication


class PackagePagesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.row = next(row for row in publication.targets() if row['id'] == 'debian-sid-armhf')
        self.key = self.row['id']
        self.generation = dict(revisions={'snode.c': '9', 'mqttsuite': '9'}, run_id='capture', run_url='run-url',
                               context={'captured_at': '2026-10-10T10:00:00Z', 'projects': copy.deepcopy(repository.PROJECTS)},
                               sources={r['id']: {'snode.c': {'refs/tags/v2.0.0': 'a'*40}, 'mqttsuite': {'refs/tags/v1.0.2': 'b'*40}}
                                        for r in publication.targets()})
        self.state = dict(targets={}, runs={'capture': self.generation})
        shutil.copy2(repository.ROOT / 'site/README.md', self.root / 'README.md')
        shutil.copytree(repository.ROOT / 'site/docs', self.root / 'docs')

    def feed(self, row=None, revision=9):
        row = row or self.row
        info = dict(versions={config['package']: repository.package_version(row, version, revision)
                    for config, version in zip(repository.PROJECTS.values(), ['2.0.0', '1.0.2'])},
                    context={'build_project': 'mqttsuite'}, published_at='2026-10-09T05:05:00Z')
        info.update(sources=self.generation['sources'].get(row['id'], {}))
        info = feed_manifest(info)
        path = self.root / publication.feed_paths(row)[0] / 'build.json'
        if len(publication.feed_paths(row)) == 2:
            existing = publication.read(path, {'targets': {}})
            existing['targets'][row['arch']] = info
            info = existing
        publication.write(path, info)

    def event(self, project, status, row=None, attempt=1, log='https://github.com/SNodeC/snode.c/actions/runs/5/job/5'):
        with patch.dict(os.environ, EVENT_TIME='2026-10-10T11:00:00Z', EVENT_STAGE='publication' if status == 'published' else 'build'):
            publication.update(self.state, row or self.row, self.generation, project, status, attempt, log)
        return None

    def text(self, package='snodec'):
        return (self.root / f'status/{package}.md').read_text()

    def table_row(self, architecture='armhf', package='snodec'):
        section = self.text(package).split('### Debian sid', 1)[1].split('## ', 1)[0]
        return next(line for line in section.splitlines() if line.startswith(f'<tr><td align="left"><code>{architecture}</code>'))

    def test_idle_all_current_and_full_coverage(self):
        for row in publication.targets():
            self.feed(row)
            for project in self.generation['revisions']:
                self.event(project, 'published', row)
        publication.render(self.root, self.state)
        for package in ['snodec', 'mqttsuite']:
            rows = [line for line in self.text(package).splitlines() if line.startswith('<tr><td ')]
            self.assertEqual(len(rows), 76)
            self.assertTrue(all('alt="current"' not in line and 'alt="published"' not in line for line in rows))
            self.assertTrue(all(re.findall(r'<td[^>]*>(.*?)</td>', line)[3] == '—' for line in rows))
        self.assertIn('2.0.0', (self.root / 'README.md').read_text())
        self.assertNotIn(' · r', (self.root / 'README.md').read_text())
        self.assertNotIn(' · r', (self.root / 'status/README.md').read_text())
        self.assertIn('1.0.2', (self.root / 'status/README.md').read_text())
        self.assertNotIn('Available targets', (self.root / 'README.md').read_text())

    def test_divergent_rows_keep_their_own_current_revision_under_version_only_heading(self):
        other = next(r for r in publication.targets() if r['id'] == 'debian-sid-amd64')
        newer = copy.deepcopy(self.generation)
        newer.update(run_id='other-row', revisions={'snode.c': '10'}, sources={other['id']: self.generation['sources'][other['id']]})
        self.state['runs']['other-row'] = newer
        self.feed(self.row, revision=9)
        self.feed(other, revision=10)
        self.event('snode.c', 'published')
        publication.update(self.state, other, newer, 'snode.c', 'published', 1, 'https://github.com/SNodeC/snode.c/actions/runs/6/job/6')
        publication.render(self.root, self.state)
        for arch, revision in [('armhf', 9), ('amd64', 10)]:
            row = self.table_row(arch)
            self.assertIn(f'2.0.0-{revision}~sid', row)
            self.assertNotIn('alt="current"', row)
            self.assertNotIn('alt="outdated"', row)
            self.assertEqual(re.findall(r'<td[^>]*>(.*?)</td>', row)[3], '—')
        self.assertIn('Available shows the published package version without a current/outdated indicator', self.text())
        for text in [self.text(), (self.root / 'README.md').read_text(), (self.root / 'status/README.md').read_text()]:
            self.assertIn('2.0.0', text)
            self.assertNotIn('2.0.0 · r', text)
        return None

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
                for project, config in self.generation['context']['projects'].items():
                    if project not in self.generation['revisions']:
                        continue
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
            self.assertNotIn('alt="outdated"', text)
            self.assertEqual(len(re.findall(r'<td[^>]*>', text)), 5)
            self.assertNotIn('<br>', text)
        self.assertIn('alt="cancelled"', snode)
        self.assertIn('<code>2.0.0-5~sid</code>', snode)
        self.assertIn('<code>2.0.0-9~sid</code>', snode)
        self.assertIn('alt="skipped"', mqtt)
        self.assertIn('<code>1.0.2-9~sid</code>', mqtt)
        self.assertIn('2026-10-09 05:05', mqtt)
        self.assertNotIn('2026-10-09 05:05', snode)

    def test_mixed_in_progress_release_and_missing_values(self):
        for row, status in zip(publication.targets(), ['pending', 'running', 'publishing', 'published', 'failed', 'superseded']):
            self.feed(row, revision=9 if status == 'published' else 5)
            self.event('snode.c', status, row)
        publication.render(self.root, self.state)
        rows = [line for line in self.text().splitlines() if line.startswith('<tr><td ')]
        for label in ['pending', 'running', 'publishing', 'failed', 'superseded']:
            self.assertTrue(any(f'alt="{label}"' in line for line in rows))
        self.assertTrue(any('<td align="center">—</td>' in line for line in rows))
        self.assertTrue(any('alt="not built"' in line for line in rows))
        self.assertNotIn('Captured:', self.text())
        self.assertNotIn('Needs attention', self.text())
        self.assertNotIn('[Record]', self.text())
        self.assertNotIn('attempt 1', self.text())

    def test_build_log_selects_attempt_or_available_publication(self):
        self.feed(revision=5)
        key = self.key + '/snode.c'
        old = copy.deepcopy(self.generation)
        old.update(run_id='old', revisions={'snode.c': '5'}, nodes={key: dict(status='published', attempt=1, job_url='https://github.com/SNodeC/snode.c/actions/runs/1/job/1', published=dict(revision='5', at='2026-10-09T12:00:00Z', job_url='https://github.com/SNodeC/snode.c/actions/runs/1/job/1'))})
        self.state['runs']['old'] = old
        self.event('snode.c', 'running', log='https://github.com/SNodeC/snode.c/actions/runs/2/job/2')
        publication.render(self.root, self.state)
        self.assertIn('<a href="https://github.com/SNodeC/snode.c/actions/runs/2/job/2">Build log</a>', self.table_row())
        self.assertIn('2026-10-09 12:00', self.table_row())
        self.generation['nodes'].pop(key)
        old['nodes'][key]['status'] = 'running'
        publication.render(self.root, self.state)
        self.assertIn('<a href="https://github.com/SNodeC/snode.c/actions/runs/1/job/1">Build log</a>', self.table_row())
        self.assertNotIn('alt="running"', self.table_row())
        old['nodes'][key]['published'].pop('job_url')
        old['nodes'][key]['job_url'] = None
        publication.render(self.root, self.state)
        self.assertNotIn('>Build log</a>', self.table_row())
        return None

    def test_publication_job_and_time_survive_later_attempt(self):
        self.feed()
        self.event('snode.c', 'published', log='https://github.com/SNodeC/snode.c/actions/runs/4/job/4')
        self.assertEqual(publication.projection(self.state)['timeline'][self.key + '/snode.c']['published']['job_url'], 'https://github.com/SNodeC/snode.c/actions/runs/4/job/4')
        self.generation = copy.deepcopy(self.generation) | dict(run_id='next', revisions={'snode.c': '10'}, nodes={})
        self.state['runs']['next'] = self.generation
        self.event('snode.c', 'running', log='https://github.com/SNodeC/snode.c/actions/runs/3/job/3')
        publication.render(self.root, self.state)
        self.assertIn('2026-10-10 11:00', self.table_row())
        self.assertIn('<a href="https://github.com/SNodeC/snode.c/actions/runs/3/job/3">Build log</a>', self.table_row())
        return None

    def test_publication_without_job_id_never_borrows_previous_generation_job(self):
        self.event('snode.c', 'published', log='https://github.com/SNodeC/snode.c/actions/runs/1/job/1')
        self.generation = copy.deepcopy(self.generation) | dict(run_id='next', run_url='new-run', revisions={'snode.c': '10'}, nodes={})
        self.state['runs']['next'] = self.generation
        self.event('snode.c', 'published', log=None)
        self.assertIsNone(publication.projection(self.state)['timeline'][self.key + '/snode.c']['published']['job_url'])
        return None

    def test_unknown_latest_source_never_invents_attempt_version(self):
        self.generation['sources'] = {}
        self.event('snode.c', 'running')
        publication.render(self.root, self.state)
        self.assertFalse((self.root / 'status/snodec.md').exists(), 'No valid tagged source means no invented product status')

    def test_available_version_is_plain_even_when_control_version_differs(self):
        self.feed()
        path = self.root / publication.feed_paths(self.row)[0] / 'build.json'
        info = publication.read(path)
        info['targets']['armhf']['releases']['snode.c']['v2.0.0']['versions']['snode.c'] = '1.9.0-9~sid'
        publication.write(path, info)
        publication.render(self.root, self.state)
        self.assertNotIn('alt="outdated"', self.table_row())
        self.assertIn('<code>1.9.0-9~sid</code>', self.table_row())

    def test_package_formats_match_build_policy(self):
        for distribution, suite, expected in [('debian', 'sid', '2.0.0-9~sid'), ('raspberrypios', 'trixie', '2.0.0-9~trixie'),
                ('rocky', '10', '2.0.0-9.el10'), ('fedora', '44', '2.0.0-9.fc44'), ('openwrt', '24.10', '2.0.0-r9')]:
            with self.subTest(distribution=distribution):
                self.assertEqual(repository.package_version(dict(distribution=distribution, suite=suite), '2.0.0', '9'), expected)

    def test_openwrt_release_specific_architectures(self):
        publication.render(self.root, self.state)
        first, second = self.text().split('### OpenWrt 24.10')[1].split('### OpenWrt 25.12')
        self.assertIn('<code>riscv64_riscv64</code>', first)
        self.assertNotIn('<code>riscv64_generic</code>', first)
        self.assertIn('<code>riscv64_generic</code>', second)

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
        config = dict(repository.PROJECTS['snode.c'], title='New project', package='new-package', depends_on=[])
        self.generation['revisions']['new-project'] = '1'
        self.generation['context']['projects']['new-project'] = config
        for sources in self.generation['sources'].values():
            sources['new-project'] = {'refs/tags/v1.0.0': 'c' * 40}
        with patch.dict(repository.PROJECTS, {'new-project': dict(repository.PROJECTS['snode.c'], title='New project', package='new-package', depends_on=[])}):
            publication.render(self.root, self.state)
        self.assertTrue((self.root / 'status/new-package.md').exists())
        self.assertNotIn('alt="Catalog"', self.text('new-package'))
        (self.root / 'docs/catalogs/new-package.md').write_text('New catalog')
        with patch.dict(repository.PROJECTS, {'new-project': dict(repository.PROJECTS['snode.c'], title='New project', package='new-package', depends_on=[])}):
            publication.render(self.root, self.state)
        for path in ['README.md', 'status/README.md']:
            self.assertIn('[New project](https://github.com/SNodeC/new-project#banner)', (self.root / path).read_text())
        return None





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
        event = publication.projection(self.state)['timeline'][self.key + '/snode.c']['event']
        self.assertEqual(event['stage'], 'publication')
        self.assertEqual(event['started_at'], '2026-10-10T11:00:00Z')
        return None




    def test_public_render_command_preserves_authoritative_state(self):
        self.feed()
        self.event('snode.c', 'running')
        publication.write(self.root / 'status.json', self.state)
        before = (self.root / 'status.json').read_bytes()
        subprocess.run(['python3', '-m', 'ci.publish.publication', 'render', str(self.root)], cwd=repository.ROOT, check=True)
        self.assertEqual((self.root / 'status.json').read_bytes(), before)
        self.assertIn('2.0.0', self.text())

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
        shell = workflow.split('          # Publish current guides', 1)[1].split('\n', 1)[1].split("          echo 'paths<<EOF'", 1)[0]
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
        (current / 'install').mkdir()
        (current / 'install/install.sh').write_text('# obsolete ecosystem installer')
        (current / 'tool.py').write_text('CAPTURED')
        (current / 'keys').mkdir()
        (current / 'keys/opkg.pub').write_text('CAPTURED KEY')
        git('add', '.')
        git('commit', '-m', 'capture')
        commit = git('rev-parse', 'HEAD')
        shutil.copytree(repository.ROOT / 'site', current / 'site')
        shutil.rmtree(current / 'install')
        shutil.copytree(repository.ROOT / 'install', current / 'install')
        (current / 'tool.py').write_text('NEW')
        (current / 'keys/opkg.pub').write_text('CURRENT KEY')
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
        self.assertEqual((current / 'keys/opkg.pub').read_text(), 'CAPTURED KEY')
        self.assertEqual((tmp / 'package-site/keys/opkg.pub').read_text(), 'CURRENT KEY')
        self.assertEqual({p.name: p.read_bytes() for p in (current / 'install').iterdir()},
                         {p.name: p.read_bytes() for p in (repository.ROOT / 'install').iterdir()})
        self.assertIn('PACKAGE_SITE=' + str(tmp / 'package-site/site'), (self.root / 'env').read_text())





    def test_navigation_is_a_jump_table_and_body_links_are_text(self):
        publication.render(self.root, self.state)
        text = self.text()
        self.assertIn('| Distribution | Jump to release |', text)
        self.assertIn('[sid](#debian-sid)', text)
        self.assertIn('[↑ Distributions](#distributions)', text)
        self.assertIn('[Debian install guide](../docs/installation/debian.md#banner)', text)
        self.assertNotIn('src="menu/', text)
        self.assertIn('<!-- packages:begin menu -->', text)
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
        self.assertEqual(len(list(badges.glob('*.svg'))), 11)
        self.assertFalse((badges / 'current.svg').exists())
        self.assertFalse((badges / 'outdated.svg').exists())
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
        self.assertIn('stroke="white"', (badges / 'blocked.svg').read_text())
        self.assertEqual(len(list(ET.parse(badges / 'waiting.svg').getroot().iter(ns + 'circle'))), 1)
        self.assertNotIn('alt="published"', self.text())
        for label in ('blocked', 'waiting', 'publishing', 'failed', 'skipped', 'cancelled'):
            self.assertIsNotNone(ET.parse(badges / f'{label}.svg').getroot().find(ns + 'path'))
        for label in ('blocked', 'waiting', 'skipped', 'running', 'publishing', 'failed', 'pending', 'superseded', 'not-built', 'cancelled'):
            self.assertEqual(self.text().split('**Legend:**', 1)[1].split('\n', 1)[0].count(f'alt="{label.replace("-", " ")}"'), 1)
        return None

    def test_released_rows_survive_head_matrix_removal_and_unreleased_rows_are_hidden(self):
        config = copy.deepcopy(repository.PROJECTS['snode.c'])
        config['title'] = 'Demo]\n|injected'
        config['matrix'] = {'linux':[dict(distribution='debian',suite='trixie',image='debian:trixie',architectures=['amd64'])]}
        config['build'] = {'native':'ci/package/native.sh'}
        new = repository.rows(config)[0]
        generation = dict(self.generation, targets=[self.row,new], revisions={'snode.c':'1'}, context={'contract':3,
            'projects':{'snode.c':dict(config, matrix={'linux':[dict(distribution='debian',suite='sid',image='debian:sid',
            architectures=['armhf'])]})}}, sources={self.row['id']:{'snode.c':{'refs/tags/v1.0.0':'a'*40}}})
        with patch.dict(repository.PROJECTS, {'snode.c':config}, clear=True):
            publication.render(self.root, {'runs':{'capture':generation}})
        page = (self.root/'status/snodec.md').read_text()
        self.assertIn('### Debian sid', page)
        self.assertIn('armhf', page)
        self.assertNotIn('### Debian trixie', page)
        self.assertNotIn('Demo]\n|injected', page)
        return None




class DependencyPageTest(unittest.TestCase):
    """Synthetic diamond facts, rendered without source or network discovery."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = copy.deepcopy(repository.PROJECTS['snode.c'])
        config.update(matrix={'linux': [dict(distribution='debian', suite='trixie', image='debian:trixie', architectures=['amd64'])]},
                      build={'native': 'ci/package/native.sh'})
        self.graph = {p: dict(config, title=p.capitalize(), package=p, depends_on=deps)
                      for p, deps in [('core', []), ('app', ['core']), ('side', ['core']), ('join', ['app', 'side'])]}
        self.row = repository.rows(self.graph['core'])[0]
        self.target = self.row['id']
        self.sources = {p: {'refs/tags/v1.0.0': str(i) * 40} for i, p in enumerate(self.graph, 1)}
        self.state = dict(runs={'old': dict(run_id='old', revisions=dict.fromkeys(self.graph, '1'),
            context=dict(projects=self.graph, release_project='core', cascade='old'), sources={self.target: self.sources},
            nodes={self.target + '/' + p: dict(status='published') for p in self.graph})})
        self.info = feed_manifest(dict(sources=self.sources, versions={p: '1.0.0-1~trixie' for p in self.graph},
            publications={p: dict(capture='old', revision='1', published_at='2026-10-23T00:00:00Z', job_url=None)
                          for p in self.graph}), self.graph)
        self.feed_path = self.root / 'debian/dists/trixie/build.json'
        publication.write(self.feed_path, dict(targets={'amd64': self.info}))
        self.offline = patch.object(repository, 'content', side_effect=AssertionError('Rendering must use recorded facts only'))
        self.offline.start()
        self.addCleanup(self.offline.stop)
        return None

    def work(self, project, status='running', revision='2', tag='v1.0.0'):
        capture = project + '-new'
        self.state['runs'][capture] = dict(run_id=capture, revisions={project: revision},
            context=dict(projects=self.graph, release_project=project, tag=tag, cause='release', cascade=capture),
            sources={self.target: {project: {f'refs/tags/{tag}': 'f' * 40}}},
            nodes={self.target + '/' + project: dict(status=status, reason='fixture reason')})
        return None

    def page(self, project):
        publication.render(self.root, self.state)
        return (self.root / ('status/' + project + '.md')).read_text()

    def test_indirect_diamond_waits_name_immediate_arms_before_join_capture(self):
        self.work('core')
        before = copy.deepcopy(self.state)
        page = self.page('join')
        self.assertIn('Waiting for <a href="app.md#banner">App</a>, <a href="side.md#banner">Side</a>', page)
        self.assertIn('Waiting for <a href="core.md#banner">Core</a>', self.page('app'))
        self.assertNotIn('<code>1.0.0-2~trixie</code>', page)
        self.assertNotIn('alt="current"', page)
        self.assertNotIn('alt="outdated"', page)
        self.assertEqual(self.state, before)
        for line in (line for line in page.splitlines() if line.startswith('<tr><td ')):
            cells = re.findall(r'<td align="([^"]+)">(.*?)</td>', line)
            self.assertEqual(len(cells), 5)
            self.assertTrue(all(align == ('center' if value == '—' else 'left') for align, value in cells))
        self.assertEqual(self.state['runs']['old']['revisions']['join'], '1')
        return None

    def test_failed_arm_blocks_then_running_arm_waits_then_completion_is_centered(self):
        self.work('side', 'failed')
        self.assertIn('Blocked: <a href="side.md#banner">Side</a> failed', self.page('join'))
        self.assertIn('alt="blocked"', self.page('join'))
        self.state['runs']['side-new']['nodes'][self.target + '/side']['status'] = 'running'
        self.assertIn('Waiting for <a href="side.md#banner">Side</a>', self.page('join'))
        self.state['runs'].pop('side-new')
        page = self.page('join')
        self.assertIn('<td align="center">—</td>', page)
        self.assertNotIn('Waiting for ', page.split('<table>', 1)[1].split('</table>', 1)[0])
        return None

    def test_older_direct_activity_does_not_change_highest_pages(self):
        before = self.page('join')
        self.work('side', 'failed', revision='99', tag='v0.9.0')
        self.assertEqual(before, self.page('join'))
        return None

    def test_running_and_terminal_own_work_keep_their_icons_and_labels(self):
        self.work('core')
        for status in ['running', 'publishing', 'failed', 'cancelled', 'skipped', 'superseded', 'unsatisfiable', 'pending']:
            with self.subTest(status=status):
                self.work('join', status)
                page = self.page('join').split('<table>', 1)[1].split('</table>', 1)[0]
                self.assertIn('alt="' + status + '"', page)
                self.assertIn('<td align="left"><img ', page)
                self.assertIn('<code>1.0.0-2~trixie</code>', page)
        return None

    def test_direct_pending_work_does_not_acquire_the_cascade_wait_policy(self):
        self.work('core')
        self.work('join', 'pending')
        page = self.page('join').split('<table>', 1)[1].split('</table>', 1)[0]
        self.assertIn('Pending <code>1.0.0-2~trixie</code>', page)
        self.assertNotIn('Waiting for ', page)
        self.state['runs']['join-new']['context']['cause'] = 'dependent'
        self.assertIn('Waiting for <a href="app.md#banner">App</a>, <a href="side.md#banner">Side</a>', self.page('join'))
        return None

    def test_indirect_failed_root_is_explained_on_the_immediate_prerequisite_page(self):
        self.work('core', 'failed')
        self.assertIn('Blocked: <a href="app.md#banner">App</a>, <a href="side.md#banner">Side</a>', self.page('join'))
        self.assertIn('Blocked: <a href="core.md#banner">Core</a> failed', self.page('app'))
        return None

    def test_waits_are_row_scoped(self):
        for config in self.graph.values():
            config['matrix']['linux'][0]['architectures'] = ['amd64', 'arm64']
        other = next(r for r in repository.rows(self.graph['core']) if r['arch'] == 'arm64')
        self.state['runs']['old']['sources'][other['id']] = self.sources
        for project in self.graph:
            self.state['runs']['old']['nodes'][other['id'] + '/' + project] = dict(status='published')
        publication.write(self.feed_path, dict(targets=dict(amd64=self.info, arm64=self.info)))
        self.work('core')
        page = self.page('join')
        rows = [line for line in page.splitlines() if line.startswith('<tr><td ')]
        self.assertEqual(len(rows), 2)
        self.assertIn('Waiting for ', rows[0])
        self.assertIn('<code>arm64</code>', rows[1])
        self.assertEqual(re.findall(r'<td[^>]*>(.*?)</td>', rows[1])[3], '—')
        return None

    def published_app_with_holder(self, revision, source, reserved=None):
        self.work('app', 'published', revision=revision)
        self.state['runs']['old']['revisions'].pop('app')
        self.state['runs']['old']['nodes'][self.target + '/app'] = dict(status='running', source=dict(run=source, attempt=1))
        if reserved is not None:
            self.state['allocations'] = {str(source): {'app': reserved}}
        release = self.info['releases']['app']['v1.0.0']
        release.update(revision=revision, versions={'app': f'1.0.0-{revision}~trixie'}, sources={'app': {'refs/tags/v1.0.0': 'f' * 40}})
        release['publications']['app'].update(capture='app-new', revision=revision)
        publication.write(self.feed_path, dict(targets={'amd64': self.info}))
        return None

    def test_registered_child_is_the_only_display_authority_during_holder_lag(self):
        self.published_app_with_holder('2', 'app-new', reserved='2')
        before = copy.deepcopy(self.state)
        row = next(line for line in self.page('app').splitlines() if line.startswith('<tr><td '))
        self.assertEqual(re.findall(r'<td[^>]*>(.*?)</td>', row)[3], '—')
        self.assertEqual(self.state, before)
        return None

    def test_older_held_allocation_does_not_override_a_newer_published_revision(self):
        self.published_app_with_holder('3', 'unregistered-capture', reserved='2')
        self.state['runs']['old']['nodes'][self.target + '/app']['status'] = 'failed'
        row = next(line for line in self.page('app').splitlines() if line.startswith('<tr><td '))
        self.assertEqual(re.findall(r'<td[^>]*>(.*?)</td>', row)[3], '—')
        self.assertIn('<code>1.0.0-3~trixie</code>', row)
        return None

    def test_newer_unregistered_capture_is_still_displayed_without_inventing_its_version(self):
        self.published_app_with_holder('1', 'unregistered-capture', reserved='2')
        row = next(line for line in self.page('app').splitlines() if line.startswith('<tr><td '))
        self.assertIn('Building capture', row)
        self.assertNotIn('<code>1.0.0-2~trixie</code>', row)
        return None

    def test_current_root_capture_failure_is_visible_without_fabricated_revision(self):
        self.state['runs']['old']['nodes'][self.target + '/app'].update(status='failed', reason='Capture failed')
        self.state['runs']['old-app'] = copy.deepcopy(self.state['runs']['old']) | dict(run_id='old-app', revisions={'app': '1'})
        self.state['runs']['old']['revisions'].pop('app')
        page = self.page('app')
        self.assertIn('Failed capture', page)
        self.assertNotIn('<code>1.0.0-2~trixie</code>', page)
        self.assertIn('Blocked: <a href="app.md#banner">App</a> failed', self.page('join'))
        return None




    def test_dropped_prerequisite_row_does_not_create_a_wait(self):
        self.work('core', revision='2', tag='v2.0.0')
        generation = self.state['runs']['core-new']
        generation['context']['projects'] = copy.deepcopy(self.graph)
        config = generation['context']['projects']['core']
        config['matrix']['linux'][0]['architectures'] = ['arm64']
        other = repository.rows(config)[0]
        generation['sources'] = {other['id']: {'core': {'refs/tags/v2.0.0': 'f' * 40}}}
        generation['nodes'] = {other['id'] + '/core': dict(status='published')}
        before = copy.deepcopy(self.state)
        page = self.page('app')
        row = next(line for line in page.splitlines() if line.startswith('<tr><td '))
        self.assertEqual(self.state, before)
        self.assertNotIn('<code>amd64</code>', self.page('core'))
        self.assertEqual(re.findall(r'<td[^>]*>(.*?)</td>', row)[3], '—')
        return None

    def test_satisfied_direct_recovery_hides_terminal_unallocated_capture(self):
        self.published_app_with_holder('3', 'unregistered-failed-capture')
        holder = self.state['runs']['old']['nodes'][self.target + '/app']
        holder.update(status='failed', category='configuration', reason='Capture failed before reserve', requires=['core'],
                      dependencies='a' * 64, builds=1)
        child = self.state['runs']['app-new']['nodes'][self.target + '/app']
        child.update(requires=['core'], dependencies='a' * 64)
        before = copy.deepcopy(self.state)
        page = self.page('app')
        row = next(line for line in page.splitlines() if line.startswith('<tr><td '))
        self.assertEqual(self.state, before)
        self.assertTrue(publication.row_activity(self.row, self.info, publication.projection(self.state))['app']['current'])
        self.assertEqual(re.findall(r'<td[^>]*>(.*?)</td>', row)[3], '—')
        return None

    def test_terminal_capture_with_different_binding_remains_visible(self):
        self.published_app_with_holder('3', 'unregistered-failed-capture')
        self.state['runs']['old']['nodes'][self.target + '/app'].update(status='failed', dependencies='a' * 64)
        self.state['runs']['app-new']['nodes'][self.target + '/app']['dependencies'] = 'b' * 64
        self.assertIn('Failed capture', self.page('app'))
        return None

    def test_newer_failed_reserved_capture_remains_visible_at_equal_binding(self):
        self.published_app_with_holder('3', 'unregistered-failed-capture', reserved='4')
        self.state['runs']['old']['nodes'][self.target + '/app'].update(status='failed', dependencies='a' * 64)
        self.state['runs']['app-new']['nodes'][self.target + '/app']['dependencies'] = 'a' * 64
        self.assertIn('Failed capture', self.page('app'))
        return None


class ControlPagePipelineTest(CoordinatorCase):
    def test_retry_with_retained_artifact_keeps_its_real_source_job(self):
        key = self.row['id'] + '/snode.c'
        source = dict(run=42, attempt=1)
        artifact = dict(id=44, digest='sha256:' + 'a' * 64)
        log = 'https://github.com/SNodeC/snode.c/actions/runs/42/job/43'
        self.state['runs']['100'].setdefault('nodes', {})[key] = dict(status='failed', source=source, artifact=artifact,
            job=43, job_url=log, builds=1, publications=1)
        self.save()
        state = dispatch.transaction(self.root, dict(retry='100/snode.c/' + self.row['id']))
        node = state['runs']['100']['nodes'][key]
        dispatch.run('bash', str(repository.ROOT / 'ci/publish/status.sh'), str(self.root), 'project')
        page = self.git('--git-dir=' + str(self.remote), 'show', 'main:status/snodec.md')
        self.assertEqual((node['source'], node['artifact'], node['job'], node['job_url']), (source, artifact, 43, log))
        self.assertEqual(node['status'], 'publishing')
        self.assertIn(log, page.split('### Debian trixie', 1)[1])
        self.assertEqual(self.posts, [])
        return None

    def test_control_retry_drops_previous_source_job_link_before_admission(self):
        key = self.row['id'] + '/snode.c'
        old_link = 'https://github.com/SNodeC/snode.c/actions/runs/42/job/43'
        node = self.state['runs']['100'].setdefault('nodes', {}).setdefault(key, {})
        node.update(status='failed', category='deterministic', reason='Previous source failed', source=dict(run=42, attempt=1),
                    job=43, job_url=old_link, builds=1, publications=0, request={'intent':'old'})
        self.save()
        original_api = self.api
        def api(path, *args, **kwargs):
            result = {'permission':'write'} if '/collaborators/' in path else original_api(path, *args, **kwargs)
            return result
        with patch.object(dispatch.sys, 'argv', ['dispatch', 'control', str(self.root)]), \
                patch.object(dispatch, 'api', side_effect=api), \
                patch.object(dispatch, 'capture_bundle', side_effect=lambda capture, bundles: self.bundles[capture]), \
                patch.object(dispatch, 'capacity', return_value=(0, {})), \
                patch.dict(os.environ, GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_ACTOR='test-operator',
                           GITHUB_TRIGGERING_ACTOR='test-operator', PACKAGE_REPORT='', PACKAGE_RETRY='100/snode.c/' + self.row['id']):
            dispatch.main()
        state = publication.read(self.root / 'status.json')
        node = state['runs']['100']['nodes'][key]
        page = self.git('--git-dir=' + str(self.remote), 'show', 'main:status/snodec.md')
        section = page.split('### Debian trixie', 1)[1].split('### ', 1)[0]
        row = next(line for line in section.splitlines() if line.startswith('<tr><td ') and '<code>amd64</code>' in line)
        self.assertEqual(node['status'], 'pending')
        self.assertEqual(self.posts, [])
        self.assertNotIn('source', node)
        self.assertNotIn('request', node)
        self.assertEqual(page, (self.root / 'status/snodec.md').read_text().strip())
        self.assertNotIn(old_link, row)
        return None

    def test_control_command_projects_and_pushes_prerequisite_wait_pages(self):
        """Real tick, transactions, status.sh project and rendered bare-remote bytes."""
        for project, capture in [('mqttsuite', '200'), ('snode.c-idp', '300')]:
            self.add_capture(project, capture)
        self.feed(list(self.graph))
        info = publication.published(self.root, self.row)[0]
        for generation in self.state['runs'].values():
            for project in generation['revisions']:
                required = repository.dependencies(project, self.graph)
                generation.setdefault('nodes', {})[self.row['id'] + '/' + project] = dict(
                    status='published', requires=list(required), dependencies=repository.binding(info, required))
        self.save()
        self.add_capture('snode.c', '400', revision='3')
        with patch.object(dispatch.sys, 'argv', ['dispatch', 'control', str(self.root)]), \
                patch.object(dispatch, 'capture_bundle', side_effect=lambda capture, bundles: self.bundles[capture]), \
                patch.dict(os.environ, GITHUB_EVENT_NAME='workflow_run', PACKAGE_REPORT='', PACKAGE_RETRY=''):
            dispatch.main()
            first = self.git('--git-dir=' + str(self.remote), 'show', 'main:status/mqttsuite.md')
            self.assertIn('Waiting for <a href="snodec.md#banner">SNode.C</a>', first)
            self.runs['SNodeC/snode.c', 501]['status'] = 'in_progress'
            self.jobs['SNodeC/snode.c', 501][0]['status'] = 'in_progress'
            dispatch.main()
        state = publication.read(self.root / 'status.json')
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(state['runs']['400']['nodes'][self.row['id'] + '/snode.c']['status'], 'running')
        self.assertEqual(state['runs']['200']['revisions'], {'mqttsuite': '2'})
        page = self.git('--git-dir=' + str(self.remote), 'show', 'main:status/mqttsuite.md')
        self.assertEqual(page, (self.root / 'status/mqttsuite.md').read_text().strip())
        self.assertIn('Waiting for <a href="snodec.md#banner">SNode.C</a>', page)
        self.assertIn('<td align="left"><img src="badges/waiting.svg"', page)
        self.assertIn('<td align="center">—</td>', page)
        self.assertNotIn('alt="current"', page)
        self.assertNotIn('alt="outdated"', page)
        core = self.git('--git-dir=' + str(self.remote), 'show', 'main:status/snodec.md')
        self.assertIn('Building <code>1.0.0-3~trixie</code>', core)
        self.assertEqual(self.git('--git-dir=' + str(self.remote), 'show', 'main:status.json'),
                         (self.root / 'status.json').read_text().strip())
        return None


if __name__ == '__main__':
    unittest.main()
