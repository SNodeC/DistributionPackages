"""Repository-defined graphs, target coverage, captures and scheduling causes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
from unittest.mock import patch
import yaml
from support import CoordinatorCase
from ci import dispatch, repository
from ci.publish import publication


class OrchestrationTest(CoordinatorCase):
    def test_registry_rejects_unknown_edges_cycles_and_unsupported_families(self):
        for change in ['unknown','cycle','family','duplicate','field','hook']:
            invalid=copy.deepcopy(self.graph)
            if change=='unknown':
                invalid['mqttsuite']['depends_on']=['unregistered']
            elif change=='cycle':
                invalid['snode.c']['depends_on']=['mqttsuite']
            elif change=='family':
                invalid['mqttsuite']['matrix']={'unsupported':[]}
            elif change=='duplicate':
                invalid['mqttsuite']['package']='snodec'
            elif change=='field':
                invalid['mqttsuite']['scheduler']='second-authority'
            else:
                invalid['mqttsuite']['build']['native']='../escape.sh'
            with self.subTest(change=change),self.assertRaises(ValueError):
                repository.validate_projects(invalid)
        return None

    def test_diamond_waits_for_all_exact_dependencies_and_publishes_per_target(self):
        graph = copy.deepcopy(self.graph)
        graph['join'] = copy.deepcopy(graph['snode.c-idp'])
        graph['join'].update(title='Join', package='join', depends_on=['mqttsuite', 'snode.c-idp'], _commit='d' * 40)
        self.graph = graph
        self.sources['join'] = {'refs/tags/v1.0.0': 'd' * 40}
        self.contents['SNodeC/join', 'd' * 40, 'ci/packages.json'] = json.dumps(
            {k: v for k, v in graph['join'].items() if not k.startswith('_')}).encode()
        self.state['requests']['join'] = {'v1.0.0': dict(definition=graph['join'], capture='100', revision='2')}
        self.save()
        with patch.object(repository, 'REPOSITORIES', tuple(graph)):
            self.feed(['snode.c'])
            self.tick()
            self.assertEqual({json.loads(p['inputs']['request'])['project'] for _, p in self.posts}, {'mqttsuite', 'snode.c-idp'})
            self.state = publication.read(self.root / 'status.json')
            for project, capture in [('mqttsuite', '200'), ('snode.c-idp', '300')]:
                self.state['runs'][capture] = dict(context=self.context | dict(cascade='100', release_project=project),
                    run_id=capture, revisions={project: '2'}, targets=[self.row],
                    sources={self.row['id']: {project: self.sources[project]}}, nodes={})
            self.save()
            self.feed(['snode.c', 'mqttsuite'], capture='200')
            info, path = publication.published(self.root, self.row)
            info['publications']['snode.c']['capture'] = '100'
            info['releases']['snode.c']['v1.0.0']['publications']['snode.c']['capture'] = '100'
            for project, owner in [('mqttsuite', '200'), ('snode.c-idp', '300')]:
                if project in info['sources']:
                    self.state['runs']['100']['nodes'][self.row['id'] + '/' + project].update(status='superseded', waiting=False)
                    self.state['runs'][owner]['nodes'][self.row['id'] + '/' + project] = dict(
                        status='published', requires=['snode.c'], dependencies=repository.binding(info, ['snode.c']))
            publication.write(self.root / path / 'build.json', {'targets': {'amd64': info}})
            self.save()
            self.tick()
            self.assertNotIn('join', {json.loads(p['inputs']['request'])['project'] for _, p in self.posts})
            self.feed(['snode.c', 'mqttsuite', 'snode.c-idp'], capture='300')
            info, path = publication.published(self.root, self.row)
            info['publications']['snode.c']['capture'] = '100'
            info['releases']['snode.c']['v1.0.0']['publications']['snode.c']['capture'] = '100'
            info['publications']['mqttsuite']['capture'] = '200'
            info['releases']['mqttsuite']['v1.0.0']['publications']['mqttsuite']['capture'] = '200'
            self.state['runs']['100']['nodes'][self.row['id'] + '/snode.c-idp'].update(status='superseded', waiting=False)
            self.state['runs']['300']['nodes'][self.row['id'] + '/snode.c-idp'] = dict(
                status='published', requires=['snode.c'], dependencies=repository.binding(info, ['snode.c']))
            publication.write(self.root / path / 'build.json', {'targets': {'amd64': info}})
            self.save()
            self.tick()
            self.tick()
            self.assertEqual([json.loads(p['inputs']['request'])['project'] for _, p in self.posts].count('join'), 1)
        return None

    def test_failed_branch_skips_transitive_dependents_without_blocking_sibling(self):
        self.tick();self.finish(artifact=False,conclusion='failure');self.tick()
        self.assertEqual(self.node()['status'], 'failed')
        self.assertEqual(self.node('mqttsuite'), {}, 'No dependent capture before prerequisite publication')
        self.assertEqual(len(self.posts), 1)
        self.feed(['snode.c']);self.tick()
        self.assertIn('mqttsuite',{json.loads(p['inputs']['request'])['project'] for _,p in self.posts})
        return None

    def test_coordinator_attempt_does_not_consume_source_build_attempt(self):
        with patch.dict(os.environ,GITHUB_RUN_ATTEMPT='5'):
            self.tick()
        self.assertEqual(self.node()['source']['attempt'],1)
        self.assertEqual(self.node('mqttsuite'), {})
        self.assertEqual(self.node()['builds'], 1)
        return None

    def test_capture_uses_notified_commit_even_after_tag_move_and_checks_bytes(self):
        source=self.base/'source';source.mkdir()
        subprocess.run(['git','init','-q',str(source)],check=True)
        config=copy.deepcopy(self.graph['snode.c'])
        config.update(title='Demo',package='demo',depends_on=[],matrix={'linux':[dict(distribution='debian',suite='trixie',image='debian:trixie',architectures=['amd64'])]},build={'native':'ci/package/native.sh'})
        publication.write(source/'ci/packages.json',config)
        (source/'VERSION').write_text('1.0.0\n');(source/'content').write_text('captured')
        self.git('add','.',cwd=source)
        self.git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','old',cwd=source)
        commit=self.git('rev-parse','HEAD',cwd=source);self.git('tag','v1.0.0',cwd=source)
        graph={'demo':config|dict(_commit=commit,_digest=repository.digest(source/'ci/packages.json'))}
        (source/'content').write_text('later')
        self.git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qam','new',cwd=source)
        self.git('tag','-f','v1.0.0',cwd=source)
        root,bundle=self.base/'published',self.base/'captured'
        publication.write(root/'status.json',{'allocations':{'123':{'demo':'1'}}})
        original=repository.run
        def local(*args,**kwargs):
            args=tuple(str(source) if a=='https://github.com/SNodeC/demo.git' else a for a in args)
            return 'b'*40 if args[:3]==('git','-C',str(root)) else original(*args,**kwargs)
        row=repository.rows(config)[0]
        with patch.dict(os.environ,RELEASE_PROJECT='demo',RELEASE_TAG='v1.0.0',RELEASE_SHA=commit,GITHUB_RUN_ID='123'), \
            patch.object(repository,'PROJECTS',graph),patch.object(repository,'REPOSITORIES',('demo',)),patch.object(repository,
            'ROW_PROJECTS',{row['id']:graph}),patch.object(publication,'published',return_value=({},'feed')),patch.object(repository,'run',side_effect=local):
            repository.prepare(root,bundle)
        archive=next((bundle/'archives').iterdir())
        with tarfile.open(archive) as stream:
            member=next(m for m in stream if m.name.endswith('/content'))
            self.assertEqual(stream.extractfile(member).read(),b'captured')
        repository.unchanged(bundle)
        archive.write_bytes(b'tampered')
        with self.assertRaisesRegex(RuntimeError,'archive changed'):
            repository.unchanged(bundle)
        return None

    def test_verified_coordinator_identity_reaches_isolated_native_builds(self):
        shared = yaml.load((repository.ROOT / '.github/workflows/build-packages.yml').read_text(), Loader=yaml.BaseLoader)
        validation = next(s for s in shared['jobs']['build']['steps'] if s.get('name') == 'Validate captured build')
        self.assertIn('PACKAGE_COORDINATOR=${{ job.workflow_repository }}', validation['run'])
        self.assertIn('-e PACKAGE_COORDINATOR', (repository.ROOT / 'ci/build/linux.sh').read_text())
        self.assertIn('PACKAGE_COORDINATOR="$PACKAGE_COORDINATOR"', (repository.ROOT / 'ci/build/raspberrypi.sh').read_text())
        return None

    def test_reusable_build_has_no_package_repository_write_tokens(self):
        shared=yaml.load((repository.ROOT/'.github/workflows/build-packages.yml').read_text(),Loader=yaml.BaseLoader)
        self.assertIn('workflow_call',shared['on'])
        self.assertNotIn('push',shared['on'])
        for job in shared['jobs'].values():
            for step in job.get('steps',[]):
                if step.get('uses','').startswith('actions/create-github-app-token@'):
                    self.assertEqual(step['with']['repositories'],'${{ steps.location.outputs.name }}')
                    self.assertNotEqual(step['with'].get('permission-contents'),'write')
                self.assertNotIn('ci/publish/status.sh',step.get('run',''))
        publisher=yaml.load((repository.ROOT/'.github/workflows/sign-and-publish-packages.yml').read_text(),Loader=yaml.BaseLoader)
        self.assertIn('workflow_dispatch',publisher['on'])
        self.assertEqual(publisher['jobs']['write']['concurrency']['group'],'package-publication')
        return None

    def test_source_only_release_does_not_admit_framework(self):
        generation=self.state['runs']['100']
        generation['context']['release_project']='mqttsuite'
        generation['revisions']={'mqttsuite':'3'}
        generation['nodes']={}
        publication.write(self.bundle/'context.json',generation['context'])
        publication.write(self.bundle/'revisions.json',generation['revisions'])
        generation['profiles_hash']=repository.digest(self.bundle/'profiles.json')
        self.save();self.feed(['snode.c'],capture='prior',revision='1')
        profiles=publication.read(self.bundle/'profiles.json')
        profiles[self.row['id']]['baseline']=publication.published(self.root,self.row)[0]
        publication.write(self.bundle/'profiles.json',profiles)
        self.state['runs']['100']['profiles_hash']=repository.digest(self.bundle/'profiles.json')
        self.save();self.tick()
        self.assertEqual([json.loads(p['inputs']['request'])['project'] for _,p in self.posts],['mqttsuite'])
        self.assertEqual(self.node('mqttsuite')['cause'],'release')
        return None
