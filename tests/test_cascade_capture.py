"""Per-row cascade handoffs use the ordinary capture and execution ledger."""
import copy
import json
import hashlib
import io
import zipfile
import os
import subprocess
from unittest.mock import patch
from support import CoordinatorCase
from ci import dispatch, repository
from ci.publish import publication


class CascadeCaptureTest(CoordinatorCase):
    def test_empty_feed_control_is_a_noop_and_reads_no_product(self):
        self.state = dict(repository=repository.FEED, branch=repository.FEED_BRANCH, runs={})
        self.save()
        with patch.object(repository, 'content', side_effect=AssertionError('Inactive source read')), \
                patch.object(dispatch, 'capacity', side_effect=AssertionError('Empty admission')):
            self.assertFalse(dispatch.tick(self.root, {}))
        self.assertEqual(publication.read(self.root / 'status.json')['runs'], {})
        self.assertEqual(self.posts, [])
        return None

    def test_framework_publication_admits_capture_once_and_counts_queued_intents(self):
        self.feed(['snode.c'])
        self.tick()
        requests = [json.loads(payload['inputs']['request']) for _, payload in self.posts]
        self.assertEqual({r['project'] for r in requests}, {'mqttsuite', 'snode.c-idp'})
        self.assertTrue(all(r['kind'] == 'capture' and r['root'] == '100' for r in requests))
        self.assertTrue(all('orchestrate-packages.yml' in path for path, _ in self.posts))
        before = copy.deepcopy(self.posts)
        self.tick()
        self.assertEqual(self.posts, before)
        self.assertTrue(self.node('mqttsuite')['waiting'])
        self.assertEqual(self.node('mqttsuite')['builds'], 1)
        derived = publication.projection(publication.read(self.root / 'status.json'))
        self.assertNotIn(self.row['id'] + '/mqttsuite', derived['targets'])
        return None

    def test_inactive_dependent_is_not_captured_even_when_tags_exist(self):
        self.state['requests'].pop('mqttsuite')
        self.save()
        self.feed(['snode.c'])
        with patch.object(repository, 'dependent_source', side_effect=AssertionError('Inactive selection')):
            self.tick()
        self.assertEqual([json.loads(p['inputs']['request'])['project'] for _, p in self.posts], ['snode.c-idp'])
        return None

    def test_coordinator_capture_checks_intent_and_cannot_activate_a_source(self):
        self.feed(['snode.c'])
        self.tick()
        request = json.loads(self.posts[0][1]['inputs']['request'])
        config = copy.deepcopy(self.graph[request['project']]) | dict(_tag='v2.0.0', _commit='e' * 40)
        original_read = dispatch.read

        def read(path, default=None):
            return publication.read(self.root / 'status.json') if str(path) == 'published/status.json' else original_read(path, default)

        with patch.object(dispatch, 'read', side_effect=read), \
                patch.object(dispatch, 'dependent_source', return_value=config), \
                patch.object(dispatch, 'content', return_value=b'2.0.0\n'), patch.object(dispatch, 'configure') as configure, \
                patch.dict(os.environ, GITHUB_ACTOR='ci[bot]', GITHUB_TRIGGERING_ACTOR='ci[bot]'):
            release = dispatch.intake(request)
            self.assertEqual((release['tag'], release['sha'], release['cause']), ('v2.0.0', 'e' * 40, 'dependent'))
            self.assertEqual(configure.call_args.args[2], 'e' * 40)
            with self.assertRaisesRegex(ValueError, 'admitted coordinator intent'):
                dispatch.intake(request | dict(intent='forged'))
            self.state = publication.read(self.root / 'status.json')
            self.state['requests'].pop(request['project'])
            self.save()
            with self.assertRaisesRegex(ValueError, 'inactive'):
                dispatch.intake(request)
        return None

    def test_child_definition_that_adds_an_in_cascade_arm_waits_for_that_arm(self):
        # The registered join originally needed only the framework. Its captured
        # highest tag adds MQTT while the framework cascade is already underway.
        self.feed(['snode.c', 'mqttsuite'], capture='previous')
        self.state = publication.read(self.root / 'status.json')
        graph = copy.deepcopy(self.graph)
        graph['snode.c-idp']['depends_on'] = ['snode.c', 'mqttsuite']
        child = self.base / 'join-child'
        context = self.context | dict(run_id='200', release_project='snode.c-idp', cascade='100', cause='dependent', projects=graph)
        profile = dict(projects=graph, sources=self.sources, baseline=publication.published(self.root, self.row)[0])
        old = copy.deepcopy(profile['baseline'])
        old['releases']['snode.c']['v1.0.0']['revision'] = '1'
        self.state['runs']['previous'] = dict(context=self.context, revisions={}, targets=[self.row], sources={},
            nodes={self.row['id'] + '/mqttsuite': dict(status='published', requires=['snode.c'],
                   dependencies=repository.binding(old, ['snode.c']))})
        for name, value in dict(context=context, revisions={'snode.c-idp': '3'}, targets=[self.row],
                                profiles={self.row['id']: profile}, sources={self.row['id']: self.sources}, checksums={}).items():
            publication.write(child / (name + '.json'), value)
        publication.record_run(child, self.state, context)
        # The root is already handed off; no fresh cascade may substitute for this join.
        self.state['runs']['100']['nodes'] = {self.row['id'] + '/' + p: dict(status='superseded', category='excluded')
                                           for p in ('snode.c', 'mqttsuite', 'snode.c-idp')}
        self.save()
        self.tick({'100': self.bundle, '200': child})
        self.assertEqual(self.posts, [], 'Old MQTT publication cannot satisfy this in-cascade arm')
        self.assertEqual(self.node('snode.c-idp', '200')['status'], 'pending')
        return None

    def test_completed_handoff_execution_is_durably_reconciled(self):
        self.feed(['snode.c'])
        self.tick()
        request = json.loads(self.posts[0][1]['inputs']['request'])
        project = request['project']
        number = self.node(project)['source']['run']
        self.runs[dispatch.COORDINATOR, number].update(status='completed', conclusion='success')
        self.jobs[dispatch.COORDINATOR, number][0].update(status='completed', conclusion='success')
        self.tick()
        node = self.node(project)
        self.assertEqual(node['status'], 'superseded')
        self.assertFalse(node['waiting'])
        self.assertEqual(node['builds'], 1)
        return None

    def failed_capture(self, error, mutate=None, corrupt=False, missing=False, malformed=False):
        request = next(json.loads(p['inputs']['request']) for _, p in reversed(self.posts)
                       if json.loads(p['inputs']['request'])['project'] == 'mqttsuite')
        project = request['project']
        number = self.node(project)['source']['run']
        event = self.base / 'event.json'
        publication.write(event, dict(inputs=dict(request=json.dumps(request))))
        with patch.dict(os.environ, GITHUB_EVENT_PATH=str(event), GITHUB_RUN_ID=str(number), GITHUB_RUN_ATTEMPT='1'):
            dispatch.capture_failure(error)
        result = publication.read(self.base / 'capture-result.json')
        if mutate:
            mutate(result)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('capture-result.json', json.dumps(result))
        payload = b'truncated ZIP' if malformed else buffer.getvalue()
        self.artifacts[dispatch.COORDINATOR, number] = [dict(id=1234, name='capture-result-1', expired=False,
            workflow_run=dict(id=number), digest='sha256:' + (('0' * 64) if corrupt else hashlib.sha256(payload).hexdigest()))]
        if missing:
            self.artifacts[dispatch.COORDINATOR, number] = []
        self.runs[dispatch.COORDINATOR, number].update(status='completed', conclusion='failure')
        self.jobs[dispatch.COORDINATOR, number][0].update(status='completed', conclusion='failure')
        original = dispatch.subprocess.run

        def transport(args, **kwargs):
            if args[0:2] == ['gh', 'api'] and args[-1].endswith('/artifacts/1234/zip'):
                kwargs['stdout'].write(payload)
                result = dispatch.subprocess.CompletedProcess(args, 0)
            else:
                result = original(args, **kwargs)
            return result

        with patch.object(dispatch.subprocess, 'run', side_effect=transport):
            self.tick()
        return project

    def test_temporary_capture_definition_failure_defers_instead_of_becoming_deterministic(self):
        self.feed(['snode.c'])
        self.tick()
        project = self.failed_capture(dispatch.ApiError(503, 'Source definition temporarily unavailable: HTTP 503'))
        node = self.node(project)
        self.assertEqual(node['status'], 'pending', 'Temporary source-read failure must remain retryable')
        self.assertEqual(node['observation']['category'], 'transient')
        self.assertIn('503', node['observation']['reason'])
        self.assertGreater(node['observation']['retry_at'], dispatch.time.time())
        self.assertEqual(node.get('publications', 0), 0)
        self.assertEqual(node['builds'], 1)
        self.assertFalse(node['waiting'])
        before = copy.deepcopy(self.posts)
        self.tick()
        self.assertEqual(self.posts, before, 'Backoff must prevent a second capture')
        with patch.object(dispatch.time, 'time', return_value=node['observation']['retry_at'] + 1):
            self.tick()
        self.assertEqual(len(self.posts), len(before) + 1)
        self.assertEqual(self.node(project)['builds'], 2)
        return None

    def test_real_git_process_failures_reach_bounded_capture_retries(self):
        self.feed(['snode.c'])
        self.tick()
        moment = dispatch.time.time()
        for attempt, error in enumerate((subprocess.CalledProcessError(128, ['git', 'ls-remote']),
                                         subprocess.TimeoutExpired(['git', 'ls-remote'], 120),
                                         subprocess.CalledProcessError(128, ['git', 'fetch'])), 1):
            with patch.object(dispatch.time, 'time', return_value=moment):
                project = self.failed_capture(error)
            node = self.node(project)
            self.assertEqual(node['observation']['category'], 'transient')
            self.assertEqual(node['builds'], attempt)
            self.assertEqual(node.get('publications', 0), 0)
            self.assertFalse(node['waiting'])
            moment = node['observation']['retry_at'] + 1
            with patch.object(dispatch.time, 'time', return_value=moment):
                self.tick()
        node = self.node(project)
        self.assertEqual(node['status'], 'failed')
        self.assertIn('budget exhausted', node['reason'])
        self.assertEqual(node['builds'], 3)
        return None

    def test_deterministic_capture_failure_is_terminal_without_spending_publication_budget(self):
        self.feed(['snode.c'])
        self.tick()
        project = self.failed_capture(ValueError('Release tag and VERSION disagree'))
        node = self.node(project)
        self.assertEqual((node['status'], node['category']), ('failed', 'configuration'))
        self.assertIn('VERSION disagree', node['reason'])
        before = copy.deepcopy(self.posts)
        for _ in range(3):
            self.tick()
        self.assertEqual(self.posts, before)
        self.assertEqual((self.node(project)['builds'], self.node(project).get('publications', 0)), (1, 0))
        return None

    def test_capture_failure_result_must_match_the_attempt(self):
        self.feed(['snode.c'])
        self.tick()
        project = self.failed_capture(dispatch.ApiError(503, 'temporary'), lambda r: r.update(attempt=2))
        node = self.node(project)
        self.assertEqual(node['status'], 'failed')
        self.assertEqual(node['observation']['category'], 'configuration')
        self.assertIn('does not match', node['reason'])
        self.assertEqual(node['builds'], 1)
        return None

    def test_transient_capture_retries_are_bounded_and_operator_retry_is_supported(self):
        self.feed(['snode.c'])
        self.tick()
        errors = [dispatch.ApiError(503, 'unavailable'), dispatch.ApiError(429, 'rate limit'), TimeoutError('timed out')]
        with patch.object(dispatch.time, 'time', return_value=dispatch.time.time()) as clock:
            for count, error in enumerate(errors, 1):
                project = self.failed_capture(error)
                node = self.node(project)
                self.assertEqual((node['status'], node['builds'], node.get('publications', 0)), ('pending', count, 0))
                self.assertEqual(node['observation']['category'], 'transient')
                clock.return_value = node['observation']['retry_at'] + 1
                self.tick()
        node = self.node('mqttsuite')
        self.assertEqual(node['status'], 'failed')
        self.assertIn('builds dispatch budget exhausted', node['reason'])
        self.assertEqual(len([p for _, p in self.posts if json.loads(p['inputs']['request'])['project'] == 'mqttsuite']), 3)
        self.assertTrue(self.node('snode.c-idp')['waiting'], 'Independent capture remains admitted')
        dispatch.transaction(self.root, dict(retry='100/mqttsuite/' + self.row['id']))
        self.tick()
        self.assertEqual(self.node('mqttsuite')['builds'], 1)
        self.assertTrue(self.node('mqttsuite')['waiting'])
        return None

    def test_missing_capture_failure_evidence_fails_closed(self):
        self.feed(['snode.c'])
        self.tick()
        project = self.failed_capture(dispatch.ApiError(503, 'temporary'), missing=True)
        node = self.node(project)
        self.assertEqual(node['status'], 'failed')
        self.assertIn('without its verified result', node['reason'])
        self.assertFalse(node['waiting'])
        self.assertEqual(node['builds'], 1)
        before = copy.deepcopy(self.posts)
        self.tick()
        self.assertEqual(self.posts, before)
        return None

    def test_corrupt_capture_failure_evidence_fails_closed(self):
        self.feed(['snode.c'])
        self.tick()
        project = self.failed_capture(dispatch.ApiError(503, 'temporary'), corrupt=True)
        node = self.node(project)
        self.assertEqual(node['status'], 'failed')
        self.assertIn('digest mismatch', node['reason'])
        self.assertEqual(node['observation']['category'], 'configuration')
        self.assertEqual(node['builds'], 1)
        return None

    def test_malformed_capture_zip_is_a_node_local_integrity_failure(self):
        self.feed(['snode.c'])
        self.tick()
        project = self.failed_capture(dispatch.ApiError(503, 'temporary'), malformed=True)
        node = self.node(project)
        self.assertEqual(node['status'], 'failed')
        self.assertIn('Malformed artifact ZIP', node['reason'])
        self.assertEqual(node['observation']['category'], 'configuration')
        self.assertFalse(node['waiting'])
        self.assertEqual(node['builds'], 1)
        self.assertTrue(self.node('snode.c-idp')['waiting'])
        return None

    def test_higher_cascade_cannot_erase_earlier_direct_notification_deduplication(self):
        self.feed(['snode.c'])
        self.tick()
        request = json.loads(self.posts[0][1]['inputs']['request'])
        project = request['project']
        before = copy.deepcopy(self.state['requests'])
        with patch.dict(os.environ, RELEASE_PARENT=json.dumps(request), RELEASE_TAG='v2.0.0', RELEASE_SHA='e' * 40,
                        GITHUB_RUN_ATTEMPT='1', RELEASE_REQUESTED_AT='', RELEASE_RUN='0'):
            revision = publication.reserve(self.root, project, str(self.node(project)['source']['run']))
        state = publication.read(self.root / 'status.json')
        self.assertEqual(state['requests'], before)
        parent = state['runs']['100']['nodes'][self.row['id'] + '/' + project]
        self.assertEqual(parent['source']['run'], self.node(project)['source']['run'])
        self.assertEqual(state['allocations'][str(parent['source']['run'])], revision)
        return None
