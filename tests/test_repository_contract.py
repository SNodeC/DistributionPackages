"""Repository ownership, policy overrides, capacity observations and receipt replay."""
import copy
import gzip
import json
import os
from pathlib import Path
import tempfile
import unittest
from support import PinnedJsonCase
from unittest.mock import patch
from ci import repository, dispatch
from ci.publish import publication, openwrt


class ContractTest(PinnedJsonCase):
    def test_master_contains_only_registration_and_real_policy_overrides(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'master.json'
            publication.write(path,dict(repositories=['demo_repo']))
            self.assertEqual(repository.load_master(path)['settings'],dict(capacity='plan',headroom=2,dependent_version='published',rebuild_overlap=True))
            for names in [['..'],['demo','Demo'],['a/b']]:
                publication.write(path,dict(repositories=names))
                with self.subTest(names=names),self.assertRaises(ValueError):
                    repository.load_master(path)
            settings=dict(capacity=7,headroom=1,dependent_version='latest',rebuild_overlap=False)
            publication.write(path,dict(repositories=['demo'],settings=settings))
            self.assertEqual(repository.load_master(path)['settings'],settings)
            for extra in [dict(matrix=[]),dict(depends_on=[]),dict(build={}),dict(settings={'fairness':True}),dict(settings={'capacity':True}),dict(settings={'headroom':-1}),dict(settings={'dependent_version':'branch'}),dict(settings={'dependent_version':[]}),dict(settings={'rebuild_overlap':'yes'})]:
                publication.write(path,dict(repositories=['demo'])|extra)
                with self.subTest(extra=extra),self.assertRaises(ValueError):
                    repository.load_master(path)
        return None

    def test_malformed_pinned_json_and_matrix_are_actionable(self):
        for value in ([], None, {'_commit':'a'*40}):
            with self.subTest(value=value), patch.object(repository,'content',return_value=json.dumps(value).encode()), self.assertRaisesRegex(ValueError,'Source definitions'):
                repository.definition_data.cache_clear()
                repository.definition('snode.c','a'*40)
        for matrix in (None, [], {'linux':[dict(distribution='debian',suite='trixie',image='debian:trixie',architectures=['mips'])]}, {'linux':[dict(distribution='debian',suite='..',image='debian:trixie',architectures=['amd64'])]}):
            with self.subTest(matrix=matrix), self.assertRaises(ValueError):
                repository.rows({'matrix':matrix})
        repository.definition_data.cache_clear()
        return None

    def test_openwrt_release_requires_numeric_supported_patch(self):
        config = copy.deepcopy(repository.PROJECTS['snode.c'])
        for release in ['24.10.not-a-version', '25.12.1/escape', '23.05.9']:
            config['matrix'] = {'openwrt':{'releases':[release],'targets':{'x86_64':'x86/64'}}}
            with self.subTest(release=release), self.assertRaisesRegex(ValueError, 'Unsupported OpenWrt release'):
                repository.rows(config)
        return None

    def test_cas_reservation_deduplicates_events_and_accepts_moved_tag_new_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with patch.dict(os.environ,RELEASE_REQUESTED_AT='2026-10-20T00:00:00Z',RELEASE_RUN='99',RELEASE_SHA='a'*40,RELEASE_TAG='v1.0.0'):
                allocation=publication.reserve(root,'snode.c','100')
                self.assertEqual(publication.reserve(root,'snode.c','100'),allocation)
                with self.assertRaisesRegex(ValueError,'already has a capture'):
                    publication.reserve(root,'snode.c','101')
                self.assertNotIn('101',publication.read(root/'status.json')['allocations'])
                with patch.dict(os.environ,RELEASE_RUN='100',RELEASE_SHA='b'*40):
                    moved=publication.reserve(root,'snode.c','101')
                self.assertEqual(int(moved['snode.c']),int(allocation['snode.c'])+1)
                self.assertEqual(publication.read(root/'status.json')['requests']['snode.c']['sha'],'b'*40)
        return None

    def test_pinned_per_row_definitions_select_last_published_and_pending_explicit(self):
        graph=copy.deepcopy(repository.PROJECTS)
        root_config=graph['snode.c']
        root_config['build']={'native':'ci/package/native.sh'}
        root_config['matrix']={'linux':[dict(distribution='debian',suite='trixie',image='debian:trixie',architectures=['amd64','arm64'])]}
        seen=[]
        def definition(project,commit):
            seen.append((project,commit))
            return copy.deepcopy(graph[project])|dict(_commit=commit,_digest='f'*64)
        def api(path,*args,**kwargs):
            return {'default_branch':'main'} if '/git/' not in path else {'object':{'sha':'d'*40}}
        def published(root,row):
            ref='b'*40 if row['arch']=='amd64' else 'c'*40
            return dict(sources={'mqttsuite':{'refs/tags/v1.0.0':ref}},versions={'mqttsuite':'1.0.0-1~trixie'}),'feed'
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            publication.write(root/'status.json',{})
            with patch.object(repository,'DEFINITIONS',root/'definitions.json'),patch.object(repository,'definition',side_effect=definition),patch.object(dispatch,'api',side_effect=api),patch.object(publication,'published',side_effect=published),patch.dict(repository.PROJECTS,repository.PROJECTS,clear=True),patch.dict(repository.ROW_PROJECTS,{},clear=True):
                repository.configure(root,'snode.c','a'*40,root_config)
                self.assertEqual(repository.ROW_PROJECTS['debian-trixie-amd64']['mqttsuite']['_commit'],'b'*40)
                self.assertEqual(repository.ROW_PROJECTS['debian-trixie-arm64']['mqttsuite']['_commit'],'c'*40)
                publication.write(root/'status.json',dict(requests={'mqttsuite':dict(sha='e'*40,tag='v2.0.0',revision='2')}))
                repository.configure(root,'snode.c','a'*40,root_config)
                self.assertTrue(all(p['mqttsuite']['_commit']=='e'*40 and p['mqttsuite']['_tag']=='v2.0.0' for p in repository.ROW_PROJECTS.values()))
                with self.assertRaisesRegex(ValueError,'does not match'):
                    repository.configure(root,'snode.c','a'*40,root_config|dict(title='forged'))
        return None

    def test_identical_receipt_is_noop_but_conflicting_bytes_and_path_escape_fail(self):
        row=publication.targets()[0]
        with tempfile.TemporaryDirectory() as temporary:
            root,bundle,incoming=(Path(temporary)/n for n in ['root','bundle','incoming'])
            incoming.mkdir()
            name='snodec_1.0.0_amd64.deb'
            (incoming/name).write_bytes(b'original')
            receipt=dict(capture='100',source={'run':42,'attempt':1},job=43,artifact={'id':44,'digest':'sha256:'+'a'*64})
            checksums={name:repository.digest(incoming/name)}
            info=dict(publications={'snode.c':receipt|dict(unsigned_files=checksums)})
            publication.write(incoming/'build.json',dict(files=checksums,sources={'snode.c':{'refs/tags/v1.0.0':'a'*40}}))
            with patch.dict(os.environ,BUILD_RECEIPT=json.dumps(receipt)),patch.object(publication,'published',return_value=(info,'feed')),patch.object(publication,'activate',side_effect=AssertionError('identical receipt must not republish')):
                publication.publish(root,bundle,incoming,row,{'context':{'contract':3}},'snode.c')
                (incoming/name).write_bytes(b'changed')
                publication.write(incoming/'build.json',dict(files={name:repository.digest(incoming/name)},sources={'snode.c':{'refs/tags/v1.0.0':'a'*40}}))
                with self.assertRaisesRegex(RuntimeError,'Different package content'):
                    publication.publish(root,bundle,incoming,row,{'context':{'contract':3}},'snode.c')
                publication.write(incoming/'build.json',dict(files={'../escape':'a'*64}))
                with self.assertRaisesRegex(RuntimeError,'checksum mismatch'):
                    publication.publish(root,bundle,incoming,row,{'context':{'contract':3}},'snode.c')
        return None

    def test_generic_opkg_rebase_preserves_newer_siblings_and_third_product(self):
        with tempfile.TemporaryDirectory() as temporary:
            incoming,previous=(Path(temporary)/n for n in ['incoming','previous'])
            incoming.mkdir();previous.mkdir()
            graph=repository.PROJECTS|{'demo':dict(package='demo')}
            (incoming/'Packages').write_text('Package: demo\nVersion: 2-r2\n\nPackage: mqttsuite\nVersion: 1-r1\n\n')
            (previous/'Packages').write_text('Package: demo\nVersion: 1-r1\n\nPackage: mqttsuite\nVersion: 3-r3\n\nPackage: snodec\nVersion: 2-r4\n\n')
            info=dict(series='24.10',files={},sources={p:{'refs/tags/v1.0.0':'a'*40} for p in graph})
            publication.write(previous/'build.json',info)
            with patch.object(repository,'PROJECTS',graph),patch.object(repository,'REPOSITORIES',tuple(graph)):
                openwrt.reindex(incoming,previous,info,'demo',info)
            index=(incoming/'Packages').read_text()
            for value in ['2-r2','3-r3','2-r4']:
                self.assertIn('Version: '+value,index)
            self.assertNotIn('Version: 1-r1',index)
            self.assertEqual(gzip.decompress((incoming/'Packages.gz').read_bytes()).decode(),index)
        return None


class CapacityTest(unittest.TestCase):
    def setUp(self):
        self.org=dict(plan={'name':'free'},public_repos=1,total_private_repos=1)
        self.jobs=[dict(id=1,name='build',status='in_progress',runner_id=2,labels=['ubuntu-24.04-arm']),dict(id=2,status='queued',runner_id=None,labels=['ubuntu-24.04']),dict(id=3,status='in_progress',runner_id=3,labels=['self-hosted'])]
        self.seen=[]
        return None

    def api(self,path,payload=None,token=None):
        self.seen.append(path)
        if path=='orgs/SNodeC':
            value=self.org
        elif path.startswith('orgs/SNodeC/repos'):
            value=[dict(name='public'),dict(name='private')]
        elif '/attempts/' in path:
            jobs = self.jobs if '/runs/12/' in path else [dict(id=1000+int(path.split('/runs/')[1].split('/')[0]),status='queued',runner_id=None)]
            value=dict(total_count=len(jobs),jobs=jobs)
        elif 'status=queued' in path:
            value=dict(total_count=50,workflow_runs=[dict(id=i,run_attempt=1) for i in range(50)])
        else:
            value=dict(total_count=1,workflow_runs=[dict(id=12,run_attempt=1)])
        return value

    def test_all_repositories_count_only_occupied_jobs_including_arm(self):
        with patch.dict(os.environ,OBSERVER_TOKEN='read-only-fixture'),patch.object(dispatch,'api',side_effect=self.api):
            free,occupied=dispatch.capacity()
        self.assertEqual(free,18)
        self.assertEqual(set(occupied),{('public',1),('private',1)})
        self.assertTrue(any('/private/' in path for path in self.seen))
        return None

    def test_waiting_run_is_inspected_for_allocated_jobs(self):
        original = self.api
        def waiting(path, payload=None, token=None):
            value = original(path, payload, token)
            if '/actions/runs?status=' in path and 'status=waiting' not in path:
                value = dict(total_count=0,workflow_runs=[])
            return value
        with patch.dict(os.environ,OBSERVER_TOKEN='fixture'),patch.object(dispatch,'api',side_effect=waiting):
            free, occupied = dispatch.capacity()
        self.assertEqual(free,18)
        self.assertEqual(set(occupied),{('public',1),('private',1)})
        return None

    def test_explicit_limit_and_unknown_plan_or_runner_never_become_zero(self):
        with patch.dict(os.environ,OBSERVER_TOKEN='fixture'),patch.object(dispatch,'api',side_effect=self.api),patch.dict(repository.CONFIG['settings'],capacity=8):
            self.org.pop('plan')
            self.assertEqual(dispatch.capacity()[0],6)
            with patch.dict(repository.CONFIG['settings'],capacity='plan'),self.assertRaisesRegex(ValueError,'plan is unavailable'):
                dispatch.capacity()
            self.jobs[0]['runner_id']=None
            with self.assertRaisesRegex(ValueError,'unknown runner'):
                dispatch.capacity()
        return None

    def test_incomplete_inventory_and_truncated_or_failed_listing_fail_closed(self):
        with patch.dict(os.environ,OBSERVER_TOKEN='fixture'),patch.object(dispatch,'api',side_effect=self.api):
            self.org['total_private_repos']=2
            with self.assertRaisesRegex(ValueError,'complete organization inventory'):
                dispatch.capacity()
        with patch.object(dispatch,'api',return_value={'total_count':1000,'jobs':[]}):
            with self.assertRaisesRegex(ValueError,'truncated'):
                dispatch.listing('repos/SNodeC/private/actions/runs/12/jobs','jobs')
        for status in [0,403,429,500]:
            with self.subTest(status=status),patch.dict(os.environ,OBSERVER_TOKEN='fixture'),patch.object(dispatch,'api',side_effect=dispatch.ApiError(status,'unknown observation')),self.assertRaises(dispatch.ApiError):
                dispatch.capacity()
        return None


class ArtifactBytesTest(unittest.TestCase):
    def test_download_digest_and_zip_paths_are_verified_before_extracting(self):
        import hashlib
        import io
        import zipfile
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name in ['linux/debian/trixie/amd64/package.deb','../escape']:
                archive=io.BytesIO()
                with zipfile.ZipFile(archive,'w') as contents:
                    contents.writestr(name,b'package bytes')
                data=archive.getvalue()
                request=dict(project='demo',artifact=dict(id=123,digest='sha256:'+hashlib.sha256(data).hexdigest()))
                def transport(*args,**kwargs):
                    kwargs['stdout'].write(data)
                    return None
                with patch.object(dispatch.subprocess,'run',side_effect=transport):
                    if name.startswith('..'):
                        with self.assertRaisesRegex(ValueError,'Unsafe artifact'):
                            dispatch.artifact(request,root/'unsafe')
                    else:
                        dispatch.artifact(request,root/'valid')
                        self.assertEqual((root/'valid'/name).read_bytes(),b'package bytes')
                        request['artifact']['digest']='sha256:'+'0'*64
                        with self.assertRaisesRegex(ValueError,'digest mismatch'):
                            dispatch.artifact(request,root/'changed')
                        self.assertFalse((root/'changed').exists())
        return None


class AuthorityTest(unittest.TestCase):
    def test_notify_app_cannot_request_operator_retry_or_clear_observation_cooldown(self):
        for actor,permission,allowed in [('notify[bot]','admin',False),('reader','read',False),('maintainer','write',True)]:
            with self.subTest(actor=actor),patch.dict(os.environ,GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_ACTOR=actor,PACKAGE_RETRY='100/mqttsuite/target',PACKAGE_REPORT=''),patch('sys.argv',['dispatch','control','unused']),patch.object(dispatch,'api',return_value={'permission':permission}),patch.object(dispatch,'transaction') as transaction,patch.object(dispatch,'read',return_value={'runs':{'100':{'nodes':{'target/mqttsuite':{'status':'failed'}}}}}),patch.object(dispatch,'tick',return_value=False):
                if allowed:
                    dispatch.main()
                    self.assertTrue(any(call.args[1].get('retry') for call in transaction.call_args_list))
                else:
                    with self.assertRaisesRegex(ValueError,'human with write access'):
                        dispatch.main()
                    self.assertFalse(any(call.args[1].get('retry') for call in transaction.call_args_list))
                    if actor.endswith('[bot]'):
                        transaction.assert_not_called()
        return None

    def test_publication_workflow_rejects_notify_app_before_artifact_or_signing(self):
        import subprocess
        import yaml
        workflow=yaml.load((repository.ROOT/'.github/workflows/sign-and-publish-packages.yml').read_text(),Loader=yaml.BaseLoader)
        steps=workflow['jobs']['write']['steps']
        guard=next(step for step in steps if step.get('name')=='Verify coordinator publication authority')
        guide=yaml.load((repository.ROOT/'.github/workflows/publish-guides-and-status.yml').read_text(),Loader=yaml.BaseLoader)
        guide_steps=guide['jobs']['render']['steps']
        operator=next(step for step in guide_steps if step.get('name')=='Verify operator authority')
        token=next(step for step in guide_steps if step.get('uses','').startswith('actions/create-github-app-token@'))
        self.assertLess(guide_steps.index(operator),guide_steps.index(token))
        self.assertEqual(operator['run'],'python3 -m ci.dispatch operator')
        first_download=next(step for step in steps if step.get('uses','').startswith('actions/download-artifact@'))
        self.assertLess(steps.index(guard),steps.index(first_download))
        self.assertEqual(guard['env']['EXPECTED_ACTOR'],'${{ steps.publisher.outputs.app-slug }}[bot]')
        for actor,expected in [('notify[bot]',False),('coordinator[bot]',True)]:
            result=subprocess.run(['bash','-eu','-c',guard['run']],env=os.environ|dict(GITHUB_ACTOR=actor,GITHUB_TRIGGERING_ACTOR=actor,EXPECTED_ACTOR='coordinator[bot]'))
            self.assertEqual(result.returncode==0,expected)
        return None
