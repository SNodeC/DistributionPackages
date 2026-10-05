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

    def test_status_render_is_immutable_and_does_not_copy_documentation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'status').mkdir()
            (root / 'status/old-target.svg').write_text('obsolete')
            publication.render(root, {'targets': {}})
            before = {p.name: p.read_bytes() for p in (root / 'status/badges').iterdir()}
            self.assertEqual(len(before), 9)
            self.assertFalse((root / 'status/old-target.svg').exists())
            state = dict(targets={})
            row = publication.targets()[0]
            generation = dict(revisions={'snode.c':'1'},run_id='one',run_url='url')
            publication.update(state,row,generation,'snode.c','running',1)
            publication.render(root,state)
            self.assertEqual(before,{p.name:p.read_bytes() for p in (root/'status/badges').iterdir()})
            text=(root/'docs/status.md').read_text()
            self.assertIn('![snode.c: running](../status/badges/running.svg)',text)
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


class StatusEventsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        self.git('init','--bare','-b','main',str(self.remote))
        self.seed = self.clone('seed')
        (self.seed/'feed').write_text('original feed')
        publication.write(self.seed/'status.json',dict(repository='SNodeC/Packages',branch='main',runs={},targets={}))
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
        self.assertEqual(self.git('rev-list','--count','main',cwd=self.remote),'1')

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
        env=self.env | {'RELEASE_PROJECT':'mqttsuite','GITHUB_RUN_ID':'200','PACKAGE_REVISION_BASE':'0'}
        command=['python3','-m','ci.publish.publication','reserve',str(allocator)]
        subprocess.run(command,env=env,check=True)
        result=subprocess.run(['bash',str(self.push_script),str(allocator),previous,'reserve',*command],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        state=self.snapshot()
        self.assertEqual(state['allocations']['200']['mqttsuite'],'2')
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
        original={name:(self.bundle/name).read_bytes() for name in ['context.json','sources.json']}
        def publish(*args):
            publication.write(self.bundle/'context.json',{'selected':'modified'})
            publication.write(self.bundle/'sources.json',{'selected':'modified'})
        with patch('sys.argv',['publication','feed',str(self.seed),str(self.bundle),json.dumps(self.rows[0]),'snode.c','unused']), patch.object(publication,'publish',side_effect=publish):
            self.assertEqual(publication.main(),0)
        self.assertEqual(publication.read(self.seed/'status.json')['targets'],{})
        for name,data in original.items():
            self.assertEqual((self.bundle/name).read_bytes(),data)
        self.assertEqual((self.seed/'README.md').read_bytes(),(repository.ROOT/'README.md').read_bytes())
        self.assertEqual((self.seed/'install/install.sh').read_bytes(),(repository.ROOT/'install/install.sh').read_bytes())

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
