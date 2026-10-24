"""Held-capture lifetime, optimistic control writes, and published README boundaries."""
import copy
import hashlib
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from ci import dispatch, repository
from ci.publish import publication, apt, cleanup, linux
from support import CoordinatorCase
import test_cascade_capture as capture_cases
import test_corrective_revision2 as ownership_cases


class HeldCaptureTest(CoordinatorCase):
    def backoff(self):
        self.feed(['snode.c'])
        self.tick()
        capture_cases.CascadeCaptureTest.failed_capture(self, dispatch.ApiError(503, 'temporary capture read'))
        self.assertNotIn('request', self.node('mqttsuite'))
        return copy.deepcopy(self.node('mqttsuite'))

    def replace_root(self, capture='110', tag='v1.0.0'):
        self.add_capture('snode.c', capture, revision='3')
        self.feed(['snode.c'], capture=capture, revision='3')
        if tag != 'v1.0.0':
            info = publication.published(self.root, self.row)[0]
            own = info['releases']['snode.c'].pop('v1.0.0')
            own['sources']['snode.c'] = {'refs/tags/' + tag: 'a' * 40}
            own['context']['source_tags']['snode.c'] = tag
            info['releases']['snode.c'][tag] = own
            info['sources']['snode.c'] = own['sources']['snode.c']
            publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
            self.save()
        return None

    def test_overlap_off_reason_distinguishes_pinned_work_from_new_events(self):
        info = ownership_cases.CorrectiveRevision2Test.application_fixture(self, dict(
            status='superseded', reason='Superseded build: published dependency changed', builds=2, publications=1))
        info['releases']['snode.c']['v1.0.0']['revision'] = '2'
        publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
        self.save()
        with patch.dict(repository.CONFIG['settings'], rebuild_overlap=False):
            self.tick()
        node = self.node('mqttsuite')
        self.assertEqual(node['status'], 'superseded')
        self.assertEqual(node['category'], 'excluded')
        self.assertEqual(node['reason'], 'Prerequisite replaced; pinned rebuild disabled by rebuild_overlap')
        self.assertEqual((node['builds'], node['publications']), (2, 1))
        self.assertEqual(self.posts, [])
        return None

    def test_direct_build_breaks_current_root_backoff_cycle(self):
        before = self.backoff()
        self.add_capture('mqttsuite', '200', revision='3')
        self.tick()
        requests = [json.loads(p['inputs']['request']) for _, p in self.posts]
        self.assertEqual([(r['capture'], r['kind']) for r in requests if r['project'] == 'mqttsuite'],
                         [('100', 'capture'), ('200', 'build')])
        self.assertEqual(self.node('mqttsuite')['builds'], before['builds'])
        self.assertEqual(self.node('mqttsuite', '200')['builds'], 1)
        return None

    def test_direct_completion_settles_backoff_and_admits_one_join(self):
        self.backoff()
        join = dict(copy.deepcopy(self.graph['mqttsuite']), title='Join', package='join',
                    depends_on=['snode.c', 'mqttsuite'], _commit='d' * 40)
        self.graph['join'] = join
        repository.PROJECTS.update(self.graph)
        master = self.base / 'master.json'
        publication.write(master, dict(repositories=list(self.graph)))
        self.state['requests']['join'] = {'v1.0.0': dict(definition=join, capture='100', revision='2')}
        self.save()
        self.add_capture('mqttsuite', '200', revision='3')
        with patch.dict(os.environ, CI_MASTER=str(master)), patch.object(repository, 'REPOSITORIES', tuple(self.graph)):
            self.tick()
            requests = [json.loads(p['inputs']['request']) for _, p in self.posts]
            self.assertEqual([r for r in requests if r['project'] == 'join'], [])
            self.assertEqual(self.node('mqttsuite', '200')['builds'], 1)
            self.feed(['snode.c', 'mqttsuite'])
            info = publication.published(self.root, self.row)[0]
            own = info['releases']['mqttsuite']['v1.0.0']
            own['revision'] = '3'
            own['publications']['mqttsuite'].update(capture='200', revision='3')
            info['publications']['mqttsuite'].update(capture='200', revision='3')
            self.state['runs']['200']['nodes'][self.row['id'] + '/mqttsuite'].update(
                status='published', waiting=False, requires=['snode.c'], dependencies=repository.binding(info, ['snode.c']))
            publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
            self.save()
            for _ in range(3):
                self.tick()
        self.assertEqual(self.node('mqttsuite')['status'], 'superseded')
        self.assertIn('satisfied', self.node('mqttsuite')['reason'])
        requests = [json.loads(p['inputs']['request']) for _, p in self.posts]
        self.assertEqual([(r['capture'], r['kind']) for r in requests if r['project'] == 'join'], [('100', 'capture')])
        self.assertEqual(self.node('join')['builds'], 1)
        return None

    def test_replaced_roots_retire_backoff_without_spending_old_budget(self):
        for tag in ('v1.0.0', 'v2.0.0'):
            with self.subTest(tag=tag):
                # Each variant is an independent row-local lifecycle in its own fixture.
                if tag == 'v2.0.0':
                    self.doCleanups()
                    self.setUp()
                before = self.backoff()
                self.replace_root(tag=tag)
                self.tick()
                old = self.node('mqttsuite')
                self.assertEqual(old['status'], 'superseded')
                self.assertIn('Root', old['reason'])
                self.assertEqual(old['builds'], before['builds'])
                self.assertEqual(old['observation'], before['observation'])
                self.assertNotIn('request', old)
                requests = [json.loads(p['inputs']['request']) for _, p in self.posts]
                self.assertEqual([(r['capture'], r['kind']) for r in requests if r['project'] == 'mqttsuite'],
                                 [('100', 'capture'), ('110', 'capture')])
                self.assertEqual(self.node('mqttsuite', '110')['builds'], 1)
                count = len(self.posts)
                self.tick()
                self.assertEqual(len(self.posts), count)
        return None

    def test_inert_root_operator_retry_is_retired_instead_of_orphaned(self):
        self.backoff()
        self.state = publication.read(self.root / 'status.json')
        self.state['runs']['100']['nodes'][self.row['id'] + '/mqttsuite'].update(status='failed')
        self.save()
        self.replace_root()
        dispatch.transaction(self.root, dict(retry='100/mqttsuite/' + self.row['id']))
        self.tick()
        old = self.node('mqttsuite')
        self.assertEqual(old['status'], 'superseded')
        self.assertNotIn('request', old)
        self.assertEqual(old['builds'], 0)
        self.assertEqual(self.node('mqttsuite', '110')['builds'], 1)
        return None

    def test_settled_current_root_retires_retried_holder(self):
        self.backoff()
        self.feed(['snode.c', 'mqttsuite'])
        self.state['runs']['100']['nodes'][self.row['id'] + '/mqttsuite'].update(status='failed')
        self.save()
        self.add_capture('mqttsuite', '200', revision='2')
        self.state['runs']['200']['nodes'] = {self.row['id'] + '/mqttsuite': dict(
            status='published', requires=['snode.c'], dependencies=repository.binding(
                publication.published(self.root, self.row)[0], ['snode.c']))}
        self.save()
        dispatch.transaction(self.root, dict(retry='100/mqttsuite/' + self.row['id']))
        before = len(self.posts)
        self.tick()
        self.assertEqual(self.node('mqttsuite')['status'], 'superseded')
        self.assertIn('satisfied', self.node('mqttsuite')['reason'])
        self.assertEqual(len(self.posts), before)
        return None

    def test_queued_capture_survives_replacement_until_observed_terminal(self):
        self.feed(['snode.c'])
        self.tick()
        before = copy.deepcopy(self.node('mqttsuite'))
        self.replace_root()
        self.tick()
        self.assertEqual(self.node('mqttsuite')['request'], before['request'])
        self.assertTrue(self.node('mqttsuite')['waiting'])
        self.assertNotIn('request', self.node('mqttsuite', '110'))
        capture_cases.CascadeCaptureTest.failed_capture(self, dispatch.ApiError(503, 'temporary'))
        self.assertEqual(self.node('mqttsuite')['status'], 'superseded')
        self.assertEqual(self.node('mqttsuite', '110')['builds'], 1)
        return None

    def test_retirement_is_row_local_and_independent_of_root_order(self):
        before = self.backoff()
        other = next(r for r in repository.rows(self.graph['snode.c']) if r['id'] == 'debian-trixie-arm64')
        generation = self.state['runs']['100']
        generation['targets'].append(other)
        generation['sources'][other['id']] = copy.deepcopy(generation['sources'][self.row['id']])
        generation['nodes'][other['id'] + '/mqttsuite'] = copy.deepcopy(before)
        profiles = publication.read(self.bundle / 'profiles.json')
        profiles[other['id']] = copy.deepcopy(profiles[self.row['id']])
        for name, value in [('targets', generation['targets']), ('sources', generation['sources']), ('profiles', profiles)]:
            publication.write(self.bundle / (name + '.json'), value)
        generation['profiles_hash'] = repository.digest(self.bundle / 'profiles.json')
        info = publication.read(self.root / 'debian/dists/trixie/build.json')
        info['targets']['arm64'] = copy.deepcopy(info['targets']['amd64'])
        publication.write(self.root / 'debian/dists/trixie/build.json', info)
        self.save()
        self.add_capture('snode.c', '110', revision='3')
        info['targets']['amd64']['publications']['snode.c'].update(capture='110', revision='3')
        own = info['targets']['amd64']['releases']['snode.c']['v1.0.0']
        own['revision'] = '3'
        own['publications']['snode.c'].update(capture='110', revision='3')
        publication.write(self.root / 'debian/dists/trixie/build.json', info)
        self.state['runs'] = dict(reversed(list(self.state['runs'].items())))
        self.save()
        self.tick()
        pushed = publication.read(self.root / 'status.json')
        self.assertEqual(pushed['runs']['100']['nodes'][self.row['id'] + '/mqttsuite']['status'], 'superseded')
        self.assertEqual(pushed['runs']['100']['nodes'][other['id'] + '/mqttsuite'], before)
        self.assertEqual(pushed['runs']['110']['nodes'][self.row['id'] + '/mqttsuite']['builds'], 1)
        return None

    def test_upstream_child_republication_retires_the_old_independent_root(self):
        self.backoff()
        self.graph['upstream'] = dict(copy.deepcopy(self.graph['snode.c']), package='upstream', title='Upstream', _commit='e' * 40)
        self.graph['snode.c']['depends_on'] = ['upstream']
        self.sources['upstream'] = {'refs/tags/v1.0.0': 'e' * 40}
        context = patch.object(repository, 'REPOSITORIES', tuple(self.graph))
        context.start()
        self.addCleanup(context.stop)
        repository.definition_data.cache_clear()
        repository.PROJECTS.update(self.graph)
        self.contents['SNodeC/upstream', 'e' * 40, 'ci/packages.json'] = json.dumps(self.graph['upstream']).encode()
        self.contents['SNodeC/snode.c', 'a' * 40, 'ci/packages.json'] = json.dumps(self.graph['snode.c']).encode()
        master = self.base / 'master.json'
        publication.write(master, dict(repositories=list(self.graph)))
        publication.write(self.base / 'definitions.json', dict(projects=self.graph))
        self.state['requests']['snode.c']['v1.0.0']['definition'] = self.graph['snode.c']
        self.state['requests']['upstream'] = {'v1.0.0': dict(definition=self.graph['upstream'], capture='90', revision='2')}
        self.save()
        self.add_capture('upstream', '90')
        self.add_capture('snode.c', '110', revision='3', cause='dependent', cascade='90')
        self.feed(['upstream', 'snode.c'], capture='90')
        info = publication.published(self.root, self.row)[0]
        info['publications']['snode.c'].update(capture='110', revision='3')
        own = info['releases']['snode.c']['v1.0.0']
        own['revision'] = '3'
        own['publications']['snode.c'].update(capture='110', revision='3')
        self.state['runs']['110']['nodes'] = {self.row['id'] + '/snode.c': dict(
            status='published', requires=['upstream'], dependencies=repository.binding(info, ['upstream']))}
        self.state['runs']['90']['nodes'] = {self.row['id'] + '/snode.c': dict(status='superseded')}
        publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
        self.save()
        with patch.dict(os.environ, CI_MASTER=str(master)), patch.object(repository, 'REPOSITORIES', tuple(self.graph)):
            self.tick()
        self.assertEqual(self.node('mqttsuite')['status'], 'superseded')
        self.assertEqual(self.node('mqttsuite', '90')['builds'], 1)
        return None


