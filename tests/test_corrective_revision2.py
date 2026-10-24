"""Public-boundary reproductions for the revision-2 correction budget review."""
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import subprocess
import time
import tempfile
from pathlib import Path
from unittest.mock import patch

from ci import dispatch, repository
from ci.publish import publication
from support import CoordinatorCase


class CorrectiveRevision2Test(CoordinatorCase):
    def test_rejected_publisher_dispatch_releases_commitment_immediately(self):
        self.tick()
        self.finish()
        original = self.api

        def api(path, payload=None, token=None):
            if payload is not None and 'sign-and-publish-packages.yml/dispatches' in path:
                raise dispatch.ApiError(422, 'Publication dispatch rejected')
            return original(path, payload, token)

        with patch.object(dispatch, 'api', side_effect=api):
            self.tick()
        node = self.node()
        self.assertEqual(node['status'], 'failed')
        self.assertFalse(node['waiting'])
        self.assertNotIn('publisher_intent', node)
        self.assertEqual(node.get('publications', 0), 0)
        self.assertIn('artifact', node)
        self.assertEqual(node['job'], 1501)
        self.assertIn('Dispatch rejected', node['reason'])
        return None

    def test_publisher_observation_preserves_source_artifact_job_identity(self):
        self.tick()
        self.finish()
        self.tick()
        before = self.node()
        self.assertIn('publisher', before)
        self.runs[dispatch.COORDINATOR, before['publisher']].update(status='in_progress', run_attempt=2)
        self.jobs[dispatch.COORDINATOR, before['publisher']][0].update(
            name='write', status='in_progress', run_attempt=2, runner_id=3)
        self.tick()
        after = self.node()
        self.assertFalse(after['waiting'])
        self.assertEqual(after['job'], before['job'])
        self.assertEqual(after['job_url'], before['job_url'])
        self.assertEqual(after['attempt'], before['attempt'])
        self.assertEqual(after['source'], before['source'])
        self.assertEqual(after['artifact'], before['artifact'])
        return None

    def test_malformed_capture_observation_does_not_abort_independent_admission(self):
        self.state['requests'] = {'mqttsuite': {'v2.0.0': dict(definition=copy.deepcopy(self.graph['mqttsuite']),
            **dict(capture='200', sha='f' * 40, tag='v2.0.0', revision='3', eligible=True))}}
        self.save()
        self.runs[dispatch.COORDINATOR, 200] = {}
        self.tick()
        request = publication.read(self.root / 'status.json')['requests']['mqttsuite']['v2.0.0']
        self.assertTrue(request['eligible'])
        self.assertEqual(request['sha'], 'f' * 40)
        self.assertEqual(request['observation']['category'], 'configuration')
        self.assertIn('event', request['observation']['reason'])
        self.assertEqual([json.loads(p['inputs']['request'])['project'] for _, p in self.posts], ['snode.c'])
        return None

    def test_malformed_capacity_is_recorded_and_never_admits_new_work(self):
        with patch.object(dispatch, 'capacity', side_effect=KeyError('runner_id')):
            self.tick()
        state = publication.read(self.root / 'status.json')
        self.assertEqual(state['observation']['category'], 'configuration')
        self.assertIn('runner_id', state['observation']['reason'])
        self.assertNotIn('request', self.node())
        self.assertEqual(self.posts, [])
        return None

    def test_presentation_revision_decoder_does_not_need_source_repository_access(self):
        info = dict(sources=self.sources, revision='2', context=dict(build_project='snode.c'), versions={'snode.c': '1.0.0-2~trixie'})
        with patch.object(repository, 'definition', side_effect=AssertionError('Presentation must not fetch source JSON')):
            self.assertEqual(repository.project_revision(info, 'snode.c'), 2)
        return None

    def test_chain_and_diamond_replacements_compare_each_prerequisites_own_counter(self):
        from support import feed_manifest
        names = ('framework', 'first', 'second', 'join', 'tail')
        edges = dict(framework=[], first=['framework'], second=['framework'], join=['first', 'second'], tail=['join'])
        graph = {p: copy.deepcopy(self.graph['snode.c']) | dict(
            package=p, title=p, depends_on=edges[p], _commit=chr(97 + i) * 40) for i, p in enumerate(names)}
        self.graph = graph
        self.sources = {p: {'refs/tags/v1.0.0': c['_commit']} for p, c in graph.items()}
        for project, config in graph.items():
            self.contents['SNodeC/' + project, config['_commit'], 'ci/packages.json'] = json.dumps(
                {k: v for k, v in config.items() if not k.startswith('_')}).encode()
        self.state['requests'] = {p: {'v1.0.0': dict(definition=c, sha=c['_commit'], capture='100', revision='2')}
                                  for p, c in graph.items()}
        self.state['runs'] = {}
        self.context.update(projects=graph, release_project='framework')
        for name, value in dict(context=self.context, revisions={'framework': '2'},
                                sources={self.row['id']: self.sources}, profiles={self.row['id']: dict(
                                    projects=graph, sources=self.sources, baseline={})}).items():
            publication.write(self.bundle / (name + '.json'), value)
        publication.record_run(self.bundle, self.state, self.context)
        for capture, project, revision in [('200', 'first', '3'), ('300', 'first', '4'),
                                            ('400', 'second', '2'), ('500', 'tail', '999')]:
            self.state['runs'][capture] = dict(run_id=capture, context=self.context | dict(
                release_project=project, cascade='100', cause='dependent'), revisions={project: revision},
                targets=[self.row], sources={self.row['id']: {project: self.sources[project]}},
                nodes={self.row['id'] + '/' + project: dict(status='superseded', category='excluded')})
        self.state['runs']['100']['nodes'] = {self.row['id'] + '/' + p: dict(status='superseded', category='excluded')
                                             for p in ('first', 'second')}
        info = dict(sources={p: self.sources[p] for p in ('framework', 'first', 'second')},
                    versions={p: '1.0.0-' + ('4' if p == 'first' else '2') + '~trixie'
                              for p in ('framework', 'first', 'second')},
                    publications={p: dict(capture=c, revision=r) for p, c, r in
                                  [('framework', '100', '2'), ('first', '300', '4'), ('second', '400', '2')]})
        publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': feed_manifest(info, graph)}})
        self.save()
        with patch.object(repository, 'REPOSITORIES', names), patch.object(dispatch, 'REPOSITORIES', names), \
            patch.object(publication, 'REPOSITORIES', names), patch.dict(repository.PROJECTS, graph, clear=True),                  \
            patch.dict(repository.CONFIG['settings'], rebuild_overlap=False):
            self.tick()
            requests = [json.loads(p['inputs']['request']) for _, p in self.posts]
            self.assertEqual([r['project'] for r in requests], ['join'])
            self.assertEqual(requests[0]['kind'], 'capture')
            self.assertEqual(self.node('join')['builds'], 1)
            self.assertNotIn('request', self.node('tail'))
            self.tick()
            self.assertEqual(len(self.posts), 1)
        return None

    def queued_terminal(self, publisher=False):
        self.posts.clear()
        self.feed(['snode.c'], capture='older', revision='2')
        node = dict(status='superseded', category='excluded', reason='New request owns the row', cause='release',
                    artifact={'id': 900, 'digest': 'sha256:' + 'a' * 64}, builds=1, publications=2, waiting=True,
                    request=dict(intent='old-intent', created='2026-10-20T00:00:00Z', actor='ci[bot]'),
                    source=dict(run=800, attempt=1))
        if publisher:
            node.update(publisher=800, publisher_intent='old-publication', publish_created='2026-10-20T00:00:00Z')
        self.state['runs']['100']['nodes'] = {self.row['id'] + '/snode.c': node}
        current = copy.deepcopy(self.state['runs']['100'])
        current.update(run_id='600', context=self.context | dict(run_id='600'), nodes={}, revisions={'snode.c': '3'})
        self.state['runs']['600'] = current
        self.save()
        self.feed(['snode.c'], capture='600', revision='3')
        repo = dispatch.COORDINATOR if publisher else 'SNodeC/snode.c'
        self.runs[repo, 800] = dict(status='queued', run_attempt=1)
        self.jobs[repo, 800] = [dict(id=1800, name='write' if publisher else 'build / ' + self.row['id'],
                                   run_attempt=1, status='queued', runner_id=0, html_url='source-job')]
        return repo, copy.deepcopy(node)

    def test_terminal_source_and_publisher_commitments_follow_execution_after_window(self):
        for publisher in (False, True):
            with self.subTest(publisher=publisher):
                repo, before = self.queued_terminal(publisher)
                with patch.object(dispatch, 'capacity', return_value=(3, {})):
                    self.tick()
                node = self.node()
                self.assertTrue(node['waiting'])
                self.assertEqual(self.posts, [])
                self.runs[repo, 800]['status'] = 'completed'
                self.tick()
                node = self.node()
                self.assertFalse(node['waiting'])
                for key in ('status', 'category', 'reason', 'cause', 'artifact', 'builds', 'publications'):
                    self.assertEqual(node[key], before[key])
                self.assertFalse(any(json.loads(p['inputs']['request'])['project'] == 'snode.c' for _, p in self.posts))
                self.posts.clear()
        return None

    def test_terminal_unknown_execution_retains_commitment_and_backoff(self):
        for publisher in (False, True):
            for status in (0, 401, 403, 404, 429, 503, 'malformed'):
                with self.subTest(publisher=publisher, status=status):
                    repo, before = self.queued_terminal(publisher)
                    original = self.api

                    def api(path, *args, **kwargs):
                        if path == f'repos/{repo}/actions/runs/800' and status != 'malformed':
                            raise dispatch.ApiError(status, 'Execution cannot be observed')
                        result = {} if path == f'repos/{repo}/actions/runs/800' else original(path, *args, **kwargs)
                        return result

                    with patch.object(dispatch, 'api', side_effect=api) as calls, \
                            patch.object(dispatch, 'capacity', return_value=(3, {})):
                        self.tick()
                        count = sum(c.args[0] == f'repos/{repo}/actions/runs/800' for c in calls.call_args_list)
                        self.tick()
                        self.assertEqual(sum(c.args[0] == f'repos/{repo}/actions/runs/800'
                                             for c in calls.call_args_list), count)
                    node = self.node()
                    self.assertTrue(node['waiting'])
                    for key in ('status', 'category', 'reason', 'cause', 'artifact', 'builds', 'publications'):
                        self.assertEqual(node[key], before[key])
                    self.assertIn('observation', node)
                    self.assertIn('reason', node['observation'])
                    self.assertGreater(node['observation']['retry_at'], time.time())
                    self.assertEqual(self.posts, [])
        return None

    def test_observed_allocation_replaces_commitment_without_double_counting(self):
        for publisher in (False, True):
            with self.subTest(publisher=publisher):
                repo, before = self.queued_terminal(publisher)
                self.runs[repo, 800]['status'] = 'in_progress'
                self.jobs[repo, 800][0].update(status='in_progress', runner_id=7)
                job = self.jobs[repo, 800][0]
                occupied = {(repo.split('/')[-1], 1800): dict(run=800, name=job['name'], title='old')}
                with patch.object(dispatch, 'capacity', return_value=(4, occupied)):
                    self.tick()
                    self.assertEqual(len(self.posts), 2)
                    self.tick()
                    self.assertEqual(len(self.posts), 2)
                self.assertFalse(self.node()['waiting'])
                self.assertEqual(self.node()['status'], before['status'])
                self.posts.clear()
        return None

    def test_unbound_commitment_retires_only_on_successful_post_window_absence(self):
        for publisher in (False, True):
            for terminal in (False, True):
                with self.subTest(publisher=publisher, terminal=terminal):
                    repo, before = self.queued_terminal(publisher)
                    self.runs.pop((repo, 800))
                    node = self.state['runs']['100']['nodes'][self.row['id'] + '/snode.c']
                    node.pop('publisher' if publisher else 'source')
                    node.pop('artifact')
                    node.update(status='superseded' if terminal else 'pending')
                    self.save()
                    with patch.object(dispatch, 'capacity', return_value=(3, {})):
                        self.tick()
                    result = self.node()
                    self.assertFalse(result['waiting'])
                    self.assertEqual(result['status'], 'superseded' if terminal else 'failed')
                    if terminal:
                        self.assertEqual(result['reason'], before['reason'])
                    else:
                        self.assertIn('Dispatch visibility unresolved', result['reason'])
                    self.posts.clear()
        return None

    def test_operator_retry_explicitly_releases_unobservable_terminal_commitment(self):
        _, _ = self.queued_terminal()
        node = self.state['runs']['100']['nodes'][self.row['id'] + '/snode.c']
        node.pop('artifact')
        node['observation'] = dict(category='configuration', reason='Scope lost', retry_at=time.time() + 1800)
        self.save()
        dispatch.transaction(self.root, dict(retry='100/snode.c/' + self.row['id']))
        result = self.node()
        self.assertFalse(result['waiting'])
        self.assertNotIn('request', result)
        self.assertNotIn('source', result)
        self.assertEqual((result['builds'], result['publications']), (0, 0))
        self.assertEqual(result['status'], 'pending')
        return None

    def test_unbound_listing_failure_keeps_commitment_and_matching_late_run_binds(self):
        for publisher in (False, True):
            with self.subTest(publisher=publisher):
                repo, before = self.queued_terminal(publisher)
                node = self.state['runs']['100']['nodes'][self.row['id'] + '/snode.c']
                node.pop('publisher' if publisher else 'source')
                node.pop('artifact')
                self.save()
                workflow = 'sign-and-publish-packages.yml' if publisher else 'build-distribution-packages.yml'
                self.runs[repo, 800].update(id=800, path='.github/workflows/' + workflow,
                    actor={'login': 'ci[bot]'}, created_at='2026-10-20T01:00:00Z',
                    display_title='Publish · old-publication' if publisher else 'Packages · old-intent')
                original = self.api

                def api(path, *args, **kwargs):
                    if path.startswith(f'repos/{repo}/actions/workflows/{workflow}/runs?'):
                        raise dispatch.ApiError(403, 'Cannot list execution intents')
                    return original(path, *args, **kwargs)

                with patch.object(dispatch, 'api', side_effect=api), patch.object(dispatch, 'capacity', return_value=(3, {})):
                    self.tick()
                result = self.node()
                self.assertTrue(result['waiting'])
                self.assertIn('observation', result)
                self.assertEqual(result['observation']['category'], 'configuration')
                self.assertEqual(self.posts, [])
                with patch.object(dispatch.time, 'time', return_value=result['observation']['retry_at'] + 1), \
                        patch.object(dispatch, 'capacity', return_value=(3, {})):
                    self.tick()
                result = self.node()
                self.assertEqual(result['publisher'] if publisher else result['source']['run'], 800)
                self.assertTrue(result['waiting'])
                self.assertEqual(result['status'], before['status'])
                self.assertEqual((result['builds'], result['publications']), (1, 2))
                self.assertEqual(self.posts, [])
        return None

    def test_ambiguous_dispatch_inside_window_already_retains_its_commitment(self):
        repo, _ = self.queued_terminal()
        self.runs.pop((repo, 800))
        node = self.state['runs']['100']['nodes'][self.row['id'] + '/snode.c']
        node.pop('source')
        node['request']['created'] = datetime.now(timezone.utc).isoformat()
        self.save()
        with patch.object(dispatch, 'capacity', return_value=(3, {})):
            self.tick()
        self.assertTrue(self.node()['waiting'])
        self.assertEqual(self.posts, [])
        return None

    def test_offline_guard_rejects_gh_download_and_remote_git_forms(self):
        import offline
        for command in (['gh', 'run', 'download', '123', '--repo', 'SNodeC/snode.c'],
                        ['gh', 'api', 'orgs/SNodeC'], ['git', 'ls-remote', 'git@github.com:SNodeC/snode.c.git'],
                        ['git', 'fetch', 'https://example.invalid/source.git']):
            with self.subTest(command=command), patch.object(offline, '_original', return_value=subprocess.CompletedProcess(command, 0)), \
                    self.assertRaisesRegex(AssertionError, 'transport forbidden'):
                offline.offline(command)
        return None

    def test_source_reuse_and_native_install_use_only_pinned_prerequisite_bytes(self):
        info = dict(sources=copy.deepcopy(self.sources), versions={}, packages=['snodec', 'snodec-idp', 'mqttsuite'],
                    files={'snodec_1_amd64.deb': repository.hashlib.sha256(b'root').hexdigest(),
                           'snodec-idp_1_amd64.deb': repository.hashlib.sha256(b'idp').hexdigest()})
        owners = {p: dict(_commit=c['_commit'], package=c['package']) for p, c in self.graph.items()}
        admission = repository.dependency_identity(info, 'snode.c')
        graph = {p: c for p, c in self.graph.items() if p != 'snode.c-idp'}
        profiles = publication.read(self.bundle / 'profiles.json')
        profile = profiles[self.row['id']]
        profile.update(projects=graph, sources={p: self.sources[p] for p in graph})
        profile['context'] = dict(build_project='mqttsuite', versions=dict.fromkeys(graph, '1.0.0'),
                                  source_tags=dict.fromkeys(graph, 'v1.0.0'))
        profile['archives'] = {'mqttsuite': 'application.tar.gz'}
        publication.write(self.bundle / 'profiles.json', profiles)
        (self.bundle / 'archives').mkdir()
        (self.bundle / 'archives/application.tar.gz').write_bytes(b'captured application')
        request = dict(definitions=owners | {'snode.c': self.graph['snode.c']})
        downloaded = []

        def fetch(url, destination=None):
            result = json.dumps({'targets': {'amd64': info}}).encode()
            if destination is not None:
                downloaded.append(destination.name)
                destination.write_bytes(b'root' if destination.name.startswith('snodec_') else b'idp')
                result = None
            return result

        with patch.dict(os.environ, GITHUB_REPOSITORY='SNodeC/mqttsuite', BUILD_PROJECT='mqttsuite',
                        PUBLISHED_REF='f' * 40, PACKAGE_REQUEST=json.dumps(request)), \
                patch.object(repository, 'fetch', side_effect=fetch), \
                patch.object(dispatch, 'api', side_effect=AssertionError('Source must not read sibling JSON')) as api, \
                patch.object(dispatch, 'write', side_effect=lambda path, value: publication.write(self.base / path, value)):
            dispatch.baseline(self.bundle, self.row['id'], 'f' * 40)
            repository.select(self.bundle, self.row['id'], 'mqttsuite', info)
            self.assertEqual(repository.dependency_identity(info, 'snode.c'), admission)
            destination = self.base / 'dependencies'
            repository.reuse(self.bundle, self.row['id'], destination)
            self.assertEqual(downloaded, ['snodec_1_amd64.deb'])
            self.assertEqual({p.name for p in destination.iterdir()}, {'snodec_1_amd64.deb', 'snodec.packages'})
            self.assertEqual((destination / 'snodec.packages').read_text(), 'snodec\n')
            native = (repository.ROOT / 'ci/build/native.sh').read_text()
            snippet = native[native.index('# reuse()'):native.index('install_packages() {')]
            snippet = snippet.replace('/work/dependencies', str(destination))
            installed = subprocess.check_output(['bash', '-c', snippet + '\nprintf "%s\\n" "${prerequisite_packages[@]}"'], text=True)
            self.assertEqual(installed.splitlines(), [str(destination / 'snodec_1_amd64.deb')])
            with patch.object(repository, 'digest', return_value='wrong'), self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                repository.reuse(self.bundle, self.row['id'], destination)
            downloaded.clear()
            request['definitions']['snode.c-idp']['_commit'] = 'e' * 40
            with patch.dict(os.environ, PACKAGE_REQUEST=json.dumps(request)), \
                    self.assertRaisesRegex(ValueError, 'snode.c-idp@' + 'c' * 40):
                repository.reuse(self.bundle, self.row['id'], destination)
            self.assertEqual(downloaded, [])
            api.assert_not_called()
        return None

    def application_fixture(self, node):
        self.feed(list(self.graph), capture='older', revision='1')
        info, directory = publication.published(self.root, self.row)
        info['files'] = {'snodec_1_amd64.deb': '1' * 64,
                         'snodec-idp_1_amd64.deb': '2' * 64}
        from support import feed_manifest
        info = feed_manifest(info, self.graph)
        publication.write(self.root / directory / 'build.json', {'targets': {'amd64': info}})
        generation = self.state['runs']['100']
        generation['context']['release_project'] = 'mqttsuite'
        generation['context']['projects'] = {p: c for p, c in self.graph.items() if p != 'snode.c-idp'}
        generation['revisions'] = {'mqttsuite': '2'}
        profile = publication.read(self.bundle / 'profiles.json')
        profile[self.row['id']]['sources'].pop('snode.c-idp', None)
        generation['sources'][self.row['id']] = copy.deepcopy(profile[self.row['id']]['sources'])
        publication.write(self.bundle / 'profiles.json', profile)
        generation['profiles_hash'] = repository.digest(self.bundle / 'profiles.json')
        generation['nodes'] = {self.row['id'] + '/mqttsuite': node} if node else {}
        if node:
            node.update(requires=['snode.c'], dependencies=repository.binding(info, ['snode.c']),
                        waiting=False, request=dict(intent='completed-attempt', actor='ci[bot]', created='2026-10-20T00:00:00Z'),
                        source=dict(run=800, attempt=1))
        self.save()
        return info

    def test_application_failure_with_retained_idp_keeps_its_budget(self):
        self.application_fixture(dict(status='failed', category='deterministic', reason='Build failed', builds=1, publications=0))
        with patch.object(repository, 'definition', side_effect=lambda p, c: self.graph[p] | dict(_commit=c)):
            for _ in range(3):
                self.tick()
        node = self.node('mqttsuite')
        self.assertEqual(node['status'], 'failed')
        self.assertEqual(node['category'], 'deterministic')
        self.assertEqual(node['reason'], 'Build failed')
        self.assertEqual((node['builds'], node['publications']), (1, 0))
        self.assertEqual(self.posts, [])
        return None

    def test_publication_failure_and_blocked_work_stay_closed_without_new_capture_downloads(self):
        for status, category in [('failed', 'deterministic'), ('unsatisfiable', 'blocked')]:
            with self.subTest(status=status):
                self.posts.clear()
                self.application_fixture(dict(status=status, category=category, reason='Original reason', builds=2, publications=1))
                for _ in range(3):
                    self.tick()
                with patch.object(dispatch, 'listing', wraps=dispatch.listing) as listing:
                    dispatch.tick(self.root, {})
                self.assertEqual(self.node('mqttsuite')['status'], status)
                self.assertEqual(self.node('mqttsuite')['reason'], 'Original reason')
                self.assertEqual((self.node('mqttsuite')['builds'], self.node('mqttsuite')['publications']), (2, 1))
                self.assertFalse(any('/runs/100/artifacts' in c.args[0] for c in listing.call_args_list))
                self.assertEqual(self.posts, [])
        return None

    def test_changed_dependency_digest_readmits_superseded_source_once_without_revision_change(self):
        info = self.application_fixture(dict(status='superseded', reason='Superseded build: published dependency changed', builds=2, publications=1))
        info['releases']['snode.c']['v1.0.0']['files']['snodec_1_amd64.deb'] = '3' * 64
        publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
        self.save()
        self.tick()
        self.assertEqual(self.node('mqttsuite')['builds'], 1)
        self.assertEqual(self.node('mqttsuite')['publications'], 0)
        self.assertEqual(self.node('mqttsuite')['cause'], 'dependent')
        self.assertEqual(self.node('mqttsuite')['dependencies'], repository.binding(info, ['snode.c']))
        self.tick()
        self.tick()
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.node('mqttsuite')['builds'], 1)
        return None

    def test_changed_prerequisite_closes_application_only_capture_when_overlap_is_off(self):
        info = self.application_fixture(dict(status='failed', category='deterministic', reason='Old failure', builds=2, publications=1))
        info['releases']['snode.c']['v1.0.0']['revision'] = '2'
        publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
        self.save()
        with patch.dict(repository.CONFIG['settings'], rebuild_overlap=False):
            self.tick()
            self.tick()
        self.assertEqual(self.node('mqttsuite')['status'], 'failed')
        self.assertEqual(self.node('mqttsuite')['reason'], 'Old failure')
        self.assertEqual((self.node('mqttsuite')['builds'], self.node('mqttsuite')['publications']), (2, 1))
        self.assertEqual(self.posts, [])
        return None

    def test_historical_build_schema_is_not_required_for_ownership(self):
        self.application_fixture(None)
        historical = dict(package='snodec-idp', matrix=None, build={'native': '../invalid'}, depends_on=['unregistered'])
        self.contents['SNodeC/snode.c-idp', 'c' * 40, 'ci/packages.json'] = json.dumps(historical).encode()
        profiles = publication.read(self.bundle / 'profiles.json')
        profiles[self.row['id']]['projects'].pop('snode.c-idp')
        publication.write(self.bundle / 'profiles.json', profiles)
        self.state['runs']['100']['profiles_hash'] = repository.digest(self.bundle / 'profiles.json')
        self.save()
        repository.definition_data.cache_clear()
        self.tick()
        self.assertEqual(self.node('mqttsuite')['builds'], 1)
        definitions = json.loads(self.posts[0][1]['inputs']['request'])['definitions']
        self.assertIn('snode.c-idp', definitions)
        self.assertEqual(definitions['snode.c-idp'], dict(package='snodec-idp', _commit='c' * 40))
        return None

    def test_historical_metadata_outside_ownership_contract_is_not_validated(self):
        self.application_fixture(None)
        historical = dict(package='snodec-idp', _historical='irrelevant metadata', _commit='e' * 40, matrix=None)
        self.contents['SNodeC/snode.c-idp', 'c' * 40, 'ci/packages.json'] = json.dumps(historical).encode()
        profiles = publication.read(self.bundle / 'profiles.json')
        profiles[self.row['id']]['projects'].pop('snode.c-idp')
        publication.write(self.bundle / 'profiles.json', profiles)
        self.state['runs']['100']['profiles_hash'] = repository.digest(self.bundle / 'profiles.json')
        self.save()
        repository.definition_data.cache_clear()
        with patch.object(repository, 'content', wraps=repository.content) as content:
            self.tick()
            with self.assertRaisesRegex(ValueError, 'without capture metadata'):
                repository.definition('snode.c-idp', 'c' * 40)
        self.assertEqual(sum(call.args[0] == 'snode.c-idp' for call in content.call_args_list), 1)
        self.assertEqual(self.node('mqttsuite').get('builds', 0), 1, self.node('mqttsuite'))
        definitions = json.loads(self.posts[0][1]['inputs']['request'])['definitions']
        self.assertIn('snode.c-idp', definitions)
        self.assertEqual(definitions['snode.c-idp'], dict(package='snodec-idp', _commit='c' * 40))
        return None

    def test_source_rejects_mismatched_sibling_fact_before_any_download(self):
        info = dict(sources=self.sources, files={'snodec_1_amd64.deb': repository.hashlib.sha256(b'root').hexdigest()})
        publication.write(self.bundle / 'baseline.json', info)
        publication.write(self.bundle / 'context.json', dict(build_project='mqttsuite'))
        definitions = {p: dict(_commit=c['_commit'], package=c['package']) for p, c in self.graph.items()}
        definitions['snode.c-idp']['_commit'] = 'e' * 40
        with patch.dict(os.environ, GITHUB_REPOSITORY='SNodeC/mqttsuite', PACKAGE_REQUEST=json.dumps(dict(definitions=definitions)), PUBLISHED_REF='f' * 40), \
                patch.object(repository, 'fetch', side_effect=lambda url, path: path.write_bytes(b'root')) as fetch, \
                self.assertRaisesRegex(ValueError, 'snode.c-idp@' + 'c' * 40):
            repository.reuse(self.bundle, self.row['id'], self.base / 'dependencies')
        fetch.assert_not_called()
        return None

    def test_terminal_known_queued_run_still_consumes_one_commitment(self):
        self.feed(['snode.c'], capture='older', revision='2')
        created = datetime.now(timezone.utc).isoformat()
        node = dict(status='superseded', category='excluded', reason='New request owns the row',
                    builds=1, publications=0, waiting=True,
                    request=dict(intent='old-intent', created=created, actor='ci[bot]'),
                    source=dict(run=800, attempt=1))
        self.state['runs']['100']['nodes'] = {self.row['id'] + '/snode.c': node}
        current = copy.deepcopy(self.state['runs']['100'])
        current.update(run_id='600', context=self.context | dict(run_id='600'), nodes={}, revisions={'snode.c': '3'})
        self.state['runs']['600'] = current
        self.save()
        self.feed(['snode.c'], capture='600', revision='3')
        self.runs['SNodeC/snode.c', 800] = dict(status='queued', run_attempt=1)
        self.jobs['SNodeC/snode.c', 800] = [dict(
            id=1800, name='build / ' + self.row['id'], run_attempt=1,
            status='queued', runner_id=0, html_url='source-job')]
        with patch.object(dispatch, 'capacity', return_value=(3, {})):
            self.tick()
        observed = self.node('snode.c')
        self.assertTrue(observed['waiting'])
        self.assertEqual(observed['status'], 'superseded')
        self.assertEqual((observed['builds'], observed['publications']), (1, 0))
        self.assertEqual(self.posts, [], '3 free - 1 queued commitment - 2 headroom leaves no build admission')
        return None
