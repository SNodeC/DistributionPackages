"""Offline graph scheduling, immutable capture and shared workflow contracts."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import yaml
from ci import dispatch, repository
from ci.publish import publication


class OrchestrationTest(unittest.TestCase):
    def graph(self):
        graph = {}
        for name, deps in [('base', []), ('left', ['base']), ('right', ['base']), ('top', ['left', 'right'])]:
            graph[name] = dict(title=name, package=name, depends_on=deps, families=['linux'])
        return graph

    def test_registry_rejects_unknown_edges_cycles_and_unsupported_families(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'projects.json'
            graph = self.graph()
            path.write_text(json.dumps(dict(reversed(list(graph.items())))))
            loaded = repository.load_projects(path)
            self.assertEqual(next(iter(loaded)), 'base')
            with patch.object(repository, 'PROJECTS', loaded):
                self.assertEqual(set(repository.affected('base')), set(graph))
                self.assertEqual(repository.affected('left'), ('left', 'top'))
                self.assertEqual(set(repository.dependencies('top')), {'base', 'left', 'right'})
            for change in ['unknown', 'cycle', 'families', 'duplicate', 'field']:
                invalid = copy.deepcopy(graph)
                if change == 'unknown':
                    invalid['top']['depends_on'] = ['missing']
                elif change == 'cycle':
                    invalid['base']['depends_on'] = ['top']
                elif change == 'families':
                    invalid['top']['families'] = ['openwrt']
                elif change == 'duplicate':
                    invalid['top']['package'] = 'base'
                else:
                    invalid['top']['extra'] = True
                path.write_text(json.dumps(invalid))
                with self.subTest(change=change), self.assertRaises(ValueError):
                    repository.load_projects(path)

    def test_diamond_waits_for_all_exact_dependencies_and_publishes_per_target(self):
        graph = self.graph()
        row = next(row for row in publication.targets() if row['id'] == 'debian-trixie-amd64')
        sources = {name: {f'refs/tags/v1.0.0': name} for name in graph}
        revisions = dict.fromkeys(graph, '2')
        profile = dict(sources=sources, baseline={})
        with tempfile.TemporaryDirectory() as tmp, patch.object(repository, 'PROJECTS', graph), \
             patch.object(dispatch, 'PROJECTS', graph):
            bundle = Path(tmp)
            for name, value in [('targets', [row]), ('profiles', {row['id']: profile}), ('revisions', revisions)]:
                publication.write(bundle / (name + '.json'), value)
            for versions, expected in [({'base': '1.0.0-2'}, {'left', 'right'}),
                                       ({'base': '1.0.0-2', 'left': '1.0.0-2'}, {'right'}),
                                       ({'base': '1.0.0-2', 'left': '1.0.0-2', 'right': '1.0.0-2'}, {'top'})]:
                info = dict(versions=versions, sources=sources)
                publication.write(bundle / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
                with self.subTest(versions=versions), patch('sys.argv',
                        ['dispatch', 'dependents', str(bundle), row['id'], 'a' * 40, tmp]), \
                     patch.object(dispatch, 'build') as build:
                    dispatch.main()
                    self.assertEqual({call.args[1] for call in build.call_args_list}, expected)
            info['sources'] = sources | {'right': 'superseded'}
            self.assertFalse(dispatch.ready(profile, revisions, 'top', info))
            info['sources'] = sources
            info['versions']['right'] = '1.0.0-3'
            self.assertFalse(dispatch.ready(profile, revisions, 'top', info))

    def test_coordinator_attempt_does_not_consume_source_build_attempt(self):
        row = publication.targets()[0]
        with tempfile.TemporaryDirectory() as tmp:
            root, bundle = Path(tmp) / 'root', Path(tmp) / 'bundle'
            context = dict(run_id='123', run_url='capture-url', destination='SNodeC/Packages', release_project='snode.c')
            for name, value in dict(context=context, targets=[row], revisions={'snode.c': '1'}, profiles={}, sources={}).items():
                publication.write(bundle / (name + '.json'), value)
            publication.write(root / 'status.json', dict(repository='SNodeC/Packages', branch='main', targets={}, runs={}))
            with patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '5', 'BUILD_ATTEMPT': ''}), \
                 patch.object(publication, 'render'), patch('sys.argv',
                    ['publication', 'status', str(root), str(bundle), '-', '-', 'pending']):
                publication.main()
            state = publication.read(root / 'status.json')
            self.assertEqual(state['targets'][row['id'] + '/snode.c']['attempt'], 0)
            publication.event(state, state['runs']['123'], row, 'snode.c', 'running', 1)
            self.assertEqual(state['targets'][row['id'] + '/snode.c']['status'], 'running')

    def test_failed_branch_skips_transitive_dependents_without_blocking_sibling(self):
        graph = self.graph()
        row = next(row for row in publication.targets() if row['id'] == 'debian-trixie-amd64')
        generation = dict(revisions=dict.fromkeys(graph, '2'), run_id='123', run_url='url',
                          targets=[row], context={'release_project': 'base'})
        state = {'targets': {}}
        with patch.object(repository, 'PROJECTS', graph), patch.object(publication, 'PROJECTS', graph), \
             patch.object(publication, 'REPOSITORIES', tuple(graph)):
            for project in graph:
                publication.event(state, generation, row, project, 'pending', 0)
            publication.event(state, generation, row, 'left', 'failed', 1)
            self.assertEqual(state['targets'][row['id'] + '/top']['status'], 'skipped')
            self.assertEqual(state['targets'][row['id'] + '/right']['status'], 'pending')
            publication.event(state, generation, row, 'left', 'running', 2)
            publication.event(state, generation, row, 'left', 'published', 2)
            publication.event(state, generation, row, 'top', 'running', 1)
            self.assertEqual(state['targets'][row['id'] + '/top']['status'], 'running')
            with tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(set(publication.reserve(Path(tmp), 'left', '123')), {'left', 'top'})

    def test_capture_uses_notified_commit_even_after_tag_move_and_checks_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, published, bundle = (root / name for name in ('source', 'published', 'bundle'))
            subprocess.run(['git', 'init', '-q', str(source)], check=True)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(source), '-c', 'user.name=Test',
                    '-c', 'user.email=test@example.invalid', '-c', 'commit.gpgsign=false', *args], text=True).strip()
            (source / 'VERSION').write_text('1.0.0\n')
            (source / 'content').write_text('captured')
            git('add', '.')
            git('commit', '-qm', 'old')
            commit = git('rev-parse', 'HEAD')
            git('tag', 'v1.0.0')
            (source / 'content').write_text('later')
            git('commit', '-qam', 'new')
            git('tag', '-f', 'v1.0.0')
            graph = {'demo': dict(title='Demo', package='demo', depends_on=[], families=['linux'])}
            row = dict(id='debian-trixie-amd64', distribution='debian', suite='trixie', arch='amd64', family='linux')
            publication.write(published / 'status.json', {'allocations': {'123': {'demo': '1'}}})
            original = repository.run
            def local(*args, **kwargs):
                args = tuple(str(source) if arg == 'https://github.com/SNodeC/demo.git' else arg for arg in args)
                if args[:3] == ('git', '-C', str(published)):
                    result = 'b' * 40
                else:
                    result = original(*args, **kwargs)
                return result
            with patch.dict(os.environ, {'RELEASE_PROJECT': 'demo', 'RELEASE_TAG': 'v1.0.0', 'RELEASE_SHA': commit, 'GITHUB_RUN_ID': '123'}), \
                 patch.object(repository, 'PROJECTS', graph), patch.object(repository, 'REPOSITORIES', ('demo',)), \
                 patch.object(publication, 'targets', return_value=[row]), patch.object(publication, 'published', return_value=({}, 'feed')), \
                 patch.object(repository, 'run', side_effect=local), patch.object(repository, 'sources', side_effect=AssertionError('must not resolve moved tag')):
                repository.prepare(published, bundle)
            archive = next((bundle / 'archives').iterdir())
            with tarfile.open(archive) as stream:
                member = next(member for member in stream if member.name.endswith('/content'))
                self.assertEqual(stream.extractfile(member).read(), b'captured')
            repository.unchanged(bundle)
            archive.write_bytes(b'tampered')
            with self.assertRaisesRegex(RuntimeError, 'archive changed'):
                repository.unchanged(bundle)

    def test_reusable_build_has_no_package_repository_write_tokens(self):
        root = repository.ROOT
        shared = yaml.load((root / '.github/workflows/build-packages.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertIn('workflow_call', shared['on'])
        self.assertNotIn('push', shared['on'])
        for job in shared['jobs'].values():
            for step in job.get('steps', []):
                if step.get('uses', '').startswith('actions/create-github-app-token@'):
                    self.assertEqual(step['with']['repositories'], 'DistributionPackages')
                self.assertNotIn('ci/publish/status.sh', step.get('run', ''))
        publisher = yaml.load((root / '.github/workflows/sign-and-publish-packages.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(publisher['on']['repository_dispatch']['types'], ['sign-and-publish-packages', 'package-build-status'])
        publish = publisher['jobs']['write']['steps']
        handoff = next(step for step in publish if step.get('name') == 'Dispatch dependent project after successful publication')
        self.assertIn("steps.write.outcome == 'success'", handoff['if'])
        self.assertIn('published', handoff['run'])


if __name__ == '__main__':
    unittest.main()
