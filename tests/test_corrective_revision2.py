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
        self.state['requests'] = {'mqttsuite': dict(capture='200', sha='f' * 40, tag='v2.0.0', revision='3', eligible=True)}
        self.save()
        self.runs[dispatch.COORDINATOR, 200] = {}
        self.tick()
        request = publication.read(self.root / 'status.json')['requests']['mqttsuite']
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
        info = dict(sources=self.sources, versions={'snodec': '1.0.0-2~trixie'})
        with patch.object(repository, 'definition', side_effect=AssertionError('Presentation must not fetch source JSON')):
            self.assertEqual(repository.project_revision(info, 'snode.c'), 2)
        return None

    def test_chain_and_diamond_replacements_compare_each_prerequisites_own_counter(self):
        names = ('framework', 'first', 'second', 'join', 'tail')
        edges = dict(framework=[], first=['framework'], second=['framework'], join=['first', 'second'], tail=['join'])
        graph = {p: copy.deepcopy(self.graph['snode.c']) | dict(
            package=p, title=p, depends_on=edges[p], _commit=chr(97 + i) * 40) for i, p in enumerate(names)}
        for project, config in graph.items():
            for commit in (config['_commit'], 'f' * 40):
                self.contents['SNodeC/' + project, commit, 'ci/packages.json'] = json.dumps(
                    {k: v for k, v in config.items() if not k.startswith('_')}).encode()
        sources = {p: {'refs/tags/v1.0.0': graph[p]['_commit']} for p in names}
        context = self.context | dict(projects=graph, release_project='framework')
        profile = dict(projects=graph, sources=sources, baseline={}, directory='debian/dists/trixie')
        for name, value in dict(context=context, sources={self.row['id']: sources}, targets=[self.row],
                                revisions=dict.fromkeys(names, '2'), profiles={self.row['id']: profile}).items():
            publication.write(self.bundle / (name + '.json'), value)
        self.state['runs'] = {}
        publication.record_run(self.bundle, self.state, context)
        for capture, first_revision, tail_revision in [('200', '3', '999'), ('300', '4', '2')]:
            self.state['runs'][capture] = dict(
                context=context | dict(release_project='first'), revisions={'first': first_revision, 'tail': tail_revision},
                sources={self.row['id']: {'first': {'refs/tags/v1.0.0': 'f' * 40}}}, targets=[self.row],
                nodes={self.row['id'] + '/' + p: dict(status='superseded', category='excluded') for p in ('first', 'tail')})
        info = dict(sources={p: sources[p] for p in ('framework', 'first', 'second')},
                    versions={p: '1.0.0-' + ('4' if p == 'first' else '2') + '~trixie'
                              for p in ('framework', 'first', 'second')})
        info['sources']['first'] = {'refs/tags/v1.0.0': 'f' * 40}
        info['publications'] = {p: dict(capture='300' if p == 'first' else '100',
                                       revision='4' if p == 'first' else '2', job_url='source-' + p, published_at='now')
                                for p in ('framework', 'first', 'second')}
        publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
        self.save()
        expected = []
        original = dispatch.ready

        def ready(profile, revisions, project, info, projects=None):
            if project == 'join':
                expected.append(copy.deepcopy(revisions))
            return original(profile, revisions, project, info, projects)

        with patch.object(repository, 'REPOSITORIES', names), patch.object(dispatch, 'REPOSITORIES', names), \
                patch.object(publication, 'REPOSITORIES', names), patch.dict(repository.PROJECTS, graph, clear=True), \
                patch.object(repository, 'definition', side_effect=lambda p, c: graph[p] | dict(_commit=c)), \
                patch.dict(repository.CONFIG['settings'], rebuild_overlap=False), patch.object(dispatch, 'ready', side_effect=ready):
            self.tick()
            self.assertTrue(expected, self.node('join'))
            self.assertEqual(expected[0]['first'], '4')
            self.assertEqual(expected[0]['second'], '2')
            requests = [json.loads(p['inputs']['request']) for _, p in self.posts]
            self.assertEqual([r['project'] for r in requests], ['join'])
            self.assertEqual(self.node('join')['builds'], 1)
            self.assertNotEqual(self.node('join')['status'], 'superseded')
            self.assertNotIn('request', self.node('tail'))
            self.tick()
            self.assertEqual(len(self.posts), 1)
        return None

    @contextmanager
    def selection_fixture(self):
        self.feed(list(self.graph), capture='older', revision='1')
        info, _ = publication.published(self.root, self.row)
        graph = copy.deepcopy(self.graph)
        graph['snode.c'].update(matrix={'linux': [dict(distribution='debian', suite='trixie', image='debian:trixie',
                                                     architectures=['amd64', 'arm64'])]}, build={'native': 'ci/package/native.sh'})
        request = dict(sha='f' * 40, tag='v2.0.0', revision='3', capture='200', eligible=True)
        self.state.update(requests={'mqttsuite': request}, counters=dict.fromkeys(graph, 3), allocations={})
        self.save()
        controls = dict(error=None, omit=False, directory=Path(tempfile.mkdtemp(dir=self.base)))

        def definition(project, commit):
            config = copy.deepcopy(graph[project])
            if project == 'mqttsuite' and commit in ('e' * 40, 'f' * 40):
                if controls['error'] is not None:
                    raise controls['error']
                if controls['omit']:
                    config.update(matrix={'linux': [dict(distribution='debian', suite='trixie', image='debian:trixie',
                                                         architectures=['arm64'])]}, build={'native': 'ci/package/native.sh'})
            return config | dict(_commit=commit, _digest='d' * 64)

        def archive(project, config, tag, directory):
            name = project + '-' + config['_commit'] + '.tar.gz'
            (directory / name).write_bytes(project.encode())
            return tag[1:], {'refs/tags/' + tag: config['_commit']}, name

        with patch.object(repository, 'definition', side_effect=definition), \
                patch.object(repository, 'archive_source', side_effect=archive), \
                patch.object(repository, 'DEFINITIONS', self.base / 'selection-runtime.json'), \
                patch.object(publication, 'published', return_value=(info, 'debian/dists/trixie')), \
                patch.dict(repository.PROJECTS, graph, clear=True), \
                patch.dict(repository.ROW_PROJECTS, {}, clear=True), \
                patch.dict(os.environ, RELEASE_PROJECT='snode.c', RELEASE_TAG='v1.0.0', RELEASE_REQUESTED_AT='', GITHUB_RUN_ID='201'):
            controls['claimed'] = {k: v for k, v in graph['snode.c'].items() if not k.startswith('_')}
            yield controls, request
        return None

    def test_verified_omission_and_ineligibility_share_selection_before_and_after_reservation(self):
        with self.selection_fixture() as (controls, request):
            controls['omit'] = True
            repository.configure(self.root, 'snode.c', 'a' * 40, controls['claimed'])
            self.assertEqual(repository.ROW_PROJECTS[self.row['id']]['mqttsuite']['_commit'], 'b' * 40)
            self.assertEqual(repository.ROW_PROJECTS['debian-trixie-arm64']['mqttsuite']['_commit'], 'f' * 40)
            publication.reserve(self.root, 'snode.c', '201')
            output = controls['directory'] / 'captured-201'
            repository.prepare(self.root, output)
            profiles = publication.read(output / 'profiles.json')
            self.assertEqual(profiles[self.row['id']]['projects']['mqttsuite']['_commit'], 'b' * 40)
            self.assertEqual(profiles[self.row['id']]['sources']['mqttsuite'], {'refs/tags/v1.0.0': 'b' * 40})
            self.assertEqual(profiles['debian-trixie-arm64']['projects']['mqttsuite']['_commit'], 'f' * 40)
            state = publication.read(self.root / 'status.json')
            state['requests']['mqttsuite']['eligible'] = False
            publication.write(self.root / 'status.json', state)
            repository.configure(self.root, 'snode.c', 'a' * 40, controls['claimed'])
            self.assertTrue(all(g['mqttsuite']['_commit'] == 'b' * 40 for g in repository.ROW_PROJECTS.values()))
        return None

    def test_transient_selection_before_and_after_reservation_recovers_exact_request(self):
        for after_reservation in (False, True):
            for error in (dispatch.ApiError(503, 'unavailable'), dispatch.ApiError(429, 'rate limit'), subprocess.TimeoutExpired('gh', 120)):
                with self.subTest(after_reservation=after_reservation, error=str(error)), self.selection_fixture() as (controls, request):
                    controls['error'] = None if after_reservation else error
                    repository.configure(self.root, 'snode.c', 'a' * 40, controls['claimed'])
                    if not after_reservation:
                        self.assertTrue(all('mqttsuite' not in g for g in repository.ROW_PROJECTS.values()))
                    publication.reserve(self.root, 'snode.c', '201')
                    controls['error'] = error
                    output = controls['directory'] / ('deferred-' + str(after_reservation) + '-' + type(error).__name__)
                    repository.prepare(self.root, output)
                    profiles = publication.read(output / 'profiles.json')
                    for profile in profiles.values():
                        self.assertNotIn('mqttsuite', profile['sources'])
                        self.assertNotIn('mqttsuite', profile['projects'])
                        self.assertIn('temporarily', profile['errors']['mqttsuite'])
                        self.assertIn('snode.c-idp', profile['sources'])
                    self.assertEqual(publication.read(self.root / 'status.json')['requests']['mqttsuite'], request)
                    controls['error'] = None
                    repository.configure(self.root, 'snode.c', 'a' * 40, controls['claimed'])
                    publication.reserve(self.root, 'snode.c', '202')
                    recovered = controls['directory'] / ('recovered-' + str(after_reservation) + '-' + type(error).__name__)
                    with patch.dict(os.environ, GITHUB_RUN_ID='202'):
                        repository.prepare(self.root, recovered)
                    for profile in publication.read(recovered / 'profiles.json').values():
                        self.assertEqual(profile['projects']['mqttsuite']['_commit'], request['sha'])
                        self.assertEqual(profile['sources']['mqttsuite'], {'refs/tags/v2.0.0': request['sha']})
                    self.assertEqual(publication.read(self.root / 'status.json')['requests']['mqttsuite'], request)
        return None

    def test_deterministic_selection_excludes_without_changing_request_eligibility(self):
        for error in (dispatch.ApiError(404, 'exact commit missing'), dispatch.ApiError(403, 'scope lost'), ValueError('invalid JSON')):
            with self.subTest(error=str(error)), self.selection_fixture() as (controls, request):
                controls['error'] = error
                repository.configure(self.root, 'snode.c', 'a' * 40, controls['claimed'])
                for selected in repository.ROW_PROJECTS.values():
                    self.assertNotIn('mqttsuite', selected)
                    self.assertIn('snode.c-idp', selected)
                self.assertEqual(publication.read(self.root / 'status.json')['requests']['mqttsuite'], request)
                errors = publication.read(self.base / 'selection-runtime.json')['errors']
                self.assertTrue(all('excluded' in row['mqttsuite'] for row in errors.values()))
        return None

    def test_prepare_reselects_a_cas_fresh_explicit_request_or_defers_it(self):
        for omitted, transient in ((False, False), (True, False), (False, True)):
            with self.subTest(omitted=omitted, transient=transient), self.selection_fixture() as (controls, request):
                repository.configure(self.root, 'snode.c', 'a' * 40, controls['claimed'])
                publication.reserve(self.root, 'snode.c', '201')
                with patch.dict(os.environ, RELEASE_PROJECT='mqttsuite', RELEASE_TAG='v3.0.0', RELEASE_SHA='e' * 40,
                                RELEASE_RUN='999', RELEASE_REQUESTED_AT='2026-10-21T10:00:00Z'):
                    publication.reserve(self.root, 'mqttsuite', '301')
                controls.update(omit=omitted, error=dispatch.ApiError(503, 'newest source unavailable') if transient else None)
                output = controls['directory'] / ('interleaved-' + str(omitted) + '-' + str(transient))
                repository.prepare(self.root, output)
                profiles = publication.read(output / 'profiles.json')
                for target, profile in profiles.items():
                    if transient:
                        self.assertNotIn('mqttsuite', profile['sources'])
                        self.assertIn('temporarily', profile['errors']['mqttsuite'])
                    else:
                        expected = 'b' * 40 if omitted and target == self.row['id'] else 'e' * 40
                        self.assertEqual(profile['projects']['mqttsuite']['_commit'], expected)
                        self.assertEqual(repository.source_commit(profile['sources']['mqttsuite']), expected)
                self.assertEqual(publication.read(self.root / 'status.json')['requests']['mqttsuite']['sha'], 'e' * 40)
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
        self.save()
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
            node.update(requires=['snode.c'], dependencies=repository.binding(info, ['snode.c'], self.graph))
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

    def test_changed_dependency_digest_reopens_once_without_source_or_revision_change(self):
        info = self.application_fixture(dict(status='failed', category='deterministic', reason='Old failure', builds=2, publications=1))
        info['files']['snodec_1_amd64.deb'] = '3' * 64
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
        info['versions']['snodec'] = '1.0.0-2~trixie'
        publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
        self.save()
        with patch.dict(repository.CONFIG['settings'], rebuild_overlap=False):
            self.tick()
            self.tick()
        self.assertEqual(self.node('mqttsuite')['status'], 'superseded')
        self.assertIn('re-request required', self.node('mqttsuite')['reason'])
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
        self.save()
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

    def test_transient_explicit_definition_read_never_selects_old_source(self):
        self.feed(['snode.c', 'mqttsuite'], capture='older', revision='1')
        request = dict(sha='f' * 40, tag='v2.0.0', revision='3', capture='200', eligible=True)
        self.state['requests'] = {'mqttsuite': request}
        self.save()
        graph = copy.deepcopy(self.graph)
        claimed = {k: v for k, v in graph['snode.c'].items() if not k.startswith('_')}

        def definition(project, commit):
            if project == 'mqttsuite' and commit == request['sha']:
                raise dispatch.ApiError(503, 'Selected explicit definition temporarily unavailable')
            return graph[project] | dict(_commit=commit)

        def api(path, *args, **kwargs):
            return dict(object={'sha': 'c' * 40}) if '/git/' in path else dict(default_branch='main')

        with patch.object(repository, 'definition', side_effect=definition), \
                patch.object(dispatch, 'api', side_effect=api), \
                patch.object(repository, 'DEFINITIONS', self.base / 'selection.json'), \
                patch.dict(repository.ROW_PROJECTS, {}, clear=True), \
                patch.dict(repository.PROJECTS, graph, clear=True):
            repository.configure(self.root, 'snode.c', 'a' * 40, claimed)
            selection = publication.read(self.base / 'selection.json')
            self.assertNotIn('mqttsuite', selection['targets'][self.row['id']])
            self.assertIn('temporarily', selection['errors'][self.row['id']]['mqttsuite'])
            self.assertIn('snode.c-idp', selection['targets'][self.row['id']])
        self.assertEqual(publication.read(self.root / 'status.json')['requests']['mqttsuite'], request)
        self.assertEqual(self.posts, [])
        return None
