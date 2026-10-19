"""Controller behavior through real local Git transactions and a GitHub transport fixture."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from ci import dispatch, repository
from ci.publish import publication


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.remote = self.base / 'remote.git'
        self.root = self.base / 'feed'
        self.git('init', '--bare', '-b', 'main', str(self.remote))
        self.git('clone', str(self.remote), str(self.root))
        self.git('config', 'user.name', 'Test', cwd=self.root)
        self.git('config', 'user.email', 'test@example.invalid', cwd=self.root)
        self.row = next(r for r in publication.targets() if r['id'] == 'debian-trixie-amd64')
        self.graph = {p: repository.PROJECTS[p] for p in ['snode.c', 'mqttsuite']}
        self.sources = dict.fromkeys(self.graph, {'refs/tags/v1.0.0':'a'*40})
        self.bundle = self.base / 'bundle'
        self.context = dict(contract=2, projects=self.graph, release_project='snode.c', run_id='100', run_url='capture',
                            destination='SNodeC/Packages', captured_at='2026-10-19T00:00:00Z', recipe_commit=self.git('rev-parse','HEAD',cwd=repository.ROOT))
        for name, data in dict(context=self.context, targets=[self.row], revisions=dict.fromkeys(self.graph, '2'),
                               sources=self.sources, profiles={self.row['id']:dict(sources=self.sources, baseline={})}).items():
            publication.write(self.bundle / (name+'.json'),data)
        self.state = dict(repository='SNodeC/Packages', branch='main', runs={}, counters={})
        publication.record_run(self.bundle, self.state, self.context)
        self.save()
        self.runs, self.jobs, self.artifacts, self.posts = {}, {}, {}, []
        self.fail_post = None
        self.patches = [patch.dict(os.environ, GITHUB_REPOSITORY=dispatch.COORDINATOR,
                            GITHUB_WORKFLOW_REF=dispatch.COORDINATOR+'/.github/workflows/control-packages.yml@refs/heads/main',
                            COORDINATOR_ACTOR='ci[bot]', RUNNER_TEMP=str(self.base)), patch.object(dispatch,'api',side_effect=self.api)]
        for p in self.patches:
            p.start();self.addCleanup(p.stop)

    def git(self, *args, cwd=None):
        value = subprocess.check_output(['git','-c','commit.gpgsign=false',*args],cwd=cwd or self.base,text=True,stderr=subprocess.DEVNULL).strip()
        return value

    def save(self):
        publication.write(self.root / 'status.json', self.state)
        self.git('add','.',cwd=self.root)
        if subprocess.run(['git','diff','--cached','--quiet'],cwd=self.root).returncode:
            self.git('commit','-m','fixture',cwd=self.root)
            self.git('push','origin','HEAD:main',cwd=self.root)

    def read(self):
        self.state = publication.read(self.root / 'status.json')
        return self.state

    def node(self, project='snode.c', capture='100'):
        value = self.read()['runs'][capture].get('nodes',{}).get(self.row['id']+'/'+project,{})
        return value

    def api(self, endpoint, payload=None):
        parsed = urlsplit(endpoint);parts=parsed.path.split('/');query=parse_qs(parsed.query)
        value = {}
        if payload is not None:
            self.posts.append((endpoint,copy.deepcopy(payload)))
            if self.fail_post:
                raise self.fail_post
            request = json.loads(payload['inputs']['request'])
            number = 500+len(self.posts)
            project = request['project']
            repo = '/'.join(parts[1:3])
            workflow = parts[-2]
            value = dict(workflow_run_id=number)
            self.runs[repo,number] = dict(id=number,event='workflow_dispatch',path='.github/workflows/'+workflow,
                display_title='Packages · '+request['intent'],head_repository={'full_name':repo},head_branch='main',
                actor={'login':'ci[bot]'},run_attempt=1,status='queued',conclusion=None,
                referenced_workflows=[dict(path=dispatch.COORDINATOR+'/.github/workflows/build-packages.yml@main',sha=self.context['recipe_commit'])])
            self.jobs[repo,number] = [dict(id=number+1000,run_id=number,run_attempt=1,name='build / '+request['target'],status='queued',
                html_url=f'https://github.com/{repo}/actions/runs/{number}/job/{number+1000}',steps=[])]
        elif len(parts)==3:
            value = dict(default_branch='main')
        elif parts[-1]=='runs':
            repo='/'.join(parts[1:3]);rows=[r for (n,_),r in self.runs.items() if n==repo and r['path'].endswith(parts[-2])]
            if 'status' in query:
                rows=[r for r in rows if r['status']==query['status'][0]]
            value=dict(total_count=len(rows),workflow_runs=rows if query.get('page',['1'])==['1'] else [])
        elif 'jobs' in parts:
            repo='/'.join(parts[1:3])
            if parts[-2]=='jobs':
                value=next(j for jobs in self.jobs.values() for j in jobs if j['id']==int(parts[-1]))
            else:
                number=int(parts[5]);rows=self.jobs.get((repo,number),[]);value=dict(total_count=len(rows),jobs=rows)
        elif 'artifacts' in parts:
            if parts[-1]=='artifacts':
                rows=self.artifacts.get(('/'.join(parts[1:3]),int(parts[5])),[]);value=dict(total_count=len(rows),artifacts=rows)
            else:
                value=next(a for rows in self.artifacts.values() for a in rows if a['id']==int(parts[-1]))
        elif 'runs' in parts:
            value=copy.deepcopy(self.runs['/'.join(parts[1:3]),int(parts[5])])
        else:
            raise AssertionError(endpoint)
        return copy.deepcopy(value)

    def tick(self, now=1000):
        with patch.object(dispatch.time,'time',return_value=now):
            value=dispatch.tick(self.root, {'100':self.bundle})
        self.read()
        return value

    def finish(self, conclusion='failure', artifact=False):
        permit=next(p for p in self.read()['permits'].values() if p['kind']=='build')
        repo=permit['repository'];number=permit['owner']['run']
        self.runs[repo,number].update(status='completed',conclusion=conclusion)
        self.jobs[repo,number][0].update(status='completed',conclusion=conclusion,
            steps=[dict(name='Upload package artifact',conclusion='success' if artifact else 'failure')])
        if artifact:
            self.artifacts[repo,number]=[dict(id=1234,name=f'packages-{permit["project"]}-{permit["target"]}-1',
                digest='sha256:'+'a'*64,expired=False,workflow_run={'id':number})]
        return permit

    def test_pending_job_details_and_exact_execution_gate(self):
        self.tick();self.tick()
        node=self.node();self.assertEqual(node['status'],'pending')
        self.assertRegex(node['job_url'],r'/snode.c/actions/runs/\d+/job/\d+$')
        intent,permit=next(iter(self.state['permits'].items()))
        request={k:permit[k] for k in ['capture','project','target','publication']}|dict(intent=intent)
        self.assertEqual(dispatch.gate(request,self.state,permit['repository'],permit['owner'],'build'),permit)
        for owner,repo in [(permit['owner']|dict(attempt=2),permit['repository']), (permit['owner'],'SNodeC/mqttsuite')]:
            with self.assertRaises(ValueError):dispatch.gate(request,self.state,repo,owner,'build')

    def test_timeout_is_fenced_and_late_original_never_authorized(self):
        self.fail_post=dispatch.ApiError(0,'timeout')
        self.tick();old=next(iter(self.state['permits']))
        self.fail_post=None
        self.tick(now=1121)
        new=next(iter(self.state['permits']));self.assertNotEqual(old,new)
        request=json.loads(self.posts[0][1]['inputs']['request'])
        with self.assertRaises(ValueError):dispatch.gate(request,self.state,'SNodeC/snode.c',dict(run=1,attempt=1),'build')
        self.assertEqual(len(self.state['permits']),1)

    def test_definite_failure_has_no_slot_leak_or_automatic_retry_storm(self):
        self.fail_post=dispatch.ApiError(401,'invalid installation')
        self.assertFalse(self.tick())
        self.assertEqual(self.state['permits'],{})
        self.assertEqual(self.node()['status'],'failed')
        self.tick();self.assertEqual(len(self.posts),1)

    def test_duplicate_runs_do_not_stop_other_work(self):
        self.tick()
        intent,permit=next(iter(self.state['permits'].items()))
        permit.pop('owner');self.save()
        repo,first=next(iter(self.runs))
        self.runs[repo,999]=self.runs[repo,first]|dict(id=999)
        self.tick()
        self.assertEqual(self.state['permits'][intent]['owner']['run'],first)
        self.assertEqual(self.node()['status'],'pending')

    def test_failed_root_then_manual_rerun_recovers_dependent(self):
        self.tick();permit=self.finish();self.tick()
        self.assertEqual(self.node('mqttsuite')['status'],'skipped')
        repo=permit['repository'];number=permit['owner']['run']
        self.runs[repo,number].update(status='queued',run_attempt=2)
        self.jobs[repo,number][0]['run_attempt']=2
        self.tick()
        rebound=next(iter(self.state['permits'].values()))
        self.assertEqual(rebound['owner'],dict(run=number,attempt=2))
        self.assertEqual(len(self.posts),1)

    def test_uploaded_artifact_survives_later_source_failure(self):
        self.tick();self.finish(conclusion='failure',artifact=True);self.tick()
        self.assertEqual(self.node()['status'],'publishing')
        permits=list(self.state['permits'].values())
        self.assertEqual([p['kind'] for p in permits],['publish'])
        with patch.dict(os.environ,GITHUB_RUN_ID=str(permits[0]['owner']['run']),GITHUB_RUN_ATTEMPT='1'):
            request=json.loads(self.posts[-1][1]['inputs']['request'])
            with patch.object(dispatch,'capture_run'),patch.object(dispatch,'wait_for_permit',return_value=permits[0]):
                result=dispatch.receive(request,self.bundle)
        self.assertEqual(result['artifact_id'],1234)
        self.assertEqual(json.loads(result['receipt'])['source']['run'],501)

    def test_sixteen_external_runs_leave_no_build_capacity(self):
        for number in range(16):
            self.runs['SNodeC/snode.c',number]=dict(id=number,status='in_progress',path='.github/workflows/build-distribution-packages.yml',display_title='manual',run_attempt=1)
        self.tick()
        self.assertEqual(self.posts,[])
        self.assertEqual(self.state['permits'],{})

    def test_link_failure_keeps_permit_without_blocking_other_builds(self):
        self.tick();original=self.api
        def unavailable(path,payload=None):
            if path.endswith('/jobs?per_page=100&page=1'):
                raise dispatch.ApiError(503,'job lookup unavailable')
            return original(path,payload)
        with patch.object(dispatch,'api',side_effect=unavailable):self.tick()
        self.assertEqual(len(self.state['permits']),1)
        self.assertEqual(self.node()['status'],'pending')

    def test_newer_pending_capture_does_not_suppress_older_required_dependent(self):
        source=dict(self.state['runs']['100'])
        newer=copy.deepcopy(source);newer.update(run_id='200',revisions={'mqttsuite':'3'})
        newer['context'].update(run_id='200',release_project='mqttsuite')
        newer['nodes']={self.row['id']+'/mqttsuite':dict(status='pending',attempt=0)}
        self.state['runs']['200']=newer;self.save()
        # A real feed fact makes the older dependent ready. The newer capture has
        # its own frozen old dependency and is exercised in the graph/overlap tests.
        publication.write(self.root/'debian/dists/trixie/build.json',{'targets':{'amd64':dict(versions={'snodec':'1.0.0-2~trixie'},sources=self.sources,
            publications={'snode.c':dict(capture='100',revision='2',job_url='root-job',published_at='2026-10-19T00:00:00Z')})}})
        with patch.object(dispatch,'run',side_effect=repository.run),patch.dict(self.state['runs'],{'200':newer}):
            # The fixture supplies a second immutable bundle, not another source checkout.
            other=self.base/'other';other.mkdir()
            for path in self.bundle.glob('*.json'):(other/path.name).write_bytes(path.read_bytes())
            publication.write(other/'context.json',newer['context']);publication.write(other/'revisions.json',newer['revisions'])
            profile=publication.read(other/'profiles.json');profile[self.row['id']]['baseline']=dict(versions={'snodec':'1.0.0-1~trixie'})
            publication.write(other/'profiles.json',profile);newer['profiles_hash']=repository.digest(other/'profiles.json');self.save()
            dispatch.tick(self.root,{'100':self.bundle,'200':other})
        self.assertEqual(json.loads(self.posts[0][1]['inputs']['request'])['project'],'mqttsuite')
        self.assertEqual(self.node('mqttsuite','200')['status'],'superseded')

    def test_publication_failure_retry_then_feed_receipt_recovers_dependents(self):
        self.tick()
        self.finish(conclusion='success', artifact=True)
        self.tick()
        permit = next(iter(self.read()['permits'].values()))
        self.runs[permit['repository'], permit['owner']['run']].update(status='completed', conclusion='cancelled')
        self.tick()
        self.assertEqual(self.node()['status'], 'failed')
        dispatch.transaction(self.root, dict(retry='100/snode.c/' + self.row['id']))
        self.tick()
        self.assertEqual(next(iter(self.read()['permits'].values()))['kind'], 'publish')
        publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': dict(
            versions={'snodec': '1.0.0-2~trixie'}, sources=self.sources,
            publications={'snode.c': dict(capture='100', revision='2', job_url=self.node()['job_url'], published_at='2026-10-19T00:00:00Z')})}})
        self.save()
        self.tick()
        self.assertEqual(self.node()['status'], 'published')
        self.assertTrue(any(json.loads(payload['inputs']['request'])['project'] == 'mqttsuite' for _, payload in self.posts))

    def test_crash_after_persist_before_send_recovers_after_confirmation_window(self):
        with patch.object(dispatch, 'api', side_effect=lambda path, payload=None: (_ for _ in ()).throw(InterruptedError('runner lost')) if payload else self.api(path)):
            with self.assertRaises(InterruptedError):
                self.tick()
        old = next(iter(self.read()['permits']))
        self.assertEqual(self.posts, [])
        self.tick(now=1121)
        self.assertNotIn(old, self.read()['permits'])
        self.assertEqual(len(self.posts), 1)

    def test_unknown_bound_execution_never_releases_capacity(self):
        self.tick()
        old = copy.deepcopy(self.read()['permits'])
        original = self.api
        def unavailable(path, payload=None):
            if '/attempts/' in path:
                raise dispatch.ApiError(503, 'unknown execution')
            value = original(path, payload)
            return value
        with patch.object(dispatch, 'api', side_effect=unavailable):
            with self.assertRaises(dispatch.ApiError):
                self.tick(now=5000)
        self.assertEqual(self.read()['permits'], old)

    def test_capture_dependency_identity_mismatch_is_explicitly_superseded(self):
        publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': dict(
            versions={'snodec': '1.0.0-2~trixie'}, sources={'snode.c': {'refs/tags/v1.0.0': 'b' * 40}})}})
        self.save()
        self.tick()
        self.assertEqual(self.node('mqttsuite')['status'], 'superseded')

    def test_registry_diamond_admits_join_only_after_both_feed_receipts(self):
        graph = self.graph | {
            'demo': dict(title='Demo', package='demo', depends_on=['snode.c'], families=['linux']),
            'join': dict(title='Join', package='join', depends_on=['mqttsuite', 'demo'], families=['linux'])}
        self.context['projects'] = graph
        self.sources = dict.fromkeys(graph, {'refs/tags/v1.0.0': 'a' * 40})
        for name, data in dict(context=self.context, sources=self.sources, revisions=dict.fromkeys(graph, '2'),
                               profiles={self.row['id']: dict(sources=self.sources, baseline={})}).items():
            publication.write(self.bundle / (name + '.json'), data)
        self.state['runs'] = {}
        publication.record_run(self.bundle, self.state, self.context)
        self.save()
        def feed(projects):
            publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': dict(
                versions={graph[p]['package']: '1.0.0-2~trixie' for p in projects}, sources=self.sources,
                publications={p: dict(capture='100', revision='2', job_url=f'https://github.com/SNodeC/{p}/actions/runs/1/job/2',
                                      published_at='2026-10-19T00:00:00Z') for p in projects})}})
            self.save()
        with patch.object(dispatch, 'PROJECTS', graph), patch.object(repository, 'PROJECTS', graph):
            feed(['snode.c'])
            self.tick()
            self.assertEqual({json.loads(p['inputs']['request'])['project'] for _, p in self.posts}, {'mqttsuite', 'demo'})
            feed(['snode.c', 'mqttsuite'])
            self.tick()
            self.assertNotIn('join', {json.loads(p['inputs']['request'])['project'] for _, p in self.posts})
            feed(['snode.c', 'mqttsuite', 'demo'])
            self.tick()
            self.assertEqual([json.loads(p['inputs']['request'])['project'] for _, p in self.posts].count('join'), 1)

    def test_unavailable_capture_marks_existing_pending_tasks_explicitly(self):
        generation = self.state['runs']['100']
        generation['nodes'] = {self.row['id'] + '/' + p: dict(status='pending', attempt=0) for p in self.graph}
        self.save()
        original = dispatch.run
        def unavailable(*args, **kwargs):
            if args[:3] == ('gh', 'run', 'download'):
                raise RuntimeError('artifact expired')
            value = original(*args, **kwargs)
            return value
        with patch.object(dispatch, 'run', side_effect=unavailable):
            dispatch.tick(self.root, {})
        self.assertEqual(self.node()['status'], 'failed')
        self.assertIn('Immutable capture unavailable', self.node()['reason'])
        self.assertEqual(self.posts, [])

    def test_link_refresh_failure_does_not_block_verified_artifact_publication(self):
        self.tick()
        self.tick()
        self.finish(conclusion='success', artifact=True)
        original = self.api
        def unavailable(path, payload=None):
            if '/jobs?' in path:
                raise dispatch.ApiError(503, 'optional refresh unavailable')
            value = original(path, payload)
            return value
        with patch.object(dispatch, 'api', side_effect=unavailable):
            self.tick()
        self.assertEqual(self.node()['status'], 'publishing')
        self.assertEqual([p['kind'] for p in self.read()['permits'].values()], ['publish'])

    def test_partial_rerun_never_inherits_carried_job_link(self):
        self.tick()
        self.tick()
        permit = self.finish()
        self.tick()
        repo, number = permit['repository'], permit['owner']['run']
        self.runs[repo, number].update(status='queued', run_attempt=2)
        self.tick()
        self.tick()
        self.assertEqual(self.node()['attempt'], 2)
        self.assertNotIn('job_url', self.node())
        self.assertNotIn('job', self.node())