class ConcurrentControlTest(CoordinatorCase):
    def test_publisher_terminal_outcome_wins_over_stale_tick(self):
        for terminal in ('superseded', 'failed', 'cancelled'):
            with self.subTest(terminal=terminal):
                if terminal != 'superseded':
                    self.doCleanups()
                    self.setUp()
                self.tick()
                self.state = publication.read(self.root / 'status.json')
                node = self.state['runs']['100']['nodes'][self.row['id'] + '/snode.c']
                node.update(status='publishing', artifact=dict(id=1234, digest='sha256:' + 'a' * 64),
                            publisher_intent='publisher', publisher=900, waiting=True)
                self.save()
                original = dispatch.transaction
                injected = []

                def transaction(root, payload):
                    if payload.get('nodes') and not injected:
                        injected.append(True)
                        with patch.dict(os.environ, BUILD_ATTEMPT='1'):
                            repository.run('bash', str(repository.ROOT / 'ci/publish/status.sh'), str(root), 'status',
                                str(self.bundle), json.dumps(self.row), 'snode.c', terminal)
                        injected.append(copy.deepcopy(publication.read(root / 'status.json')['runs']['100']['nodes'][self.row['id'] + '/snode.c']))
                    return original(root, payload)

                with patch.object(dispatch, 'transaction', side_effect=transaction), \
                        patch.object(dispatch, 'observe', side_effect=lambda n, p, r: n):
                    self.tick()
                actual = self.node()
                self.assertEqual(actual, injected[1])
                self.assertEqual(actual['status'], terminal)
                self.assertNotIn('Publication ended without a receipt', actual.get('reason', ''))
        return None

    def test_concurrent_intent_rejection_prevents_dispatch(self):
        original = dispatch.transaction
        injected = []

        def transaction(root, payload):
            nodes = payload.get('nodes', [])
            if nodes and nodes[0][2].get('request') and not injected:
                injected.append(True)
                state = publication.read(root / 'status.json')
                state['runs']['100'].setdefault('nodes', {})[self.row['id'] + '/snode.c'] = dict(
                    status='failed', reason='Concurrent authoritative failure', builds=2)
                publication.write(root / 'status.json', state)
                self.state = state
                self.save()
            return original(root, payload)

        with patch.object(dispatch, 'transaction', side_effect=transaction):
            self.tick()
        self.assertEqual(self.posts, [])
        self.assertEqual(self.node()['reason'], 'Concurrent authoritative failure')
        self.assertEqual(self.node()['builds'], 2)
        return None

    def reserve_before_response(self, endpoint, payload=None, token=None):
        result = self.api(endpoint, payload, token)
        if payload and 'orchestrate-packages.yml/dispatches' in endpoint:
            request = json.loads(payload['inputs']['request'])
            if request['project'] == 'mqttsuite':
                with patch.dict(os.environ, RELEASE_PARENT=json.dumps(request), RELEASE_TAG='v1.0.0',
                                RELEASE_SHA='b' * 40, RELEASE_REQUESTED_AT='', RELEASE_RUN='0',
                                RELEASE_PROJECT='mqttsuite', GITHUB_RUN_ID=str(result['workflow_run_id']),
                                GITHUB_RUN_ATTEMPT='1', GITHUB_WORKFLOW_REF=dispatch.COORDINATOR +
                                '/.github/workflows/orchestrate-packages.yml@refs/heads/main'):
                    repository.run('bash', str(repository.ROOT / 'ci/publish/status.sh'), str(self.root), 'reserve')
                self.early_runs.append(result['workflow_run_id'])
                if self.lose_response:
                    raise dispatch.ApiError(0, 'Dispatch response lost after accepted reservation')
        return result

    def early_capture_acknowledgement(self, lost=False):
        self.early_runs, self.lose_response = [], lost
        self.feed(['snode.c'])
        with patch.object(dispatch, 'api', side_effect=self.reserve_before_response):
            self.tick()
        self.tick()
        node = self.node('mqttsuite')
        inputs = dict(tag='v1.0.0', commit='b' * 40, recipe=self.context['recipe_commit'],
                      dependencies={'snode.c': dict(source=self.sources['snode.c'], revision=2)})
        checksum = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        self.assertEqual(node['source'], dict(run=self.early_runs[0], attempt=1, inputs=checksum))
        self.assertEqual(node.get('builds', 0), 1, 'The actual capture run must spend one build attempt')
        self.assertEqual(len([p for _, p in self.posts if json.loads(p['inputs']['request'])['project'] == 'mqttsuite']), 1)
        return None

    def test_early_reservations_exhaust_three_attempts_and_operator_retry_restarts_the_budget(self):
        self.early_runs, self.lose_response = [], True
        self.feed(['snode.c'])
        with (patch.object(dispatch.time, 'time', return_value=dispatch.time.time()) as clock,
              patch.object(dispatch, 'api', side_effect=self.reserve_before_response)):
            self.tick()
            for attempt in range(1, 4):
                self.assertEqual(self.node('mqttsuite')['builds'], attempt)
                capture_cases.CascadeCaptureTest.failed_capture(self, dispatch.ApiError(503, 'temporary capture read'))
                self.assertNotIn('request', self.node('mqttsuite'))
                self.assertFalse(self.node('mqttsuite')['waiting'])
                deadline = self.node('mqttsuite')['observation']['retry_at']
                clock.return_value = deadline + 1
                self.tick()
            node = self.node('mqttsuite')
            self.assertEqual(node['status'], 'failed')
            self.assertIn('builds dispatch budget exhausted', node['reason'])
            self.assertEqual((node['builds'], len(self.early_runs)), (3, 3))
            dispatch.transaction(self.root, dict(retry='100/mqttsuite/' + self.row['id']))
            self.tick()
        self.assertEqual((self.node('mqttsuite')['builds'], len(self.early_runs)), (1, 4))
        return None

    def test_early_capture_reservation_keeps_the_execution_attempt_counted(self):
        self.early_capture_acknowledgement()
        return None

    def test_lost_capture_response_counts_the_verified_early_reservation(self):
        self.early_capture_acknowledgement(lost=True)
        return None

    def test_acknowledgement_replay_preserves_newer_terminal_facts_and_attempt(self):
        self.tick()
        admitted = copy.deepcopy(self.node())
        number = admitted['source']['run']
        admitted.pop('source')
        admitted['builds'] = 0
        self.state['runs']['100']['nodes'][self.row['id'] + '/snode.c'].update(
            status='failed', reason='Authoritative failure', category='deterministic',
            source=dict(run=number, attempt=2), builds=0, publications=2,
            artifact=dict(id=9001, digest='sha256:' + 'a' * 64))
        self.save()
        previous = copy.deepcopy(self.node())
        ack = [('100', self.row['id'] + '/snode.c', admitted, number)]
        for _ in range(3):
            dispatch.transaction(self.root, dict(acknowledgements=ack))
        expected = previous | dict(builds=1)
        self.assertEqual(self.node(), expected)
        # Neither a changed intent nor a conflicting owner can spend another attempt.
        wrong = copy.deepcopy(admitted)
        wrong['request']['intent'] = 'another-intent'
        wrong['builds'] = 2
        dispatch.transaction(self.root, dict(acknowledgements=[('100', self.row['id'] + '/snode.c', wrong, number)]))
        wrong = admitted | dict(builds=2)
        dispatch.transaction(self.root, dict(acknowledgements=[('100', self.row['id'] + '/snode.c', wrong, number + 1)]))
        self.assertEqual(self.node(), expected)
        dispatch.transaction(self.root, dict(retry='100/snode.c/' + self.row['id']))
        retried = self.node()
        self.assertEqual((retried['builds'], retried['publications']), (0, 0))
        self.assertEqual(retried['artifact'], expected['artifact'])
        self.assertEqual(retried['source'], expected['source'])
        return None

    def test_publisher_acknowledgement_keeps_the_concurrent_failure(self):
        self.tick()
        self.finish()
        original = self.api
        outcome = []

        def api(endpoint, payload=None, token=None):
            result = original(endpoint, payload, token)
            if payload and 'sign-and-publish-packages.yml/dispatches' in endpoint:
                with patch.dict(os.environ, BUILD_ATTEMPT='1'):
                    repository.run('bash', str(repository.ROOT / 'ci/publish/status.sh'), str(self.root), 'status',
                                   str(self.bundle), json.dumps(self.row), 'snode.c', 'failed')
                outcome.append(copy.deepcopy(self.node()))
            return result

        with patch.object(dispatch, 'api', side_effect=api):
            self.tick()
        node = self.node()
        self.assertEqual(node['status'], 'failed')
        self.assertEqual(node['event'], outcome[0]['event'])
        self.assertEqual(node['publications'], 1)
        self.assertEqual(node['publisher'], 502)
        self.assertEqual(node['artifact'], outcome[0]['artifact'])
        self.assertEqual(len(self.posts), 2)
        return None

    def test_registering_capture_keeps_request_eligible_against_stale_observation(self):
        self.state['requests']['snode.c']['v1.0.0'].update(capture='200', eligible=True, reason='Capture pending')
        self.save()
        self.runs[dispatch.COORDINATOR, 200] = dict(event='workflow_dispatch', status='completed',
            path='.github/workflows/orchestrate-packages.yml', head_repository={'full_name': dispatch.COORDINATOR})
        bundle = self.base / 'registered-capture'
        shutil.copytree(self.bundle, bundle)
        context = publication.read(bundle / 'context.json') | dict(run_id='200')
        publication.write(bundle / 'context.json', context)
        self.bundles['200'] = bundle
        original = dispatch.transaction
        injected = []

        def transaction(root, payload):
            if payload.get('requests') and not injected:
                injected.append(True)
                repository.run('bash', str(repository.ROOT / 'ci/publish/status.sh'), str(root), 'status',
                               str(bundle), '-', '-', 'pending')
            return original(root, payload)

        with patch.object(dispatch, 'transaction', side_effect=transaction), \
                patch.object(dispatch, 'capacity', return_value=(0, {})):
            self.tick()
        request = publication.read(self.root / 'status.json')['requests']['snode.c']['v1.0.0']
        self.assertTrue(request['eligible'])
        self.assertEqual(request['reason'], 'Capture registered')
        return None


