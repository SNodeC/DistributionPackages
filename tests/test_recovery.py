"""Failure isolation, durable capture and exact dependency lifecycle regressions."""
import copy
import json
import os
import shutil
import subprocess
from unittest.mock import patch
from support import CoordinatorCase
from ci import dispatch, repository
from ci.publish import publication


class RecoveryTest(CoordinatorCase):
    def test_deleted_run_does_not_block_an_independent_release_and_can_be_retried(self):
        self.tick()
        original = self.api
        def deleted(path, payload=None, token=None):
            if path.endswith('/runs/501'):
                raise dispatch.ApiError(404, 'deleted source run')
            return original(path, payload, token)
        with patch.object(dispatch, 'api', side_effect=deleted):
            self.tick()
        self.assertEqual(self.node()['status'], 'failed')
        self.assertEqual(self.node()['observation']['category'], 'expiry')
        dispatch.transaction(self.root, dict(retry='100/snode.c/'+self.row['id']))
        self.tick()
        self.assertEqual(self.node()['source']['run'], 502)
        self.assertEqual(self.node()['builds'], 1)
        return None

    def test_transient_capture_download_defers_without_changing_budget(self):
        original = self.api
        def api(path, payload=None, token=None):
            return dict(total_count=1, artifacts=[dict(name='source-pair', expired=False)]) if '/runs/100/artifacts' in path else original(path, payload, token)
        original_run = dispatch.run
        downloads = []
        def run(*args, **kwargs):
            if args[:3] == ('gh', 'run', 'download'):
                downloads.append(args)
                raise subprocess.CalledProcessError(1, args, stderr='HTTP 503')
            return original_run(*args, **kwargs)
        with patch.object(dispatch, 'api', side_effect=api), patch.object(dispatch, 'run', side_effect=run):
            dispatch.tick(self.root, {})
            self.assertEqual(self.node()['status'], 'pending')
            self.assertEqual(self.node()['observation']['category'], 'transient')
            self.assertEqual(self.node().get('builds', 0), 0)
            before = len(downloads)
            dispatch.tick(self.root, {})
            self.assertEqual(len(downloads), before)
        with patch.object(dispatch.time, 'time', return_value=self.node()['observation']['retry_at']+1):
            self.tick()
        self.assertEqual(self.node()['builds'], 1)
        return None

    def test_one_run_observation_rate_limit_retains_artifact_and_budget(self):
        self.tick()
        before = copy.deepcopy(self.node())
        original = self.api
        def limited(path, payload=None, token=None):
            if path.endswith('/runs/501'):
                raise dispatch.ApiError(429, 'rate limit', 120)
            return original(path, payload, token)
        with patch.object(dispatch, 'api', side_effect=limited):
            self.tick()
        self.assertEqual(self.node()['builds'], before['builds'])
        self.assertEqual(self.node()['status'], before['status'])
        self.assertEqual(self.node()['observation']['category'], 'transient')
        with patch.object(dispatch.time, 'time', return_value=self.node()['observation']['retry_at']+1):
            self.tick()
        self.assertNotIn('observation', self.node())
        return None

    def test_ambiguous_dispatch_never_redispatches_based_on_short_absence(self):
        original = self.api
        def hidden(path, payload=None, token=None):
            if payload:
                original(path, payload, token)
                raise dispatch.ApiError(0, 'response lost')
            return dict(total_count=0, workflow_runs=[]) if '/workflows/' in path and '/runs?' in path else original(path, payload, token)
        with patch.object(dispatch, 'api', side_effect=hidden):
            self.tick()
            with patch.object(dispatch.time, 'time', return_value=self.node()['observation']['retry_at']+121):
                self.tick()
        self.assertEqual(len(self.posts), 1)
        self.assertNotIn('source', self.node())
        self.assertEqual(self.node().get('builds', 0), 0)
        self.assertIn('request', self.node())
        return None

    def test_definitive_dispatch_error_closes_without_consuming_publish_budget(self):
        original = self.api
        def rejected(path, payload=None, token=None):
            if payload:
                raise dispatch.ApiError(422, 'workflow input invalid')
            return original(path, payload, token)
        with patch.object(dispatch, 'api', side_effect=rejected):
            self.tick()
        self.assertEqual(self.node()['status'], 'failed')
        self.assertNotIn('request', self.node())
        self.assertEqual(self.node().get('publications', 0), 0)
        self.assertIn('Dispatch rejected', self.node()['reason'])
        return None

    def test_expired_artifact_operator_retry_rebuilds_but_valid_artifact_is_reused(self):
        self.tick()
        self.finish()
        self.tick()
        node = self.node()
        self.runs[dispatch.COORDINATOR, node['publisher']].update(status='completed', conclusion='failure')
        self.tick()
        self.artifacts['SNodeC/snode.c', 501][0]['expired'] = True
        original = self.api
        def api(path, payload=None, token=None):
            return {'permission':'write'} if '/permission' in path else original(path, payload, token)
        self.artifacts[dispatch.COORDINATOR,100] = [dict(name='source-pair', expired=False)]
        original_run = dispatch.run
        def commands(*args, **kwargs):
            value = ''
            if args[:3] == ('gh', 'run', 'download'):
                shutil.copytree(self.bundle, args[-1], dirs_exist_ok=True)
            elif args[-1] != 'project':
                value = original_run(*args, **kwargs)
            return value
        with patch.dict(os.environ, PACKAGE_RETRY='100/snode.c/'+self.row['id'], PACKAGE_REPORT='', GITHUB_ACTOR='maintainer', GITHUB_TRIGGERING_ACTOR='maintainer'), patch('sys.argv',['dispatch','control',str(self.root)]), patch.object(dispatch,'api',side_effect=api), patch.object(dispatch,'run',side_effect=commands):
            dispatch.main()
        self.assertNotIn('artifact', self.node())
        self.assertNotIn('source', self.node())
        with patch.object(dispatch.time,'time',return_value=self.node()['observation']['retry_at']+1):
            self.tick()
        self.assertEqual(self.node()['builds'], 1)
        self.assertNotEqual(self.node()['source']['run'], 501)
        return None

    def test_structural_skip_never_reloads_capture_and_overlap_off_closes(self):
        self.state['runs']['100']['revisions'] = {'snode.c-idp': '2'}
        profiles = publication.read(self.bundle/'profiles.json')
        profiles[self.row['id']]['sources'].pop('snode.c-idp')
        publication.write(self.bundle/'profiles.json', profiles)
        self.state['runs']['100']['profiles_hash'] = repository.digest(self.bundle/'profiles.json')
        self.save()
        self.feed(['snode.c'], capture='other', revision='3')
        with patch.dict(repository.CONFIG['settings'], rebuild_overlap=False):
            self.tick()
            self.assertEqual(self.node('snode.c-idp')['category'], 'excluded')
            self.assertNotIn('request', self.node('mqttsuite'))
            with patch.object(dispatch, 'run', wraps=dispatch.run) as calls:
                dispatch.tick(self.root, {})
        self.assertFalse(any(c.args[:3] == ('gh', 'run', 'download') for c in calls.call_args_list))
        return None

    def test_bound_graph_controls_dispatch_and_unchanged_binding_does_not_reset(self):
        self.feed(['snode.c', 'mqttsuite'])
        self.state['runs']['100']['revisions'] = {'snode.c-idp': '2'}
        self.state['runs']['100']['context']['release_project'] = 'snode.c-idp'
        self.save()
        graph = copy.deepcopy(self.graph)
        graph['snode.c']['depends_on'] = ['mqttsuite']
        graph['mqttsuite']['depends_on'] = []
        with patch.object(dispatch, 'bind_projects', return_value=repository.validate_projects(graph)):
            self.tick()
            node = self.node('snode.c-idp')
            self.assertEqual(node['requires'], ['mqttsuite', 'snode.c'])
            request = next(json.loads(p['inputs']['request']) for _, p in self.posts if json.loads(p['inputs']['request'])['project']=='snode.c-idp')
            self.assertEqual(set(request['definitions']), {'snode.c', 'mqttsuite'})
            before = len(self.posts)
            self.tick()
            self.assertEqual(len(self.posts), before)
            self.assertEqual(self.node('snode.c-idp')['builds'], 1)
        return None

    def test_capture_registration_is_durable_in_local_bare_remote(self):
        self.state['runs'] = {}
        self.state['requests'] = {'snode.c': {'v1.0.0': dict(definition=copy.deepcopy(self.graph['snode.c']), **dict(capture='100',eligible=False))}}
        self.save()
        # Assert the pushed transaction; a parent-process renderer mock cannot constrain this subprocess.
        dispatch.run('bash', str(repository.ROOT/'ci/publish/status.sh'), str(self.root), 'status', str(self.bundle), '-', '-', 'pending')
        remote = json.loads(self.git('show', 'main:status.json', cwd=self.remote))
        self.assertIn('100', remote['runs'])
        self.assertTrue(remote['requests']['snode.c']['v1.0.0']['eligible'])
        self.assertEqual(remote['runs']['100']['nodes'][self.row['id']+'/snode.c']['status'], 'pending')
        return None

    def test_failed_capture_intent_is_no_longer_selected(self):
        self.state['requests'] = {'mqttsuite': {'v2.0.0': dict(definition=copy.deepcopy(self.graph['mqttsuite']),
            **dict(capture='200', sha='f'*40, tag='v2.0.0', revision='3'))}}
        self.save()
        self.runs[dispatch.COORDINATOR,200] = dict(event='workflow_dispatch',path='.github/workflows/orchestrate-packages.yml',head_repository={'full_name':dispatch.COORDINATOR},status='completed',conclusion='timed_out')
        self.tick()
        request = publication.read(self.root/'status.json')['requests']['mqttsuite']['v2.0.0']
        self.assertFalse(request['eligible'])
        self.assertIn('Capture failed', request['reason'])
        return None




    def test_receipt_replay_through_feed_and_git_writer_never_signs_or_writes_feed(self):
        self.tick()
        node = self.finish()
        name = 'snodec_1.0.0-2_amd64.deb'
        incoming = self.base/'incoming'
        incoming.mkdir()
        (incoming/name).write_bytes(b'authenticated unsigned bytes')
        checksums = {name:repository.digest(incoming/name)}
        receipt = dict(capture='100',source=node['source'],artifact={'id':1234,'digest':'sha256:'+'f'*64},job=1501)
        info = dict(publications={'snode.c':receipt|dict(revision='2',unsigned_files=checksums)},sources=self.sources)
        publication.write(self.root/'debian/dists/trixie/build.json',{'targets':{'amd64':info}})
        publication.write(incoming/'build.json',dict(files=checksums,sources=self.sources))
        self.state = publication.read(self.root/'status.json')
        self.save()
        previous = self.git('rev-parse','HEAD',cwd=self.root)
        with patch.dict(os.environ,BUILD_RECEIPT=json.dumps(receipt)), patch('sys.argv',['publication','feed',str(self.root),str(self.bundle),json.dumps(self.row),'snode.c',str(incoming)]), patch.object(publication,'copy_site'), patch('ci.publish.linux.publish',side_effect=AssertionError('replay cannot sign')), patch('ci.repository.publish',side_effect=AssertionError('replay cannot sign')), patch('ci.publish.cleanup.cleanup',side_effect=AssertionError('replay cannot clean')):
            self.assertEqual(publication.main(),0)
        self.assertEqual(self.git('diff','--name-only',cwd=self.root),'')
        dispatch.run('bash',str(repository.ROOT/'ci/publish/push.sh'),str(self.root),previous,'idempotent replay')
        self.assertEqual(self.git('rev-parse','main',cwd=self.remote),previous)
        return None

    def test_separate_exhausted_budgets_stop_dispatch_until_operator_retry(self):
        self.state['runs']['100'].setdefault('nodes', {}).setdefault(self.row['id']+'/snode.c',dict(status='pending',attempt=0)).update(builds=3)
        self.save()
        self.tick()
        self.assertEqual(self.posts,[])
        self.assertEqual(self.node()['status'],'failed')
        self.assertIn('builds dispatch budget',self.node()['reason'])
        dispatch.transaction(self.root,dict(retry='100/snode.c/'+self.row['id']))
        self.tick()
        self.finish()
        node = self.node()
        node['publications'] = 3
        self.save()
        self.tick()
        self.assertEqual(len(self.posts),1)
        self.assertIn('publications dispatch budget',self.node()['reason'])
        return None

    def test_running_control_uses_its_headroom_without_self_deadlock(self):
        occupied = {('DistributionPackages',99):dict(run=42,name='control',title='control')}
        with patch.dict(os.environ,GITHUB_RUN_ID='42'),patch.object(dispatch,'capacity',return_value=(2,occupied)):
            self.tick()
        self.assertEqual(len(self.posts),1)
        self.assertEqual(self.node()['source']['run'],501)
        return None

    def test_terminal_known_run_releases_its_commitment_for_another_target(self):
        row = copy.deepcopy(self.row)
        row.update(id='debian-trixie-arm64',arch='arm64',runner='ubuntu-24.04-arm')
        row['build'].update(arch='arm64',platform='linux/arm64',runner=row['runner'])
        generation = self.state['runs']['100']
        generation['targets'].append(row)
        generation['sources'][row['id']] = self.sources
        profiles = publication.read(self.bundle/'profiles.json')
        profiles[row['id']] = copy.deepcopy(profiles[self.row['id']])
        publication.write(self.bundle/'profiles.json',profiles)
        publication.write(self.bundle/'targets.json',generation['targets'])
        generation['profiles_hash'] = repository.digest(self.bundle/'profiles.json')
        generation.setdefault('nodes',{})[self.row['id']+'/snode.c'] = dict(status='failed',waiting=True,source={'run':501,'attempt':1},request={'intent':'deleted','actor':'ci[bot]','created':'2026-10-20T00:00:00Z'})
        self.save()
        # Local termination alone is insufficient: execution completion releases the commitment.
        self.runs['SNodeC/snode.c',501] = dict(status='completed',run_attempt=1)
        with patch.object(dispatch,'capacity',return_value=(3,{})):
            self.tick()
        self.assertEqual(len(self.posts),1)
        self.assertEqual(json.loads(self.posts[0][1]['inputs']['request'])['target'],row['id'])
        return None

    def test_direct_release_uses_published_prerequisite_despite_new_reservation(self):
        self.feed(['snode.c'],capture='prior',revision='1')
        generation = self.state['runs']['100']
        generation['context']['release_project'] = 'mqttsuite'
        generation['revisions'] = {'mqttsuite':'3'}
        generation['nodes'] = {}
        self.runs[dispatch.COORDINATOR,200] = dict(event='workflow_dispatch',path='.github/workflows/orchestrate-packages.yml',head_repository={'full_name':dispatch.COORDINATOR},status='in_progress')
        self.state['requests'] = {'snode.c': {'v1.0.0': dict(definition=copy.deepcopy(self.graph['snode.c']),
            **dict(capture='200',sha='a'*40,revision='2',eligible=True))}}
        self.save()
        self.tick()
        self.assertEqual([json.loads(p['inputs']['request'])['project'] for _,p in self.posts], ['mqttsuite'])
        self.assertEqual(self.node('mqttsuite')['requires'], ['snode.c'])
        self.state['requests']['snode.c']['v1.0.0']['eligible'] = False
        self.save()
        self.tick()
        self.assertEqual([json.loads(p['inputs']['request'])['project'] for _,p in self.posts],['mqttsuite'])
        return None

    def test_deleted_source_run_with_retained_artifact_can_be_rebuilt(self):
        self.tick()
        self.finish()
        self.tick()
        node = self.node()
        node.update(status='failed',observation={'category':'expiry','reason':'source run deleted'})
        self.save()
        dispatch.transaction(self.root,dict(retry='100/snode.c/'+self.row['id']))
        self.assertNotIn('artifact',self.node())
        self.assertNotIn('source',self.node())
        self.tick()
        self.assertEqual(self.node()['source']['run'],503)
        return None

    def test_source_rerun_clears_retained_artifact_and_returns_to_pending(self):
        self.tick()
        node = self.finish()
        request = node['request'] | dict(run=501,attempt=1,job=1501,status='publishing',artifact={'id':1234,'digest':'sha256:'+'f'*64})
        dispatch.apply_report(self.root,request,self.bundle)
        self.runs['SNodeC/snode.c',501].update(run_attempt=2,status='queued')
        self.tick()
        self.assertEqual(self.node()['source']['attempt'],2)
        self.assertEqual(self.node()['status'],'pending')
        self.assertNotIn('artifact',self.node())
        self.assertNotIn('job_url',self.node())
        self.assertEqual(len(self.posts),1)
        return None

    def test_successful_source_receipt_visibility_lag_recovers_without_another_build(self):
        self.tick()
        self.finish(artifact=False)
        self.tick()
        self.assertEqual(self.node()['status'],'pending')
        self.assertEqual(self.node()['observation']['category'],'transient')
        self.assertFalse(self.node()['waiting'])
        self.artifacts['SNodeC/snode.c',501] = [dict(id=1234,name='packages-snode.c-'+self.row['id']+'-1',digest='sha256:'+'f'*64,expired=False,workflow_run={'id':501})]
        with patch.object(dispatch.time,'time',return_value=self.node()['observation']['retry_at']+1):
            self.tick()
        self.assertEqual(self.node()['status'],'publishing')
        self.assertEqual(self.node()['builds'],1)
        self.assertEqual(self.node()['publications'],1)
        self.assertEqual(len(self.posts),2)
        return None

    def test_immutable_definition_fetch_is_shared_for_one_command(self):
        graph = copy.deepcopy(self.graph)
        data = json.dumps({k:v for k,v in graph['snode.c'].items() if not k.startswith('_')}).encode()
        baseline = {'sources':{'snode.c':{'refs/tags/v2.0.0':'e'*40}}}
        repository.definition_data.cache_clear()
        with patch.object(repository,'content',return_value=data) as content:
            for project in ['mqttsuite','snode.c-idp']:
                bound = repository.bind_projects(graph,baseline,project)
                self.assertEqual(bound['snode.c']['_commit'],'e'*40)
            self.assertEqual(content.call_count,1)
        repository.definition_data.cache_clear()
        return None

    def test_provisional_capture_retry_refreshes_revisions_once_but_saved_capture_is_immutable(self):
        root = self.base/'provisional'
        with patch.dict(os.environ,RELEASE_REQUESTED_AT='2026-10-20T00:00:00Z',RELEASE_RUN='99',RELEASE_SHA='a'*40,RELEASE_TAG='v1.0.0',GITHUB_RUN_ATTEMPT='1'):
            first = publication.reserve(root,'snode.c','700')
            # A later application release advances its own counter while this capture fails.
            publication.reserve(root,'mqttsuite','701')
            with patch.dict(os.environ,GITHUB_RUN_ATTEMPT='2'):
                second = publication.reserve(root,'snode.c','700')
                self.assertGreater(int(second['snode.c']),int(first['snode.c']))
                self.assertEqual(set(second), {'snode.c'})
                self.assertEqual(publication.reserve(root,'snode.c','700'),second)
                state = publication.read(root/'status.json')
                state['runs']['700'] = {'immutable':'capture already saved'}
                publication.write(root/'status.json',state)
                with patch.dict(os.environ,GITHUB_RUN_ATTEMPT='3'):
                    self.assertEqual(publication.reserve(root,'snode.c','700'),second)
        return None

    def test_dispatch_uses_the_same_feed_snapshot_as_readiness(self):
        self.feed(['snode.c'])
        self.state['runs']['100']['context']['release_project'] = 'mqttsuite'
        self.state['runs']['100']['revisions'] = {'mqttsuite':'2'}
        self.save()
        baseline = publication.published(self.root,self.row)[0]
        commit = self.git('rev-parse','HEAD',cwd=self.root)
        def capacity():
            self.feed(['snode.c'],capture='new',revision='3')
            return 20, {}
        with patch.object(dispatch,'capacity',side_effect=capacity):
            self.tick()
        request = json.loads(self.posts[0][1]['inputs']['request'])
        self.assertEqual(request['publication'],commit)
        self.assertEqual(self.node('mqttsuite')['dependencies'],repository.binding(baseline,['snode.c']))
        self.assertEqual(request['definitions']['snode.c']['_commit'],repository.source_commit(baseline['sources']['snode.c']))
        return None

    def test_invalid_unpublished_build_definition_is_confined_to_its_repository(self):
        current = copy.deepcopy(self.graph['snode.c'])
        current['matrix'] = {'linux':[dict(distribution='debian',suite='trixie',image='debian:trixie',architectures=['amd64'])]}
        current['build'] = {'native':'ci/package/native.sh'}
        claimed = {k:v for k,v in current.items() if not k.startswith('_')}
        def definition(project, commit):
            result = copy.deepcopy(current if project=='snode.c' else self.graph[project])
            result.update(_commit=commit,_digest='f'*64)
            if project=='mqttsuite':
                result['build'] = []
            return result
        def api(path, *args, **kwargs):
            return {'object':{'sha':'d'*40}} if '/git/' in path else {'default_branch':'main'}
        destination = self.base/'selected-definitions.json'
        with patch.object(repository,'definition',side_effect=definition),patch.object(dispatch,'api',side_effect=api),patch.object(repository,'DEFINITIONS',destination),patch.dict(repository.ROW_PROJECTS,{},clear=True):
            repository.configure(self.root,'snode.c','a'*40,claimed)
        selected = publication.read(destination)
        self.assertIn('snode.c',selected['targets'][self.row['id']])
        self.assertEqual(selected['projects']['mqttsuite']['_commit'], self.graph['mqttsuite']['_commit'])
        self.assertEqual(selected['projects']['mqttsuite']['build'], self.graph['mqttsuite']['build'])
        self.assertNotIn('errors', selected)
        return None

    def test_actual_triggering_actor_controls_operator_rerun(self):
        for trigger, allowed in [('notify[bot]', False), ('maintainer', True)]:
            with patch.dict(os.environ, GITHUB_ACTOR='maintainer', GITHUB_TRIGGERING_ACTOR=trigger), patch.object(dispatch, 'api', return_value={'permission':'write'}):
                if allowed:
                    dispatch.authorize_operator()
                else:
                    with self.assertRaisesRegex(ValueError, 'human'):
                        dispatch.authorize_operator()
        return None
