"""Recorded filesystem facts drive all package-status presentation."""
import copy
import os
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
            for project in repository.PROJECTS:
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

    def test_openwrt_release_specific_architectures_and_buttons(self):
        publication.render(self.root, self.state)
        first, second = self.text().split('### OpenWrt 24.10')[1].split('### OpenWrt 25.12')
        self.assertIn('`riscv64_riscv64`', first)
        self.assertNotIn('`riscv64_generic`', first)
        self.assertIn('`riscv64_generic`', second)
        self.assertIn('<a href="#openwrt-2410"><img src="menu/24-10.svg" alt="24.10" title="24.10" align="absmiddle"></a>', self.text())
        self.assertIn('src="../docs/media/menu/catalog.svg" alt="Catalog"', self.text())
        self.assertIn('align="absmiddle"', self.text())

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
        for anchor in ['2410', '2512', 'trixie', 'trixie-1', 'debian-trixie', 'rocky-linux-9']:
            self.assertIn(f'<a id="{anchor}"></a>', (self.root / 'docs/status.md').read_text())

    def test_third_project_requires_only_registry_entry(self):
        with patch.dict(repository.PROJECTS, {'new-project': dict(title='New project', package='new-package', depends_on=())}):
            publication.render(self.root, self.state)
        self.assertTrue((self.root / 'status/new-package.md').exists())
        self.assertNotIn('alt="Catalog"', self.text('new-package'))
        (self.root / 'docs/catalogs/new-package.md').write_text('New catalog')
        with patch.dict(repository.PROJECTS, {'new-project': dict(title='New project', package='new-package', depends_on=())}):
            publication.render(self.root, self.state)
        self.assertIn('src="../docs/media/menu/catalog.svg" alt="Catalog"', self.text('new-package'))
        for path in ['README.md', 'status/README.md']:
            self.assertIn('[New project](https://github.com/SNodeC/new-project#project-overview)', (self.root / path).read_text())

    def test_distribution_guides_choose_before_install_and_match_the_menu(self):
        headings = ['Requirements', 'Choose packages', 'Quick install', 'Manual repository setup', 'Updates', 'Source records', 'Troubleshooting']
        for name in ['debian', 'ubuntu', 'fedora', 'rocky-linux', 'raspberry-pi-os', 'openwrt']:
            with self.subTest(guide=name):
                text = (repository.ROOT / f'site/docs/installation/{name}.md').read_text()
                self.assertEqual([line[3:] for line in text.splitlines() if line.startswith('## ')], headings)
                menu = next(block.split('</p>', 1)[0] for block in text.split('<p>')[1:] if 'href="#requirements"' in block)
                anchors = ['requirements', 'choose-packages', 'quick-install', 'manual-repository-setup', 'updates']
                self.assertEqual(sorted(anchors, key=lambda anchor: menu.index(f'href="#{anchor}"')), anchors)
                self.assertIn('alt="Complete sets" align="absmiddle"', text)
                self.assertIn('href="#complete-sets"', text)
                self.assertIn('alt="Selected packages" align="absmiddle"', text)
                self.assertIn('href="#selected-packages"', text)
                self.assertLess(text.index('## Choose packages'), text.index('### Complete sets'))
                self.assertIn('--prepare', text)
                self.assertNotIn('automatically. ##', text)

    def test_catalogs_have_buttons_and_queries_for_all_package_managers(self):
        for package in ['snodec', 'mqttsuite']:
            text = (repository.ROOT / f'site/docs/catalogs/{package}.md').read_text()
            self.assertNotIn('## Installation and availability', text)
            self.assertIn('[![Use](../media/menu/use.svg)](#after-installation)', text)
            self.assertIn('## After installation', text)
            for label in ['Install', 'Status', 'Catalog', 'Details', 'Query', 'Use']:
                self.assertIn(f'[![{label}]', text)
            self.assertIn(f"opkg list '{package}*'", text)
            self.assertIn(f"apk search '{package}*'", text)
        mqtt = (repository.ROOT / 'site/docs/catalogs/mqttsuite.md').read_text()
        self.assertIn('mqttsuite/blob/HEAD/docs/guides/deployment.md#page-overview', mqtt)

    def test_hub_and_keys_have_one_fingerprint_authority_and_consistent_apt_setup(self):
        hub = (repository.ROOT / 'site/README.md').read_text()
        keys = (repository.ROOT / 'site/keys/README.md').read_text()
        self.assertNotIn('8BBFD49E3C826FDB1416C79E60046744B15B0E05', hub)
        self.assertIn('8BBFD49E3C826FDB1416C79E60046744B15B0E05', keys)
        self.assertIn('ASCII-armored key unchanged', keys)
        self.assertNotIn('dearmor', keys)
        self.assertNotIn('| Key | Distributions', keys)
        self.assertIn('snodec-opkg.pub', keys)
        self.assertIn('snodec-usign.pub', keys)
        self.assertIn('architecture-independent', keys)
        self.assertIn('troubleshooting.md#page-overview)\n\nThese are public', keys)
        for name in ['debian', 'ubuntu', 'raspberry-pi-os']:
            guide = (repository.ROOT / f'site/docs/installation/{name}.md').read_text()
            self.assertIn('sudo install -m 644 "$tmp/key" /etc/apt/keyrings/snodec.asc', guide)
            self.assertNotIn('tee /etc/apt/keyrings/snodec.asc', guide)
            self.assertIn('signed-by=/etc/apt/keyrings/snodec.asc', guide)
        self.assertIn('/docs/ /status/', (repository.ROOT / 'ci/publish/status.sh').read_text())

    def test_public_pages_separate_html_blocks_and_use_real_menu_assets(self):
        import re
        import xml.etree.ElementTree as ET
        for path in (repository.ROOT / 'site').rglob('*.md'):
            text = path.read_text()
            self.assertNotRegex(text, r'</p>\n[^\n<]')
            self.assertIn('project-overview' if path == repository.ROOT / 'site/README.md' else 'page-overview', text)
            for image in re.findall(r'(?:src="|!\[[^\]]*\]\()([^"\)]+\.svg)', text):
                target = path.parent / image
                self.assertTrue(target.is_file(), f'{path}: {image}')
                if '/menu/' in image:
                    svg = ET.fromstring(target.read_text())
                    label = svg.find('{http://www.w3.org/2000/svg}text')
                    self.assertEqual(label.attrib['font-size'], '16')
                    self.assertEqual(label.attrib['font-weight'], '600')
                    for arrow in svg.findall('{http://www.w3.org/2000/svg}path'):
                        self.assertIn('M0 1.25H5.5V0L9 2L5.5 4V2.75H0Z', arrow.attrib['d'])
                        self.assertRegex(arrow.attrib['transform'], r'translate\(\d+ 12\)')
        for asset, height in [('banner.svg', '320'), ('nav/banner-installation.svg', '56'), ('nav/banner-installation-compact.svg', '72')]:
            svg = ET.fromstring((repository.ROOT / 'site/docs/media' / asset).read_text())
            self.assertEqual(svg.attrib['height'], height)

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

    def test_circles_keep_size_and_requested_palette(self):
        publication.render(self.root, self.state)
        for label, color in [('current', '#1a7f37'), ('outdated', '#9a6700'), ('publishing', '#8250df'), ('cancelled', '#24292f'), ('skipped', '#9a6700')]:
            svg = (self.root / f'status/badges/{label}.svg').read_text()
            self.assertIn(f'fill="{color}"', svg)
            self.assertIn('cy="7.8" r="6"', svg)
            self.assertNotIn('<text', svg)

    def test_public_render_command_preserves_authoritative_state(self):
        self.feed()
        self.event('snode.c', 'running')
        publication.write(self.root / 'status.json', self.state)
        before = (self.root / 'status.json').read_bytes()
        subprocess.run(['python3', '-m', 'ci.publish.publication', 'render', str(self.root)], cwd=repository.ROOT, check=True)
        self.assertEqual((self.root / 'status.json').read_bytes(), before)
        self.assertIn('2.0.0 · r9', self.text())

    def test_manual_workflow_only_renders_with_existing_publication_concurrency(self):
        workflow = (repository.ROOT / '.github/workflows/render-status.yml').read_text()
        self.assertIn('workflow_dispatch:', workflow)
        self.assertNotIn('schedule:', workflow)
        self.assertNotIn('push:', workflow)
        self.assertIn('group: package-publication', workflow)
        self.assertIn('github.event.repository.default_branch', workflow)
        self.assertIn('status.sh published render', workflow)
        self.assertNotIn('SIGNING_KEY:', workflow)

    def test_current_doc_overlay_preserves_capture_pinned_executables(self):
        workflow = (repository.ROOT / '.github/workflows/release.yml').read_text()
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
        env = os.environ | {'RUNNER_TEMP': str(tmp), 'GITHUB_ENV': str(self.root / 'env')}
        subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', 'commit=' + commit + '\n' + shell], cwd=self.root, env=env, check=True, capture_output=True)
        self.assertEqual((current / 'README.md').read_bytes(), (repository.ROOT / 'site/README.md').read_bytes())
        self.assertFalse((current / 'docs/old.md').exists())
        self.assertEqual((current / 'tool.py').read_text(), 'CAPTURED')


    def test_navigation_legend_geometry_and_generated_asset_ownership(self):
        import re
        import xml.etree.ElementTree as ET
        self.feed()
        publication.render(self.root, self.state)
        (self.root / 'status/menu/obsolete.svg').write_text('obsolete')
        publication.render(self.root, self.state)
        text = self.text()
        self.assertLess(text.index('# SNode.C package status'), text.index('alt="Install"'))
        self.assertNotIn('alt="All projects"', text)
        self.assertLess(text.index('[Legend](#legend)'), text.index('| Architecture |'))
        legend = text.split('**Legend:**', 1)[1].split('\n\n', 1)[0]
        self.assertEqual(len(re.findall(r'<img ', legend)), 11)
        self.assertIn('title="Not built"', legend)
        self.assertNotIn('alt="not-built"', legend)
        self.assertIn('&nbsp;Not&nbsp;built', legend)
        self.assertEqual(text.count('alt="↑ menu"'), 13)
        self.assertEqual(text.count('alt="Install guide"'), 6)
        self.assertEqual(len(re.findall(r'^\*\*.*?<a ', text, re.M)), 6)
        self.assertEqual(sum(line.count('<img ') for line in text.splitlines() if line.startswith('**') and 'src="menu/' in line), 13)
        self.assertIn('src="../docs/media/menu/install.svg" alt="Install" align="absmiddle"', text)
        self.assertIn('src="../docs/media/menu/troubleshoot.svg" alt="Troubleshoot" align="absmiddle"', text)
        referenced = set()
        for page in list((self.root / 'status').glob('*.md')) + [self.root / 'docs/status.md']:
            referenced.update((page.parent / name).resolve() for name in re.findall(r'src="([^\"]*menu/[^\"]+\.svg)"', page.read_text()) if (page.parent / name).resolve().parent == (self.root / 'status/menu').resolve())
        self.assertEqual(referenced, {p.resolve() for p in (self.root / 'status/menu').glob('*.svg')})
        for name in ['menu', 'install-guide']:
            svg = ET.fromstring((self.root / f'status/menu/{name}.svg').read_text())
            arrow = svg.find('{http://www.w3.org/2000/svg}path')
            self.assertEqual(arrow.attrib['d'], 'M0 1.25H5.5V0L9 2L5.5 4V2.75H0Z')
            self.assertTrue(arrow.attrib['transform'].startswith('translate(143 12)'))
            self.assertEqual(arrow.attrib['aria-hidden'], 'true')
        legacy = (self.root / 'docs/status.md').read_text()
        for ordered in [('Debian trixie', 'Debian forky', 'Debian sid'), ('Rocky Linux 9', 'Rocky Linux 10')]:
            self.assertEqual(sorted(ordered, key=legacy.index), list(ordered))

    def test_shared_page_headers_and_unified_menu_geometry(self):
        import re
        import xml.etree.ElementTree as ET
        publication.render(self.root, self.state)
        pages = [*self.root.glob('status/*.md'), self.root / 'docs/status.md']
        for page in pages:
            with self.subTest(page=page.name):
                text = page.read_text()
                self.assertEqual(text.count('<!-- snodec:begin page-header -->'), 1)
                header = text.split('<!-- snodec:begin page-header -->')[1].split('<!-- snodec:end page-header -->')[0]
                self.assertEqual(len(re.findall(r'<a href=', header)), 3)
                self.assertLess(header.index('title="Up to '), header.index('title="SNodeC organization"'))
                self.assertLess(header.index('title="SNodeC organization"'), header.index('title="Packages repository"'))
                self.assertEqual(header.count('align="right"'), 2)
                self.assertIn('<br clear="all">', header)
                self.assertIn('<source media="(max-width: 640px)"', header)
                self.assertNotIn('page-banner.svg', text)
                self.assertNotIn('alt="All projects"', text)
        for path in (self.root / 'status/menu').glob('*.svg'):
            svg = ET.fromstring(path.read_text())
            self.assertEqual((svg.attrib['width'], svg.attrib['height']), ('160', '28'))

    def test_direct_selection_routes_lossless_catalog_and_truthful_references(self):
        import re
        catalog = (repository.ROOT / 'site/docs/catalogs/snodec.md').read_text()
        names = set('''snodec-common snodec snodec-apps snodec-control snodec-logger
snodec-utils snodec-core-mux-epoll snodec-core-mux-poll snodec-core-mux-select snodec-core
snodec-core-socket snodec-core-socket-stream snodec-core-socket-stream-legacy snodec-core-socket-stream-tls snodec-db-mariadb
snodec-net snodec-net-in snodec-net-in-phy snodec-net-in-phy-stream snodec-net-in-stream
snodec-net-in-stream-legacy snodec-net-in-stream-tls snodec-net-in6 snodec-net-in6-phy snodec-net-in6-phy-stream
snodec-net-in6-stream snodec-net-in6-stream-legacy snodec-net-in6-stream-tls snodec-net-l2 snodec-net-l2-phy
snodec-net-l2-phy-stream snodec-net-l2-stream snodec-net-l2-stream-legacy snodec-net-l2-stream-tls snodec-net-rc
snodec-net-rc-phy snodec-net-rc-phy-stream snodec-net-rc-stream snodec-net-rc-stream-legacy snodec-net-rc-stream-tls
snodec-net-un snodec-net-un-phy snodec-net-un-phy-stream snodec-net-un-stream snodec-net-un-stream-legacy
snodec-net-un-stream-tls snodec-net-un-dgram snodec-http snodec-http-server snodec-http-client
snodec-http-server-express snodec-http-server-express-legacy-in snodec-http-server-express-legacy-in6 snodec-http-server-express-legacy-rc snodec-http-server-express-legacy-un
snodec-http-server-express-tls-in snodec-http-server-express-tls-in6 snodec-http-server-express-tls-rc snodec-http-server-express-tls-un snodec-websocket
snodec-websocket-server snodec-websocket-client snodec-mqtt snodec-mqtt-server snodec-mqtt-client
snodec-mqtt-server-websocket snodec-mqtt-client-websocket'''.split())
        self.assertEqual(len(names), 67)
        self.assertEqual(names, set(re.findall(r'`(snodec(?:-[a-z0-9-]+)?)`', catalog)))
        for name in ['debian', 'ubuntu', 'raspberry-pi-os', 'fedora', 'rocky-linux', 'openwrt']:
            text = (repository.ROOT / f'site/docs/installation/{name}.md').read_text()
            self.assertIn('<a id="install-selected-components"></a>\n\n```sh', text)
            self.assertIn('href="#install-selected-components"', text)
            self.assertEqual(text.count('href="#selected-packages"'), 1)
            self.assertEqual(text.count('**Check**'), 3)
            self.assertEqual(text.count('Next: '), 3)
            self.assertIn('../../keys/README.md#installed-keys', text)
            records = text.split('## Source records')[1].split('## Troubleshooting')[0]
            self.assertIn('`build.json`', records)
            self.assertIn('**Build log**', records)
            self.assertIn('**Packages**', records)
        keys = (repository.ROOT / 'site/keys/README.md').read_text()
        self.assertIn('### Installed keys', keys)
        self.assertIn('/etc/opkg/keys/*', keys)
        self.assertNotIn('maintainers edit', keys)
        self.assertIn('separate trusted channel', keys)


if __name__ == '__main__':
    unittest.main()
