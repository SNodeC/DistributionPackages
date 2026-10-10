"""Check packaging boundaries without building applications or contacting GitHub."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ci import repository
from ci.publish import cleanup, publication


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
        for name in ['snodec-openwrt-build-deps-2.0.0-r124.tar.zst', 'snodec-core_2.0.0-124~trixie_arm64.deb']:
            self.assertTrue(repository.project_file(name, 'snode.c'))
            self.assertFalse(repository.project_file(name, 'mqttsuite'))

    def test_openwrt_uses_captured_recipe_and_published_dependency_recipe(self):
        import shutil
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feed, bundle, dependencies = (root / name for name in ('feed', 'bundle', 'dependencies'))
            shutil.copytree(repository.ROOT / 'ci', feed / 'ci')
            (feed / 'keys').mkdir()
            for name in ('snodec-usign.pub', 'snodec-apk.pem'):
                (feed / 'keys' / name).write_text('test public key')
            # A stale recipe next to the CI tools must never be selected.
            (feed / 'net/snode.c').mkdir(parents=True)
            (feed / 'net/snode.c/Makefile').write_text('wrong recipe')
            bundle.mkdir()
            dependencies.mkdir()
            binary = root / 'bin'
            binary.mkdir()
            (binary / 'python3').write_text(
                '#!/bin/sh\nif [ "$1 $2 $3" = "-m ci.repository check" ]; then exit 0; fi\n'
                f'exec "{sys.executable}" "$@"\n')
            # Stop at the SDK configuration boundary; no toolchain build or network.
            (binary / 'make').write_text('#!/bin/sh\ntest "$1" = defconfig || exit 1\nexit 37\n')
            for path in binary.iterdir():
                path.chmod(0o755)
            env = os.environ | {'PATH': str(binary) + ':' + os.environ['PATH'],
                                'PACKAGE_RELEASE': '1',
                                'PYTHONDONTWRITEBYTECODE': '1'}
            info = dict(release='25.12.5', target='mediatek/filogic', arch='aarch64_cortex-a53', sha256='sdk')
            baseline = {}
            for project, parent in [('snode.c', 'supplement'), ('mqttsuite', 'misc')]:
                with self.subTest(project=project):
                    source, sdk = root / ('source-' + project), root / ('sdk-' + project)
                    recipe = source / parent / 'openwrt'
                    (recipe / 'files').mkdir(parents=True)
                    (recipe / 'Makefile').write_text('captured ' + project)
                    (recipe / 'Config.in').write_text('config for ' + project)
                    (recipe / 'files/helper.sh').write_text('#!/bin/sh\nexit 0\n')
                    (recipe / 'files/helper.sh').chmod(0o755)
                    archive = bundle / (project + '-2.0.0.tar.gz')
                    repository.run('tar', '-czf', str(archive), '--exclude=.git',
                                   f'--transform=s,^,{project}-2.0.0/,', '-C', str(source), '.')
                    (sdk / 'scripts').mkdir(parents=True)
                    (sdk / 'staging_dir').mkdir()
                    (sdk / 'feeds.conf.default').write_text('')
                    (sdk / 'scripts/feeds').write_text(
                        '#!/bin/sh\nset -eu\ntest -f "recipes/$BUILD_PROJECT/Makefile"\n'
                        'if [ "$BUILD_PROJECT" = mqttsuite ]; then\n'
                        '  test -f recipes/snode.c/Makefile\n'
                        '  test -f staging_dir/target-test/usr/include/snodec.h\nfi\n')
                    (sdk / 'scripts/feeds').chmod(0o755)
                    publication.write(sdk / 'ci-sdk.json', info)
                    publication.write(bundle / 'baseline.json', baseline)
                    publication.write(bundle / 'context.json', dict(build_project=project,
                                      versions={project: '2.0.0'}, source_tags={project: 'v2.0.0'}))
                    result = subprocess.run(['bash', str(feed / 'ci/build/openwrt.sh'), str(feed),
                                             str(bundle), str(sdk)], env=env | {'BUILD_PROJECT': project},
                                            text=True, capture_output=True)
                    self.assertEqual(result.returncode, 37, result.stderr)
                    self.assertEqual((sdk / 'recipes' / project / 'Makefile').read_text(), 'captured ' + project)
                    self.assertEqual((sdk / 'recipes' / project / 'Config.in').read_bytes(), (recipe / 'Config.in').read_bytes())
                    self.assertEqual((sdk / 'recipes' / project / 'files/helper.sh').stat().st_mode & 0o777, 0o755)
                    self.assertIn(f'src-link snodec {sdk}/recipes', (sdk / 'feeds.conf').read_text())
                    selections = [line for line in (sdk / '.config').read_text().splitlines()
                                  if line.startswith('CONFIG_PACKAGE_')]
                    self.assertEqual(selections, ['CONFIG_PACKAGE_' + project.replace('.', '') + '=m'])
                    self.assertFalse((sdk / 'key-build').exists())
                    self.assertFalse((sdk / 'private-key.pem').exists())
                    self.assertIn('# CONFIG_SIGNED_PACKAGES is not set', (sdk / '.config').read_text())
                    if project == 'snode.c':
                        target = sdk / 'staging_dir/target-test'
                        for name in ('usr/include', 'usr/lib', 'pkginfo'):
                            (target / name).mkdir(parents=True)
                        (target / 'usr/include/snodec.h').write_text('public header')
                        (target / 'usr/lib/snodec.cmake').write_text(str(sdk) + '/staging_dir/target-test/usr/lib')
                        (target / 'pkginfo/snodec.provides').write_text('libsnodec.so')
                        with patch.dict(os.environ, {'PACKAGE_RELEASE': '1'}):
                            repository.sdk_dependency(sdk, bundle, dependencies)
                        archive, = sdk.glob('snodec-openwrt-build-deps-*.tar.zst')
                        shutil.copy2(archive, dependencies / archive.name)
                        baseline = info | {'files': {archive.name: repository.digest(archive)}}
                    else:
                        self.assertEqual((sdk / 'recipes/snode.c/Makefile').read_text(), 'captured snode.c')
                        self.assertEqual((sdk / 'staging_dir/target-test/usr/lib/snodec.cmake').read_text(),
                                         str(sdk) + '/staging_dir/target-test/usr/lib')
                        self.assertEqual((sdk / 'staging_dir/target-test/pkginfo/snodec.provides').read_text(), 'libsnodec.so')
                        self.assertEqual(sorted(p.name for p in (sdk / 'recipes').iterdir()), ['mqttsuite', 'snode.c'])

    def test_status_render_is_immutable_and_does_not_copy_documentation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'status').mkdir()
            (root / 'status/old-target.svg').write_text('obsolete')
            publication.render(root, {'targets': {}})
            before = {p.name: p.read_bytes() for p in (root / 'status/badges').iterdir()}
            self.assertEqual(len(before), 9)
            for svg in before.values():
                self.assertIn(b'width="86" height="20"', svg)
                self.assertIn(b'<text x="43.0"', svg)
            (root / 'status/badges/pending.svg').write_text('previous badge design')
            self.assertFalse((root / 'status/old-target.svg').exists())
            state = dict(targets={})
            row = publication.targets()[0]
            generation = dict(revisions={'snode.c':'1'},run_id='one',run_url='url')
            publication.update(state,row,generation,'snode.c','running',1)
            publication.render(root,state)
            self.assertEqual(before,{p.name:p.read_bytes() for p in (root/'status/badges').iterdir()})
            text=(root/'docs/status.md').read_text()
            self.assertIn('![snode.c: running](../status/badges/running.svg)',text)
            self.assertEqual(text.count('| Architecture | SNode.C | MQTTSuite |'),
                             len({(r['distribution'], r['suite']) for r in publication.targets()}))
            self.assertEqual(sum(line.startswith('| `') for line in text.splitlines()),
                             len(publication.targets()))
            self.assertIn('[trixie](#debian-trixie)', text)
            self.assertIn('### Debian trixie', text)
            self.assertIn('<a id="trixie-1"></a>', text)
            self.assertIn('Unfinished or unsuccessful attempts', text)
            self.assertIn('SNode.C: running', text)
            self.assertNotIn('../status/'+row['id'],text)
            self.assertFalse((root/'README.md').exists())
            self.assertFalse((root/'install').exists())
            self.assertEqual(list((root/'docs').iterdir()),[root/'docs/status.md'])

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
            self.assertEqual(publication.read(root / 'status.json')['counters'], {'snode.c': 128, 'mqttsuite': 130})
            self.assertEqual(publication.reserve(root, 'snode.c', 'two'), {'snode.c': '129', 'mqttsuite': '131'})
            before = (root / 'status.json').read_bytes()
            self.assertEqual(publication.reserve(root, 'mqttsuite', 'one'), {'mqttsuite': '130'})
            self.assertEqual((root / 'status.json').read_bytes(), before)
            self.assertEqual(publication.reserve(root, 'mqttsuite', 'three'), {'mqttsuite': '132'})
            self.assertEqual(publication.read(root / 'status.json')['counters'], {'snode.c': 129, 'mqttsuite': 132})
            with self.assertRaisesRegex(RuntimeError, 'release project'):
                publication.reserve(root, 'snode.c', 'one')
            self.assertEqual(publication.read(root / 'status.json')['counters'], {'snode.c': 129, 'mqttsuite': 132})

    def test_fresh_repository_allocates_revision_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(publication.reserve(root, 'snode.c', 'first'), {'snode.c': '1', 'mqttsuite': '1'})
            self.assertEqual(publication.read(root / 'status.json')['counters'], {'snode.c': 1, 'mqttsuite': 1})

    def test_reset_counters_override_history_and_published_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = publication.targets()[0]
            publication.write(root / publication.feed_paths(row)[0] / 'build.json',
                              {'versions': {'snodec': '2.0.0-r150', 'mqttsuite': '1.0.2-r170'}})
            publication.write(root / 'status.json', {
                'counters': {'snode.c': 0, 'mqttsuite': 0},
                'allocations': {'old': {'snode.c': '200', 'mqttsuite': '250'}},
                'runs': {'old': {'revisions': {'snode.c': '200', 'mqttsuite': '250'}}}})
            self.assertEqual(publication.reserve(root, 'snode.c', 'fresh'), {'snode.c': '1', 'mqttsuite': '1'})
            state = publication.read(root / 'status.json')
            state['counters'] = {'snode.c': 7, 'mqttsuite': 0}
            publication.write(root / 'status.json', state)
            self.assertEqual(publication.reserve(root, 'snode.c', 'another'), {'snode.c': '8', 'mqttsuite': '1'})

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


class StatusEventsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        self.git('init','--bare','-b','main',str(self.remote))
        self.seed = self.clone('seed')
        (self.seed/'feed').write_text('original feed')
        publication.write(self.seed/'status.json',dict(repository='SNodeC/Packages',branch='main',counters={'snode.c':1,'mqttsuite':1},runs={},targets={}))
        self.git('add','.',cwd=self.seed)
        self.git('commit','-m','seed',cwd=self.seed)
        self.git('push','origin','main',cwd=self.seed)
        self.bundle=self.root/'bundle'
        self.rows=publication.targets()[:20]
        self.context=dict(run_id='100',run_url='https://example.invalid/100',destination='SNodeC/Packages',release_project='snode.c')
        for name,value in dict(context=self.context,targets=self.rows,revisions={'snode.c':'1','mqttsuite':'1'},sources={},profiles={}).items():
            publication.write(self.bundle/f'{name}.json',value)
        self.env=os.environ | {'GITHUB_RUN_ATTEMPT':'1','PYTHONPATH':str(repository.ROOT)}
        self.status_script=repository.ROOT/'ci/publish/status.sh'
        self.push_script=repository.ROOT/'ci/publish/push.sh'

    def git(self,*args,cwd=None):
        return subprocess.check_output(['git','-c','commit.gpgsign=false',*args],cwd=cwd or self.root,text=True,stderr=subprocess.DEVNULL).strip()

    def clone(self,name,sparse=False):
        path=self.root/name
        self.git('clone',str(self.remote),str(path))
        self.git('config','user.name','Test',cwd=path)
        self.git('config','user.email','test@example.invalid',cwd=path)
        if sparse:
            self.git('sparse-checkout','set','--no-cone','/status.json','/docs/status.md','/status/','**/build.json',cwd=path)
        return path

    def command(self,root,state='running',row=None,project='snode.c'):
        return ['python3','-m','ci.publish.publication','status',str(root),str(self.bundle),json.dumps(row or self.rows[0]),project,state]

    def event(self,root,state='running',row=None,project='snode.c',attempt=1):
        return subprocess.run(self.command(root,state,row,project),env=self.env | {'GITHUB_RUN_ATTEMPT':str(attempt)},capture_output=True,text=True,check=True)

    def snapshot(self):
        return json.loads(self.git('show','main:status.json',cwd=self.remote))

    def test_twenty_concurrent_writers_lose_no_events(self):
        jobs=[]
        for index,row in enumerate(self.rows):
            clone=self.clone('writer'+str(index))
            log=open(self.root/f'writer{index}.log','w+')
            self.addCleanup(log.close)
            command=['bash',str(self.status_script),str(clone),'status',str(self.bundle),json.dumps(row),'snode.c','running']
            jobs.append((subprocess.Popen(command,env=self.env,stdout=log,stderr=log),log))
        for process,log in jobs:
            self.assertEqual(process.wait(timeout=180),0)
            log.seek(0)
            self.assertNotIn('::warning::',log.read())
        state=self.snapshot()
        self.assertEqual(len(state['targets']),20)
        self.assertTrue(all(v['status']=='running' for v in state['targets'].values()))
        self.assertEqual(self.git('show','main:feed',cwd=self.remote),'original feed')
        # Status commits retain parents; the next feed publication creates the new orphan.
        self.assertEqual(self.git('rev-list','--count','main',cwd=self.remote),'21')
        self.assertEqual(self.git('rev-parse','main~20',cwd=self.remote),
                         self.git('rev-parse','HEAD',cwd=self.seed))

    def test_terminal_order_attempts_and_dependency_skip(self):
        self.event(self.seed,'failed')
        self.event(self.seed,'running')
        state=publication.read(self.seed/'status.json')
        key=self.rows[0]['id']
        self.assertEqual(state['targets'][key+'/snode.c']['status'],'failed')
        self.assertEqual(state['targets'][key+'/mqttsuite']['status'],'skipped')
        self.event(self.seed,'running',attempt=2)
        self.event(self.seed,'publishing',attempt=1)
        self.assertEqual(publication.read(self.seed/'status.json')['targets'][key+'/snode.c']['status'],'running')
        self.event(self.seed,'pending',attempt=2)
        self.assertEqual(publication.read(self.seed/'status.json')['targets'][key+'/snode.c']['status'],'running')

    def test_finalize_preserves_terminal_other_runs_and_attempts(self):
        for index,status in enumerate(['pending','running','publishing','published','failed','cancelled','skipped','superseded']):
            self.event(self.seed,status,self.rows[index],project='mqttsuite')
        self.event(self.seed,'running',self.rows[8],project='mqttsuite',attempt=2)
        for result in ['cancelled','failed']:
            baseline=(self.seed/'status.json').read_bytes()
            subprocess.run(['python3','-m','ci.publish.publication','finalize',str(self.seed),str(self.bundle),result],env=self.env,check=True)
            values=publication.read(self.seed/'status.json')['targets']
            for index,status in enumerate(['pending','running','publishing','published','failed','cancelled','skipped','superseded']):
                self.assertEqual(values[self.rows[index]['id']+'/mqttsuite']['status'],result if index<3 else status)
            self.assertEqual(values[self.rows[8]['id']+'/mqttsuite']['status'],'running')
            (self.seed/'status.json').write_bytes(baseline)

    def test_publisher_merges_status_commits_but_rejects_feed_changes(self):
        publisher=self.clone('publisher')
        previous=self.git('rev-parse','HEAD',cwd=publisher)
        (publisher/'feed').write_text('published feed')
        status=self.clone('status')
        subprocess.run(['bash',str(self.status_script),str(status),'status',str(self.bundle),json.dumps(self.rows[1]),'mqttsuite','running'],env=self.env,check=True,capture_output=True)
        result=subprocess.run(['bash',str(self.push_script),str(publisher),previous,'publish',*self.command(publisher,'published')],env=self.env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        state=self.snapshot()['targets']
        self.assertEqual(state[self.rows[0]['id']+'/snode.c']['status'],'published')
        self.assertEqual(state[self.rows[1]['id']+'/mqttsuite']['status'],'running')
        self.assertEqual(self.git('show','main:feed',cwd=self.remote),'published feed')
        stale=self.clone('stale')
        previous=self.git('rev-parse','HEAD',cwd=stale)
        (stale/'feed').write_text('must not publish')
        other=self.clone('other')
        (other/'feed').write_text('new remote feed')
        self.git('add','.',cwd=other);self.git('commit','-m','changed feed',cwd=other);self.git('push','origin','main',cwd=other)
        result=subprocess.run(['bash',str(self.push_script),str(stale),previous,'stale',*self.command(stale,'published')],env=self.env,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Remote feed changed',result.stderr)
        self.assertEqual(self.git('show','main:feed',cwd=self.remote),'new remote feed')

    def test_reservation_survives_status_commit_with_sparse_checkout(self):
        allocator=self.clone('allocator',sparse=True)
        previous=self.git('rev-parse','HEAD',cwd=allocator)
        status=self.clone('status')
        subprocess.run(['bash',str(self.status_script),str(status),'status',str(self.bundle),json.dumps(self.rows[1]),'mqttsuite','running'],env=self.env,check=True,capture_output=True)
        env=self.env | {'RELEASE_PROJECT':'mqttsuite','GITHUB_RUN_ID':'200'}
        command=['python3','-m','ci.publish.publication','reserve',str(allocator)]
        subprocess.run(command,env=env,check=True)
        result=subprocess.run(['bash',str(self.push_script),str(allocator),previous,'reserve',*command],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        state=self.snapshot()
        self.assertEqual(state['allocations']['200']['mqttsuite'],'2')
        self.assertEqual(state['counters'],{'snode.c':1,'mqttsuite':2})
        self.assertEqual(state['targets'][self.rows[1]['id']+'/mqttsuite']['status'],'running')

    def test_late_terminal_event_cannot_skip_a_published_dependency(self):
        self.event(self.seed,'published')
        self.event(self.seed,'failed')
        state=publication.read(self.seed/'status.json')
        self.assertEqual(state['targets'][self.rows[0]['id']+'/snode.c']['status'],'published')
        self.assertNotIn(self.rows[0]['id']+'/mqttsuite',state['targets'])

    def test_pending_initializes_both_projects_without_regressing_running(self):
        command=['python3','-m','ci.publish.publication','status',str(self.seed),str(self.bundle),'-','-','pending']
        subprocess.run(command,env=self.env,check=True)
        state=publication.read(self.seed/'status.json')
        self.assertEqual(len(state['targets']),40)
        self.assertTrue(all(v['status']=='pending' for v in state['targets'].values()))
        self.event(self.seed,'running')
        subprocess.run(command,env=self.env,check=True)
        self.assertEqual(publication.read(self.seed/'status.json')['targets'][self.rows[0]['id']+'/snode.c']['status'],'running')

    def test_feed_phase_preserves_original_capture_and_copies_documentation(self):
        obsolete_doc = self.seed / 'docs/removed/guide.md'
        obsolete_doc.parent.mkdir(parents=True)
        obsolete_doc.write_text('removed guide')
        (self.seed / 'docs/status.md').write_text('stale generated status')
        self.event(self.seed, 'running', row=self.rows[1])
        status_before = (self.seed / 'status.json').read_bytes()
        badges_before = {p.name: p.read_bytes() for p in (self.seed / 'status/badges').iterdir()}
        original={name:(self.bundle/name).read_bytes() for name in ['context.json','sources.json']}
        feed=self.seed/publication.feed_paths(self.rows[0])[0]
        feed.mkdir(parents=True)
        for name in ['Packages','Packages.gz','Packages.sig','retired.ipk']:
            (feed/name).write_text(name)
        publication.write(feed/'build.json',{'files':{name:repository.digest(feed/name)
                          for name in ['Packages','Packages.gz','Packages.sig']}})
        publication.write(self.seed/'retention.json',{str((feed/'retired.ipk').relative_to(self.seed)):
                          {'sha256':repository.digest(feed/'retired.ipk'),'unreferenced_since':'2000-01-01T00:00:00+00:00'}})
        stdout,stderr=StringIO(),StringIO()
        def publish(*args):
            cleanup.cleanup(self.seed,self.rows[0])
            publication.write(self.bundle/'context.json',{'selected':'modified'})
            publication.write(self.bundle/'sources.json',{'selected':'modified'})
        with patch('sys.argv',['publication','feed',str(self.seed),str(self.bundle),json.dumps(self.rows[0]),'snode.c','unused']), patch.object(publication,'publish',side_effect=publish), redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(publication.main(),0)
        self.assertEqual(stdout.getvalue(),'published\n')
        self.assertIn('Removed ',stderr.getvalue())
        self.assertIn('Protected 3 files; retained 0 retired files; removed 1',stderr.getvalue())
        self.assertFalse((feed/'retired.ipk').exists())
        self.assertEqual((self.seed / 'status.json').read_bytes(), status_before)
        self.assertFalse((self.seed / 'docs/removed').exists())
        self.assertIn('![snode.c: running]', (self.seed / 'docs/status.md').read_text())
        self.assertEqual(badges_before, {p.name: p.read_bytes() for p in (self.seed / 'status/badges').iterdir()})
        expected_docs = {p.relative_to(repository.ROOT / 'docs'): p.read_bytes()
                         for p in (repository.ROOT / 'docs').rglob('*') if p.is_file()}
        actual_docs = {p.relative_to(self.seed / 'docs'): p.read_bytes()
                       for p in (self.seed / 'docs').rglob('*') if p.is_file() and p.name != 'status.md'}
        self.assertEqual(actual_docs, expected_docs)
        self.event(self.seed,stdout.getvalue().strip())
        self.assertEqual(publication.read(self.seed/'status.json')['targets'][self.rows[0]['id']+'/snode.c']['status'],'published')
        for name,data in original.items():
            self.assertEqual((self.bundle/name).read_bytes(),data)
        self.assertEqual((self.seed/'README.md').read_bytes(),(repository.ROOT/'README.md').read_bytes())
        self.assertEqual((self.seed/'install/install.sh').read_bytes(),(repository.ROOT/'install/install.sh').read_bytes())
        self.assertFalse((self.seed / 'net').exists())

    def test_status_exhaustion_only_warns(self):
        # Exercise all retries without a network or real sleeps.
        binary=self.root/'bin';binary.mkdir()
        git_path=subprocess.check_output(['which','git'],text=True).strip()
        wrapper=binary/'git'
        wrapper.write_text('#!/bin/sh\ncase " $* " in *" push "*) echo rejected >> "'+str(self.root/'pushes')+'"; exit 1;; esac\nexec '+git_path+' "$@"\n')
        wrapper.chmod(0o755)
        sleep=binary/'sleep';sleep.write_text('#!/bin/sh\nexit 0\n');sleep.chmod(0o755)
        result=subprocess.run(['bash',str(self.status_script),str(self.seed),'status',str(self.bundle),json.dumps(self.rows[0]),'snode.c','running'],env=self.env | {'PATH':str(binary)+':'+self.env['PATH']},capture_output=True,text=True)
        self.assertEqual(result.returncode,0)
        self.assertIn('::warning::Package status update exhausted',result.stdout)
        self.assertEqual(len((self.root/'pushes').read_text().splitlines()),30)
        self.assertEqual(self.snapshot()['targets'],{})

    def test_status_errors_only_warn(self):
        result=subprocess.run(['bash',str(self.status_script),str(self.seed),'status',str(self.bundle),'{}','snode.c','invalid'],env=self.env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0)
        self.assertIn('::warning::',result.stdout)
        self.assertEqual(self.snapshot()['targets'],{})
        self.git('remote','set-url','origin',str(self.root/'missing.git'),cwd=self.seed)
        result=subprocess.run(['bash',str(self.status_script),str(self.seed),'finalize',str(self.bundle),'failed'],env=self.env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0)
        self.assertIn('::warning::',result.stdout)


if __name__ == '__main__':
    unittest.main()
