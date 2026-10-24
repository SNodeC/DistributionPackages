"""First-deployment registration, cause selection and independent release versions."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import offline

from ci import dispatch, repository
from ci.publish import publication


class TagActivationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.graph = copy.deepcopy(repository.PROJECTS)
        self.row = repository.rows(self.graph['snode.c'])[0]
        self.runtime = self.root / 'runtime.json'
        self.addCleanup(repository.definition_data.cache_clear)
        guard = patch.object(dispatch, 'api', side_effect=AssertionError('Unexpected API read in local regression'))
        guard.start()
        self.addCleanup(guard.stop)
        return None

    def definition(self, name, commit):
        return dict(copy.deepcopy(self.graph[name]), _commit=commit, _digest='f' * 64)

    def test_inactive_repositories_are_not_read_during_framework_registration(self):
        claimed = self.graph['snode.c']
        seen = []

        def definition(name, commit):
            seen.append((name, commit))
            self.assertEqual(name, 'snode.c', 'Inactive repository definition was consulted')
            return self.definition(name, commit)

        publication.write(self.root / 'status.json', {})
        with patch.object(repository, 'DEFINITIONS', self.runtime), \
                patch.dict(repository.PROJECTS, self.graph, clear=True), patch.dict(repository.ROW_PROJECTS, {}, clear=True), \
                patch.object(repository, 'definition', side_effect=definition), \
                patch.object(publication, 'published', return_value=({}, 'feed')):
            repository.configure(self.root, 'snode.c', 'a' * 40, claimed)
            self.assertTrue(repository.ROW_PROJECTS)
            self.assertTrue(all(set(g) == {'snode.c'} for g in repository.ROW_PROJECTS.values()))
        self.assertEqual(seen, [('snode.c', 'a' * 40)])
        return None

    def test_missing_prerequisite_does_not_prevent_durable_full_matrix_registration(self):
        claimed = self.graph['mqttsuite']
        publication.write(self.root / 'status.json', {})
        with patch.object(repository, 'DEFINITIONS', self.runtime), \
                patch.dict(repository.PROJECTS, self.graph, clear=True), patch.dict(repository.ROW_PROJECTS, {}, clear=True), \
                patch.object(repository, 'definition', side_effect=self.definition), \
                patch.object(publication, 'published', return_value=({}, 'feed')), \
                patch.dict(os.environ, RELEASE_PROJECT='mqttsuite', RELEASE_SHA='b' * 40, RELEASE_TAG='v1.0.0',
                           RELEASE_REQUESTED_AT='2026-10-21T00:00:00Z', RELEASE_RUN='99'):
            repository.configure(self.root, 'mqttsuite', 'b' * 40, claimed)
            allocation = publication.reserve(self.root, 'mqttsuite', '100')
            self.assertEqual(set(allocation), {'mqttsuite'})
            request = publication.read(self.root / 'status.json')['requests']['mqttsuite']['v1.0.0']
            self.assertEqual(request['sha'], 'b' * 40)
            self.assertEqual(request['definition']['matrix'], claimed['matrix'])
            self.assertEqual(request['definition']['depends_on'], ['snode.c'])
            self.assertEqual(request['definition']['_digest'], 'f' * 64)
        return None

    def test_chain_selects_highest_tag_even_after_a_lower_direct_request_failed(self):
        refs = '\n'.join([
            'b' * 40 + '\trefs/tags/v1.9.0',
            'c' * 40 + '\trefs/tags/v2.0.0',
            'd' * 40 + '\trefs/tags/v2.0.0^{}',
            'e' * 40 + '\trefs/tags/v1.99.0',
            'f' * 40 + '\trefs/tags/v02.9.0',
        ])
        requests = {'mqttsuite': {'v1.9.0': dict(sha='b' * 40, tag='v1.9.0', eligible=False)}}
        with patch.object(repository, 'run', return_value=refs) as listing, \
                patch.object(repository, 'definition', side_effect=self.definition), \
                patch.object(dispatch, 'api', side_effect=AssertionError('No HEAD selection allowed')):
            selected = repository.dependent_source('mqttsuite', requests)
        self.assertEqual(selected['_tag'], 'v2.0.0')
        self.assertEqual(selected['_commit'], 'd' * 40)
        self.assertEqual(listing.call_count, 1, 'Tag and SHA must come from one listing')
        return None

    def test_transient_highest_tag_listing_defers_without_head_or_old_source(self):
        requests = {'mqttsuite': {'v1.9.0': dict(sha='b' * 40, tag='v1.9.0')}}
        before = copy.deepcopy(requests)
        with patch.object(repository, 'run', side_effect=dispatch.ApiError(503, 'tag listing unavailable')), \
                patch.object(dispatch, 'api', side_effect=AssertionError('No HEAD fallback')):
            with self.assertRaisesRegex(dispatch.ApiError, 'tag listing unavailable'):
                repository.dependent_source('mqttsuite', requests)
        self.assertEqual(requests, before)
        return None

    def test_coordinator_production_has_no_deployment_specific_product_identity(self):
        import re
        files = [p for folder in ('ci', '.github/workflows') for p in (repository.ROOT / folder).rglob('*')
                 if p.suffix in {'.py', '.sh', '.yml'}]
        for path in files:
            with self.subTest(path=str(path.relative_to(repository.ROOT))):
                self.assertIsNone(re.search(r'SNodeC|DistributionPackages|mqttsuite|snodec', path.read_text()))
        return None

    def test_dependent_version_is_rejected_and_feed_identity_is_configuration(self):
        master = self.root / 'master.json'
        publication.write(master, dict(repositories=['widget'], settings={'dependent_version': 'published'}))
        with self.assertRaisesRegex(ValueError, 'highest semantic version'):
            repository.load_master(master)
        publication.write(master, dict(repositories=['widget'], feed={'repository': 'Binaries', 'branch': 'stable'}))
        config = repository.load_master(master)
        self.assertEqual(config['feed'], dict(repository='Binaries', branch='stable'))
        self.assertNotIn('dependent_version', config['settings'])
        return None

    def generation(self, capture, tag, revision, status):
        return dict(run_id=capture, revisions={'mqttsuite': revision}, targets=[self.row],
                    context=dict(contract=3, projects={'mqttsuite': self.graph['mqttsuite']}),
                    sources={self.row['id']: {'mqttsuite': {'refs/tags/' + tag: 'b' * 40}}},
                    nodes={self.row['id'] + '/mqttsuite': dict(status=status, attempt=1, job_url='job-' + capture)})

    def test_status_projection_keeps_highest_failure_when_an_older_version_finishes(self):
        high = self.generation('100', 'v2.0.0', '11', 'failed')
        low = self.generation('200', 'v1.9.0', '12', 'pending')
        state = dict(runs={'100': high, '200': low})
        first = publication.projection(state)['targets'][self.row['id'] + '/mqttsuite']
        self.assertEqual(first['run_id'], '100')
        self.assertEqual(first['status'], 'failed')
        low['nodes'][self.row['id'] + '/mqttsuite'].update(status='published', published_at='later')
        self.assertEqual(publication.projection(state)['targets'][self.row['id'] + '/mqttsuite'], first)
        return None

    def test_revision_and_replay_guard_is_scoped_to_the_same_semantic_version(self):
        def metadata(tag, revision, files):
            return dict(revision=revision, sources={'mqttsuite': {'refs/tags/' + tag: 'b' * 40}}, files=files, unsigned_files=files,
                        context=dict(build_project='mqttsuite', source_tags={'mqttsuite': tag}))

        high = metadata('v2.0.0', '11', {'mqttsuite_2.deb': 'a' * 64})
        low = metadata('v1.9.0', '12', {'mqttsuite_1.deb': 'b' * 64})
        current = dict(low, releases={'mqttsuite': {'v1.9.0': low}})
        self.assertTrue(repository.publication_needed(current, high))
        current['releases']['mqttsuite']['v2.0.0'] = high
        self.assertFalse(repository.publication_needed(current, high))
        with self.assertRaisesRegex(RuntimeError, 'Different package content'):
            repository.publication_needed(current, dict(high, files={'mqttsuite_2.deb': 'c' * 64}, unsigned_files={'mqttsuite_2.deb': 'c' * 64}))
        with self.assertRaisesRegex(RuntimeError, 'Superseded publication'):
            repository.publication_needed(current, metadata('v2.0.0', '10', high['files']))
        return None
