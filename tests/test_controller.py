"""Callbacks and bounded reconciliation share one admission state."""
import copy
import json
import os
from unittest.mock import patch
from support import CoordinatorCase
from ci import dispatch, repository
from ci.publish import publication


class ControllerTest(CoordinatorCase):
    def test_root_dispatch_is_one_target_and_duplicate_wakes_do_not_dispatch_again(self):
        self.tick()
        self.assertEqual(len(self.posts),1)
        self.assertEqual(json.loads(self.posts[0][1]['inputs']['request'])['target'],self.row['id'])
        self.tick()
        self.assertEqual(len(self.posts),1)
        self.assertRegex(self.node()['job_url'],r'/job/\d+$')
        return None

    def test_failure_does_not_skip_unrelated_targets_or_reopen_closed_generation(self):
        self.tick();self.finish(artifact=False,conclusion='failure');self.tick()
        self.assertEqual(self.node()['status'],'failed')
        before=len(self.posts)
        self.tick()
        self.assertEqual(len(self.posts),before)
        return None

    def test_uploaded_artifact_survives_cleanup_failure_and_has_publish_priority(self):
        self.tick();self.finish(conclusion='failure');self.tick()
        self.assertEqual(self.node()['status'],'publishing')
        self.assertIn('sign-and-publish-packages.yml',self.posts[-1][0])
        return None

    def test_receipt_recovers_failure_and_unblocks_both_dependents(self):
        self.tick();self.finish(artifact=False,conclusion='failure');self.tick()
        self.feed(['snode.c'])
        self.tick()
        self.assertEqual(self.node()['status'],'published')
        self.assertEqual({json.loads(p['inputs']['request'])['project'] for _,p in self.posts[1:]},{'mqttsuite','snode.c-idp'})
        return None

    def test_headroom_and_unstarted_commitment_are_counted_once(self):
        with patch.object(dispatch,'capacity',return_value=(2,{})):
            self.tick()
        self.assertEqual(self.posts,[])
        self.tick()
        with patch.object(dispatch,'capacity',return_value=(3,{})):
            self.tick()
        self.assertEqual(len(self.posts),1)
        return None

    def test_unknown_capacity_does_not_erase_pending_work(self):
        with patch.object(dispatch,'capacity',side_effect=ValueError('unknown inventory')):
            self.tick()
        self.assertEqual(self.node()['status'],'pending')
        self.assertEqual(self.posts,[])
        self.assertIn('unknown inventory',self.state['observation']['reason'])
        with patch.object(dispatch.time,'time',return_value=self.state['observation']['retry_at']+1):
            self.tick()
        self.assertEqual(len(self.posts),1)
        return None

    def test_ambiguous_dispatch_is_recovered_from_real_run_identity(self):
        original=self.api
        def lost(path,payload=None,token=None):
            result=original(path,payload,token)
            if payload:
                raise dispatch.ApiError(0,'connection lost after dispatch')
            return result
        with patch.object(dispatch,'api',side_effect=lost):
            self.tick()
        self.assertNotIn('source',self.node())
        with patch.object(dispatch.time, 'time', return_value=self.node()['observation']['retry_at'] + 1):
            self.tick()
        self.assertEqual(self.node()['source']['run'],501)
        self.assertEqual(len(self.posts),1)
        return None

    def test_publication_retry_has_independent_budget_and_keeps_artifact(self):
        self.tick();self.finish()
        node=self.node();node['builds']=3;self.save();self.tick()
        self.assertEqual(self.node()['builds'],3)
        self.assertEqual(self.node()['publications'],1)
        node=self.node();self.runs[dispatch.COORDINATOR,node['publisher']].update(status='completed',conclusion='failure')
        self.tick()
        self.assertEqual(self.node()['status'],'failed')
        dispatch.transaction(self.root,dict(retry='100/snode.c/'+self.row['id']))
        self.tick()
        self.assertEqual(self.node()['publications'],1)
        self.assertEqual(self.node()['builds'],0)
        self.assertEqual(self.node()['artifact']['id'],1234)
        return None

    def test_missing_capture_is_explicit_failure_without_repeated_download(self):
        with patch.object(dispatch, 'run', wraps=dispatch.run) as commands:
            dispatch.tick(self.root, {})
            self.assertEqual(self.node()['status'], 'failed')
            self.assertIn('new explicit release', self.node()['reason'])
            self.assertEqual(self.node()['observation']['category'], 'expiry')
            dispatch.tick(self.root, {})
        self.assertFalse(any(c.args[:3] == ('gh', 'run', 'download') for c in commands.call_args_list))
        self.assertEqual(self.posts, [])
        return None

    def test_same_source_new_package_revision_requeues_stale_attempt(self):
        self.feed(['snode.c'],capture='prior',revision='1')
        generation = self.state['runs']['100']
        generation['context']['release_project'] = 'mqttsuite'
        generation['revisions'] = {'mqttsuite':'2'}
        profiles = publication.read(self.bundle/'profiles.json')
        profiles[self.row['id']]['baseline'] = publication.published(self.root,self.row)[0]
        publication.write(self.bundle/'profiles.json',profiles)
        publication.write(self.bundle/'context.json',generation['context'])
        publication.write(self.bundle/'revisions.json',generation['revisions'])
        generation['profiles_hash'] = repository.digest(self.bundle/'profiles.json')
        self.save()
        self.tick()
        first = self.node('mqttsuite')
        self.assertEqual(first['source']['run'],501)
        self.runs['SNodeC/mqttsuite',501].update(status='completed',conclusion='success')
        self.jobs['SNodeC/mqttsuite',501][0].update(status='completed')
        self.artifacts['SNodeC/mqttsuite',501] = [dict(id=1234,name='packages-mqttsuite-'+self.row['id']+'-1',digest='sha256:'+'f'*64,expired=False,workflow_run={'id':501})]
        self.feed(['snode.c'],capture='new-prerequisite',revision='2')
        self.tick()
        after = self.node('mqttsuite')
        self.assertEqual(after['source']['run'],502)
        self.assertEqual(after['cause'],'dependent')
        self.assertNotIn('artifact',after)
        self.assertEqual(self.state['runs']['100']['sources'][self.row['id']]['mqttsuite'],self.sources['mqttsuite'])
        self.assertEqual([json.loads(p['inputs']['request'])['project'] for _,p in self.posts],['mqttsuite','mqttsuite'])
        self.assertTrue(all('/build-distribution-packages.yml/' in endpoint for endpoint,_ in self.posts))
        return None

    def test_newer_explicit_source_survives_framework_overlap_and_gets_dependent_cause(self):
        self.feed(['snode.c'],capture='prior',revision='1')
        profiles=publication.read(self.bundle/'profiles.json')
        profiles[self.row['id']]['baseline']=publication.published(self.root,self.row)[0]
        publication.write(self.bundle/'profiles.json',profiles)
        self.state['runs']['100']['profiles_hash']=repository.digest(self.bundle/'profiles.json')
        later=self.base/'later'
        context=self.context|dict(run_id='200',tag='v2.0.0',release_project='mqttsuite',captured_at='2026-10-20T00:00:01Z')
        source=copy.deepcopy(self.sources);source['mqttsuite']={'refs/tags/v2.0.0':'e'*40}
        profile=copy.deepcopy(profiles[self.row['id']]);profile['sources']=source
        profile['projects']['mqttsuite']['_commit']='e'*40
        for name,value in dict(context=context,targets=[self.row],revisions={'mqttsuite':'3'},sources={self.row['id']:source},profiles={self.row['id']:profile},checksums={}).items():
            publication.write(later/(name+'.json'),value)
        publication.record_run(later,self.state,context);self.save()
        self.tick({'100':self.bundle,'200':later})
        self.assertEqual([json.loads(p['inputs']['request'])['project'] for _,p in self.posts],['snode.c','mqttsuite'])
        self.assertEqual(self.node('mqttsuite', '200')['source']['run'], 502)
        self.runs['SNodeC/mqttsuite', 502].update(status='completed', conclusion='success')
        self.jobs['SNodeC/mqttsuite', 502][0].update(status='completed', conclusion='success')
        self.artifacts['SNodeC/mqttsuite', 502] = [dict(id=2900, name='packages-mqttsuite-' + self.row['id'] + '-1',
            digest='sha256:' + 'f' * 64, expired=False)]
        self.feed(['snode.c'],revision='2')
        self.tick({'100':self.bundle,'200':later})
        self.assertNotIn('request', self.node('mqttsuite'))
        self.assertEqual([json.loads(payload['inputs']['request'])['kind'] for _, payload in self.posts
                          if json.loads(payload['inputs']['request'])['project'] == 'mqttsuite'], ['build', 'build'])
        self.assertEqual(self.node('mqttsuite', '200')['request']['kind'], 'build')
        self.assertEqual(self.node('mqttsuite','200')['cause'],'dependent')
        self.assertEqual(self.state['runs']['200']['sources'][self.row['id']]['mqttsuite'],{'refs/tags/v2.0.0':'e'*40})
        return None

    def test_synthetic_repository_needs_only_registration_definition_and_build_wrapper(self):
        self.artifacts['SNodeC/mqttsuite',900] = [dict(id=2900,expired=False)]
        graph=copy.deepcopy(self.graph)
        graph['demo']=copy.deepcopy(graph['snode.c'])
        graph['demo'].update(title='Demo',package='demo',depends_on=[],matrix={'linux':[self.row['build']|dict(architectures=['amd64'])]},build={'native':'ci/package/native.sh'},_commit='e'*40)
        # Native source rows have a compact architectures list, not expanded runner fields.
        graph['demo']['matrix']['linux'][0]={k:v for k,v in graph['demo']['matrix']['linux'][0].items() if k in {'distribution','suite','image','architectures'}}
        self.context.update(projects=graph,release_project='demo')
        source={'demo':{'refs/tags/v1.0.0':'e'*40}}
        for name,value in dict(context=self.context,revisions={'demo':'1'},sources={self.row['id']:source},profiles={self.row['id']:dict(projects=graph,sources=source,baseline={})}).items():
            publication.write(self.bundle/(name+'.json'),value)
        self.state['runs']={}
        publication.record_run(self.bundle,self.state,self.context);self.save()
        with patch.object(repository,'REPOSITORIES',tuple(graph)):
            repository.validate_projects(graph)
            self.tick()
        request=json.loads(self.posts[0][1]['inputs']['request'])
        self.assertEqual(request['project'],'demo')
        self.assertIn('/SNodeC/demo/',self.posts[0][0])
        self.assertEqual(request['target'],self.row['id'])
        return None

    def test_delayed_control_snapshot_cannot_erase_a_publication_event(self):
        self.tick()
        node=copy.deepcopy(self.node())
        base=copy.deepcopy(self.state)
        self.state['runs']['100']['nodes'][self.row['id']+'/snode.c']['status']='published'
        self.save()
        dispatch.transaction(self.root,dict(nodes=[('100',self.row['id']+'/snode.c',node)],base=base))
        self.assertEqual(self.node()['status'],'published')
        return None

    def test_pending_job_starting_during_observation_is_not_counted_twice(self):
        row=copy.deepcopy(self.row)
        row.update(id='debian-trixie-arm64',arch='arm64',runner='ubuntu-24.04-arm')
        row['build'].update(arch='arm64',platform='linux/arm64',runner=row['runner'])
        profiles=publication.read(self.bundle/'profiles.json')
        profiles[row['id']]=copy.deepcopy(profiles[self.row['id']])
        self.state['runs']['100']['targets'].append(row)
        self.state['runs']['100']['sources'][row['id']]=self.sources
        publication.write(self.bundle/'profiles.json',profiles)
        publication.write(self.bundle/'targets.json',self.state['runs']['100']['targets'])
        self.state['runs']['100']['profiles_hash']=repository.digest(self.bundle/'profiles.json')
        self.save()
        with patch.object(dispatch,'capacity',return_value=(3,{})):
            self.tick()
        self.assertEqual(len(self.posts),1)
        occupied={('snode.c',1501):dict(run=501,name='build / '+self.row['id'],title='Packages · '+self.node()['request']['intent'])}
        with patch.object(dispatch,'capacity',return_value=(3,occupied)):
            self.tick()
        self.assertEqual(len(self.posts),2)
        self.assertEqual(json.loads(self.posts[-1][1]['inputs']['request'])['target'],row['id'])
        return None

    def test_capture_intake_marks_missing_prerequisite_row_unsatisfiable(self):
        profiles=publication.read(self.bundle/'profiles.json')
        profile=profiles[self.row['id']]
        profile['projects']['snode.c']['matrix']={'linux':[dict(distribution='debian',suite='bookworm',image='debian:bookworm',architectures=['amd64'])]}
        profile['projects']['snode.c']['build']={'native':'ci/package/native.sh'}
        self.context['release_project']='mqttsuite'
        publication.write(self.bundle/'context.json',self.context)
        publication.write(self.bundle/'profiles.json',profiles)
        publication.write(self.bundle/'revisions.json',{'mqttsuite':'2'})
        self.state['runs']={};self.save()
        with patch('sys.argv',['publication','status',str(self.root),str(self.bundle),'-','-','pending']):
            publication.main()
        node=self.node('mqttsuite')
        self.assertEqual(node['status'],'unsatisfiable')
        self.assertIn('snode.c',node['reason'])
        self.assertEqual(node['requires'],['snode.c'])
        self.assertEqual(self.posts,[])
        return None

    def test_first_target_cascades_while_another_framework_target_is_still_queued(self):
        row=copy.deepcopy(self.row)
        row.update(id='debian-trixie-arm64',arch='arm64',runner='ubuntu-24.04-arm')
        row['build'].update(arch='arm64',platform='linux/arm64',runner=row['runner'])
        profiles=publication.read(self.bundle/'profiles.json');profiles[row['id']]=copy.deepcopy(profiles[self.row['id']])
        self.state['runs']['100']['targets'].append(row)
        self.state['runs']['100']['sources'][row['id']]=self.sources
        publication.write(self.bundle/'profiles.json',profiles)
        publication.write(self.bundle/'targets.json',self.state['runs']['100']['targets'])
        self.state['runs']['100']['profiles_hash']=repository.digest(self.bundle/'profiles.json')
        self.save();self.tick();self.feed(['snode.c']);self.tick()
        requests=[json.loads(p['inputs']['request']) for _,p in self.posts]
        self.assertTrue(any(r['project']=='mqttsuite' and r['target']==self.row['id'] for r in requests))
        self.assertFalse(any(r['project']=='mqttsuite' and r['target']==row['id'] for r in requests))
        self.assertEqual(self.runs['SNodeC/snode.c',502]['status'],'queued')
        return None

    def priority_fixture(self):
        self.feed(['snode.c'])
        info=publication.published(self.root,self.row)[0]
        self.add_capture('mqttsuite', '150', cause='dependent', cascade='100')
        self.state['runs']['100'].setdefault('nodes', {})[self.row['id'] + '/mqttsuite'] = dict(status='superseded', category='excluded')
        request=dict(capture='150',project='mqttsuite',target=self.row['id'],runner=self.row['runner'],
            publication=self.git('rev-parse','HEAD',cwd=self.root),intent='built',actor='ci[bot]',created='2026-10-20T00:00:00+00:00')
        self.state['runs']['150'].setdefault('nodes',{})[self.row['id']+'/mqttsuite']=dict(status='publishing',attempt=1,
            request=request,source={'run':900,'attempt':1},job=1900,artifact={'id':2900,'digest':'sha256:'+'f'*64},
            requires=['snode.c'],dependencies=repository.binding(info,['snode.c']))
        self.runs['SNodeC/mqttsuite',900]=dict(id=900,status='completed',conclusion='success',run_attempt=1)
        self.jobs['SNodeC/mqttsuite',900]=[dict(id=1900,run_id=900,run_attempt=1,name='build / '+self.row['id'],status='completed',runner_id=1,html_url='https://github.com/SNodeC/mqttsuite/actions/runs/900/job/1900')]
        self.artifacts['SNodeC/mqttsuite',900] = [dict(id=2900,expired=False)]
        graph=copy.deepcopy(self.graph)
        graph['demo']=copy.deepcopy(graph['snode.c']);graph['demo'].update(title='Demo',package='demo',depends_on=[],_commit='e'*40)
        later=self.base/'later';context=self.context|dict(run_id='200',release_project='demo',projects=graph)
        source={'demo':{'refs/tags/v1.0.0':'e'*40}}
        for name,value in dict(context=context,targets=[self.row],revisions={'demo':'1'},sources={self.row['id']:source},profiles={self.row['id']:dict(projects=graph,sources=source,baseline={})},checksums={}).items():
            publication.write(later/(name+'.json'),value)
        publication.record_run(later,self.state,context);self.save()
        return graph, later

    def test_all_three_ready_classes_are_dispatched_in_strict_cause_order(self):
        graph, later = self.priority_fixture()
        with patch.object(repository,'REPOSITORIES',tuple(graph)):
            self.tick({'100':self.bundle,'200':later})
        self.assertEqual([json.loads(p['inputs']['request'])['project'] for _,p in self.posts],['mqttsuite','snode.c-idp','demo'])
        self.assertIn('sign-and-publish-packages.yml',self.posts[0][0])
        self.assertEqual(self.node('snode.c-idp')['cause'],'dependent')
        self.assertEqual(self.node('demo','200')['cause'],'release')
        return None

    def test_busy_publisher_blocks_lower_classes_across_captures_with_limited_capacity(self):
        graph, later = self.priority_fixture()
        with patch.object(repository,'REPOSITORIES',tuple(graph)), patch.object(dispatch,'capacity',return_value=(3,{})):
            self.tick({'100':self.bundle,'200':later})
        self.assertEqual([json.loads(p['inputs']['request'])['project'] for _,p in self.posts],['mqttsuite'])
        info = publication.published(self.root,self.row)[0]
        self.add_capture('snode.c-idp', '160', cause='dependent', cascade='100')
        request = dict(self.node('mqttsuite', '150')['request'],capture='160',project='snode.c-idp',intent='second-built')
        self.state['runs']['160']['nodes'] = {self.row['id']+'/snode.c-idp': dict(status='publishing',request=request,
            source={'run':901,'attempt':1},job=1901,artifact={'id':2901,'digest':'sha256:'+'e'*64},requires=['snode.c'],
            dependencies=repository.binding(info,['snode.c']))}
        self.artifacts['SNodeC/snode.c-idp',901] = [dict(id=2901,expired=False)]
        self.runs['SNodeC/snode.c-idp',901] = dict(id=901,status='completed',conclusion='success',run_attempt=1)
        self.state['runs']['100']['nodes'][self.row['id'] + '/snode.c-idp'] = dict(status='superseded', category='excluded')
        self.save()
        with patch.object(repository,'REPOSITORIES',tuple(graph)), patch.object(dispatch,'capacity',return_value=(20,{})):
            self.tick({'100':self.bundle,'200':later})
        self.assertEqual(len(self.posts),1)
        self.assertEqual(self.node('demo','200')['status'],'pending')
        return None