class ReadmeCommitTest(CoordinatorCase):
    def test_copy_site_preserves_generated_blocks_before_any_render(self):
        publication.copy_site(self.root)
        publication.render(self.root, self.state)
        self.save()
        previous = (self.root / 'README.md').read_bytes()
        publication.copy_site(self.root)
        self.assertEqual((self.root / 'README.md').read_bytes(), previous)
        return None

    def test_merge_readme_keeps_remote_generated_blocks_without_render(self):
        text = '# Guide\n<!-- packages:begin projects -->\nold\n<!-- packages:end projects -->\n'
        (self.root / 'README.md').write_text(text)
        self.save()
        previous = self.git('rev-parse', 'HEAD', cwd=self.root)
        (self.root / 'README.md').write_text(text.replace('old', 'remote'))
        self.save()
        remote = self.git('rev-parse', 'HEAD', cwd=self.root)
        (self.root / 'README.md').write_text(text.replace('# Guide', '# New guide'))
        repository.run('python3', '-m', 'ci.publish.publication', 'merge-readme', str(self.root), previous, remote)
        self.assertEqual((self.root / 'README.md').read_text(), text.replace('# Guide', '# New guide').replace('old', 'remote'))
        return None


class PublicationCommitTest(unittest.TestCase):
    def test_actual_feed_commit_and_replay_preserve_rendered_blocks(self):
        import test_deployments as deployments
        fixture = deployments.DeploymentTest()
        with fixture.deployment('ReviewOrg', 'Control', 'Feed', ('library', 'application', 'plugin', 'bundle')):
            fixture.notify('library', 'v2.0.0', fixture.tag('library', 'v2.0.0'))
            fixture.drain()
            before = fixture.pages()
            fixture.notify('library', 'v1.9.0', fixture.tag('library', 'v1.9.0'))
            fixture.drain()
            readme = fixture.git('show', 'stable:README.md', cwd=fixture.base / 'feed.git') + '\n'
            self.assertEqual(readme.encode(), before['README.md'])
            current = fixture.git('rev-parse', 'stable', cwd=fixture.base / 'feed.git')
            number, _, _, request = next(p for p in reversed(fixture.posts) if p[2] == 'publish')
            with patch.object(apt, 'signer', side_effect=AssertionError('Replay signing')):
                fixture.publish(number, request, fixture.bundles[request['capture']])
            self.assertEqual(fixture.git('rev-parse', 'stable', cwd=fixture.base / 'feed.git'), current)
            self.assertEqual(fixture.git('show', 'stable:README.md', cwd=fixture.base / 'feed.git') + '\n', readme)
        return None

    def test_highest_publication_preserves_blocks_before_the_control_render(self):
        import test_deployments as deployments
        fixture = deployments.DeploymentTest()
        with fixture.deployment('ReviewOrg', 'Control', 'Feed', ('library', 'application', 'plugin', 'bundle')):
            fixture.notify('library', 'v2.0.0', fixture.tag('library', 'v2.0.0'))
            before = fixture.pages()
            fixture.drain()
            self.assertEqual((fixture.root / 'README.md').read_bytes(), before['README.md'])
            self.assertEqual({str(p.relative_to(fixture.root)): p.read_bytes() for p in (fixture.root / 'status').rglob('*')
                              if p.is_file()}, {k: v for k, v in before.items() if k.startswith('status/')})
        return None

    def test_replay_refreshes_only_authored_content_and_rejects_conflicting_bytes(self):
        import test_deployments as deployments
        fixture = deployments.DeploymentTest()
        with fixture.deployment('ReviewOrg', 'Control', 'Feed', ('library', 'application', 'plugin', 'bundle')):
            fixture.notify('library', 'v2.0.0', fixture.tag('library', 'v2.0.0'))
            fixture.drain()
            before = fixture.pages()
            number, _, _, request = next(p for p in reversed(fixture.posts) if p[2] == 'publish')
            bundle = fixture.bundles[request['capture']]
            fixture.site = fixture.base / 'content/site'
            shutil.copytree(fixture.real_root / 'site', fixture.site)
            shutil.copytree(fixture.real_root / 'install', fixture.site.parent / 'install')
            guide = fixture.site / 'docs/publication.md'
            guide.write_text(guide.read_text() + '\nAuthored refresh fixture.\n')
            previous = fixture.git('rev-parse', 'stable', cwd=fixture.base / 'feed.git')
            state = (fixture.root / 'status.json').read_bytes()
            with patch.object(apt, 'signer', side_effect=AssertionError('Replay signing')), \
                    patch.object(cleanup, 'cleanup', side_effect=AssertionError('Replay cleanup')), \
                    patch.object(linux, 'publish', side_effect=AssertionError('Replay index write')):
                fixture.publish(number, request, bundle)
            self.assertNotEqual(fixture.git('rev-parse', 'stable', cwd=fixture.base / 'feed.git'), previous)
            self.assertEqual((fixture.root / 'docs/publication.md').read_bytes(), guide.read_bytes())
            self.assertEqual((fixture.root / 'status.json').read_bytes(), state)
            self.assertEqual((fixture.root / 'README.md').read_bytes(), before['README.md'])
            changed = fixture.git('diff', '--name-only', previous, 'HEAD', cwd=fixture.root).splitlines()
            self.assertEqual(changed, ['docs/publication.md'])
            # A fresh download with different owned bytes under this receipt fails before mutation.
            manifest = next(fixture.outputs[request['run']].rglob('build.json'))
            metadata = publication.read(manifest)
            name = next(n for n in metadata['files'] if n.endswith('.deb'))
            package = manifest.parent / name
            package.write_bytes(package.read_bytes() + b'different artifact bytes')
            metadata['files'][name] = repository.digest(package)
            publication.write(manifest, metadata)
            previous = fixture.git('rev-parse', 'stable', cwd=fixture.base / 'feed.git')
            with self.assertRaisesRegex(RuntimeError, 'Different package content under the same publication identity'):
                fixture.publish(number, request, bundle)
            self.assertEqual(fixture.git('rev-parse', 'stable', cwd=fixture.base / 'feed.git'), previous)
            self.assertEqual((fixture.root / 'status.json').read_bytes(), state)
        return None
