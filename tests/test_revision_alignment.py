"""Revision sharing at reservation, real capture/publication and display boundaries.

Reservation property fixtures register canonical synthetic generations; deployment
cases obtain contexts from prepare() and run actual local-Git CAS transactions.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ci import dispatch, repository
from ci.publish import publication
import support
import test_deployments as deployments
import test_review_findings as controls


class ReservationTest(support.CoordinatorCase):
    def setUp(self):
        super().setUp()
        for config in self.graph.values():
            config['matrix'] = {'linux': [dict(distribution='debian', suite='trixie', image='debian:trixie',
                architectures=['amd64', 'arm64', 'armhf', 'riscv64']),
                dict(distribution='debian', suite='forky', image='debian:forky', architectures=['amd64'])]}
            config['build'] = {'native': 'ci/package/native.sh'}
        self.rows = repository.rows(self.graph['mqttsuite'])
        context = patch.dict(repository.ROW_PROJECTS, {r['id']: self.graph for r in self.rows}, clear=True)
        context.start()
        self.addCleanup(context.stop)
        publication.write(Path(os.environ['CI_DEFINITIONS']), dict(projects=self.graph,
                          targets={r['id']: self.graph for r in self.rows}))
        self.state['counters'] = dict.fromkeys(self.graph, 2)
        self.state['allocations'] = {'100': {'snode.c': '2'}}
        root = self.state['runs']['100']
        root['context'].update(cascade='100', cause='release')
        root['sources'] = {r['id']: copy.deepcopy(self.sources) for r in self.rows}
        root['targets'] = self.rows
        root['nodes'] = {}
        self.state['runs']['110'] = copy.deepcopy(root) | dict(run_id='110', context=root['context'] | dict(cascade='110', run_id='110'))
        for row in self.rows:
            self.baseline(row, '2')
        self.save()
        return None

    def baseline(self, row, revision, checksum=None):
        info = support.feed_manifest(dict(sources={'snode.c': self.sources['snode.c']},
            versions={'snode.c': repository.package_version(row, '1.0.0', revision)},
            files={f'snodec_1.0.0-{revision}_{row["arch"]}.deb': checksum or row['arch']},
            publications={'snode.c': dict(capture='100', revision=revision)}), self.graph)
        directory = self.root / 'debian/dists' / row['suite'] / 'build.json'
        manifest = publication.read(directory, {'targets': {}})
        manifest['targets'][row['arch']] = info
        publication.write(directory, manifest)
        return None

    def intent(self, row, number, holder='100', tag='v1.0.0', commit=None, replay=False):
        self.state = publication.read(self.root / 'status.json')
        key = row['id'] + '/mqttsuite'
        node = self.state['runs'][holder].setdefault('nodes', {}).get(key, {})
        request = node.get('request') if replay else dict(capture=holder, target=row['id'], project='mqttsuite',
            kind='capture', intent='intent-' + str(number), cause='dependent', actor='ci[bot]', runner=['ubuntu-24.04'])
        if not replay:
            node = dict(status='running', cause='dependent', builds=1, waiting=True, request=request)
            self.state['runs'][holder]['nodes'][key] = node
        self.save()
        env = dict(RELEASE_PARENT=json.dumps(request), RELEASE_PROJECT='mqttsuite', RELEASE_TAG=tag,
                   RELEASE_SHA=commit or 'b' * 40, RELEASE_REQUESTED_AT='', RELEASE_RUN='0',
                   GITHUB_RUN_ID=str(number), GITHUB_RUN_ATTEMPT='1', GIT_ALLOW_PROTOCOL='file',
                   GITHUB_WORKFLOW_REF=dispatch.COORDINATOR + '/.github/workflows/orchestrate-packages.yml@refs/heads/main')
        return env

    def reserve(self, row, number, **kwargs):
        env = self.intent(row, number, **kwargs)
        with patch.dict(os.environ, env):
            result = publication.reserve(self.root, 'mqttsuite', str(number))['mqttsuite']
        self.state = publication.read(self.root / 'status.json')
        self.save()
        return int(result)

    def register(self, row, number, revision, tag='v1.0.0', commit=None):
        """Synthetic valid registration; actual prepare/record_run is tested below."""
        self.state['runs'][str(number)] = dict(run_id=str(number), revision=str(revision), revisions={'mqttsuite': str(revision)},
            sources={row['id']: {'mqttsuite': {'refs/tags/' + tag: commit or 'b' * 40}}}, targets=[row],
            context=self.context | dict(run_id=str(number), release_project='mqttsuite', tag=tag, cause='dependent', cascade='100'),
            nodes={row['id'] + '/mqttsuite': dict(status='published', cause='dependent')})
        self.save()
        return None

    def digest(self, row, tag='v1.0.0', commit=None, recipe=None):
        # Independent release-provenance projection, without allocation helpers.
        info = publication.published(self.root, row)[0]['releases']['snode.c']['v1.0.0']
        value = dict(tag=tag, commit=commit or 'b' * 40, recipe=recipe or self.context['recipe_commit'],
                     dependencies={'snode.c': dict(source=info['sources']['snode.c'], revision=int(info['revision']))})
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def test_five_rows_two_holders_share_one_counter_step_and_keep_direct_authority(self):
        requests = copy.deepcopy(self.state['requests'])
        revisions = [self.reserve(row, 200 + i, holder='110' if i % 2 else '100') for i, row in enumerate(self.rows)]
        self.assertEqual(revisions, [3] * 5)
        self.assertEqual(self.state['counters']['mqttsuite'], 3)
        self.assertEqual(self.state['requests'], requests)
        for i, row in enumerate(self.rows):
            node = self.state['runs']['110' if i % 2 else '100']['nodes'][row['id'] + '/mqttsuite']
            self.assertEqual(node['source'], dict(run=200 + i, attempt=1, inputs=self.digest(row)))
        return None

    def test_moved_tags_versions_tooling_and_dependency_revisions_separate_groups(self):
        first, second = self.rows[:2]
        self.assertEqual(self.reserve(first, 200), 3)
        for label, kwargs in [('moved', dict(commit='d' * 40)), ('higher', dict(tag='v2.0.0')),
                              ('tooling', {}), ('dependency', {})]:
            with self.subTest(label=label):
                if label == 'dependency':
                    self.baseline(second, '3')
                with patch.object(publication, 'recipe_commit', return_value='e' * 40 if label == 'tooling'
                                  else self.context['recipe_commit'], create=True):
                    number = self.state['counters']['mqttsuite'] + 300
                    previous = self.state['counters']['mqttsuite']
                    self.assertEqual(self.reserve(second, number, **kwargs), previous + 1)
        return None

    def test_replay_is_noop_but_unknown_or_changed_inputs_fail_without_writing(self):
        row = self.rows[0]
        self.reserve(row, 200)
        before = (self.root / 'status.json').read_bytes()
        self.assertEqual(self.reserve(row, 200, replay=True), 3)
        self.assertEqual((self.root / 'status.json').read_bytes(), before)
        for change in ['sha', 'dependencies', 'recipe', 'legacy']:
            with self.subTest(change=change):
                if change == 'dependencies':
                    self.baseline(row, '4')
                    self.save()
                if change == 'legacy':
                    self.state['runs']['100']['nodes'][row['id'] + '/mqttsuite']['source'].pop('inputs', None)
                    self.save()
                env = self.intent(row, 200, commit='f' * 40 if change == 'sha' else None, replay=True)
                before = (self.root / 'status.json').read_bytes()
                with patch.dict(os.environ, env), patch.object(publication, 'recipe_commit',
                        return_value='f' * 40 if change == 'recipe' else self.context['recipe_commit'], create=True):
                    with self.assertRaisesRegex(RuntimeError, 'Capture inputs changed or unavailable'):
                        publication.reserve(self.root, 'mqttsuite', '200')
                self.assertEqual((self.root / 'status.json').read_bytes(), before)
        return None

    def test_abandoned_reservation_can_reuse_but_terminal_unregistered_is_claim_only(self):
        a, b, c = self.rows[:3]
        self.reserve(a, 200)
        self.reserve(b, 201)
        node = self.state['runs']['100']['nodes'][b['id'] + '/mqttsuite']
        node.update(status='pending', builds=1)
        node.pop('source')
        node.pop('request')
        self.save()
        self.assertEqual(self.reserve(b, 202), 3, 'Abandoned attempt is not a registered row claim')
        for row in [a, b]:
            self.state['runs']['100']['nodes'][row['id'] + '/mqttsuite']['status'] = 'failed'
        self.save()
        self.assertEqual(self.reserve(c, 203), 4, 'Unregistered terminal holders cannot donate')
        self.assertEqual(self.reserve(a, 204, holder='110'), 4, 'Kept terminal link remains a same-row claim')
        return None

    def test_registered_terminal_holder_remains_donor_and_own_row_claim_forces_fresh(self):
        a, b = self.rows[:2]
        value = self.reserve(a, 200)
        self.register(a, 200, value)
        self.state['runs']['100']['nodes'][a['id'] + '/mqttsuite']['status'] = 'superseded'
        self.save()
        self.assertEqual(self.reserve(b, 201), 3)
        self.assertEqual(self.reserve(a, 202, holder='110'), 4)
        self.assertEqual(repository.work_index(self.state)[0][(a['id'], 'mqttsuite', 'v1.0.0')][0], 3)
        return None

    def test_version_scoped_direct_claims_and_conservative_live_claims(self):
        a, b, c = self.rows[:3]
        self.assertEqual(self.reserve(a, 200), 3)
        self.state['requests']['mqttsuite']['v0.9.0'] = self.state['requests']['mqttsuite']['v1.0.0'] | dict(revision='8')
        self.state['counters']['mqttsuite'] = 8
        self.save()
        self.assertEqual(self.reserve(b, 201), 3, 'Older direct version must not interfere')
        self.state['requests']['mqttsuite']['v1.0.0']['revision'] = '9'
        self.state['counters']['mqttsuite'] = 9
        self.save()
        self.assertEqual(self.reserve(c, 202), 10, 'Same-version direct reservation is a claim')
        self.assertEqual(self.reserve(a, 203, holder='110', tag='v0.9.0'), 11)
        self.assertEqual(self.reserve(a, 204), 12, 'A kept live row claim is conservative across versions')
        return None

    def test_checksums_remain_row_authority_and_same_row_recapture_is_fresh(self):
        row = self.rows[0]
        before = repository.binding(publication.published(self.root, row)[0], ['snode.c'])
        value = self.reserve(row, 200)
        self.register(row, 200, value)
        self.baseline(row, '2', 'changed bytes')
        self.save()
        after = repository.binding(publication.published(self.root, row)[0], ['snode.c'])
        self.assertNotEqual(before, after)
        self.assertEqual(self.state['runs']['100']['nodes'][row['id'] + '/mqttsuite']['source']['inputs'], self.digest(row))
        self.assertEqual(self.reserve(row, 201, holder='110'), 4)
        return None

    def test_seeded_orders_preserve_valid_row_uniqueness_and_counter_decisions(self):
        randomizer = random.Random(20261023)
        registered, highest = set(), {}
        for index in range(32):
            row = randomizer.choice(self.rows)
            tag = randomizer.choice(['v1.0.0', 'v2.0.0'])
            commit = ('b' if tag == 'v1.0.0' else 'd') * 40
            number = 200 + index
            previous = self.state['counters']['mqttsuite']
            revision = self.reserve(row, number, tag=tag, commit=commit)
            self.assertIn(self.state['counters']['mqttsuite'] - previous, [0, 1])
            self.assertGreater(revision, highest.get((row['id'], tag), 0))
            identity = (row['id'], tag, revision)
            self.assertNotIn(identity, registered)
            if index % 5 != 0:
                self.register(row, number, revision, tag, commit)
                registered.add(identity)
                highest[row['id'], tag] = revision
            else:
                node = self.state['runs']['100']['nodes'][row['id'] + '/mqttsuite']
                node.pop('source')
                node.pop('request')
                self.save()
        return None

    def test_two_successive_vectors_align_and_missing_prerequisite_identity_is_explicit(self):
        a, b = self.rows[:2]
        self.assertEqual(self.reserve(a, 200), 3)
        self.register(a, 200, 3)
        self.assertEqual(self.reserve(b, 201), 3)
        self.register(b, 201, 3)
        self.assertEqual(self.reserve(a, 202, holder='110', commit='d' * 40), 4)
        self.register(a, 202, 4, commit='d' * 40)
        self.assertEqual(self.reserve(b, 203, holder='110', commit='d' * 40), 4)
        missing = self.rows[-1]
        path = self.root / 'debian/dists' / missing['suite'] / 'build.json'
        publication.write(path, {'targets': {}})
        self.save()
        self.assertEqual(self.reserve(missing, 204), 5)
        node = self.state['runs']['100']['nodes'][missing['id'] + '/mqttsuite']
        value = dict(tag='v1.0.0', commit='b' * 40, recipe=self.context['recipe_commit'],
                     dependencies={'snode.c': dict(source=None, revision=0)})
        self.assertEqual(node['source']['inputs'], hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest())
        return None

    def test_cross_root_arm_baselines_can_diverge_on_a_row_with_a_later_claim(self):
        a, b, c = self.rows[:3]
        for row in [b, c]:
            self.baseline(row, '3')
        self.save()
        self.assertEqual(self.reserve(b, 200, holder='110'), 3)
        self.register(b, 200, 3)
        self.assertEqual(self.reserve(a, 201), 4)
        self.register(a, 201, 4)
        self.assertEqual(self.reserve(c, 202), 3)
        self.register(c, 202, 3)
        self.baseline(a, '3')
        self.save()
        self.assertEqual(self.reserve(a, 203, holder='110'), 5)
        self.assertNotEqual(self.state['allocations']['200']['mqttsuite'], self.state['allocations']['203']['mqttsuite'])
        self.assertEqual(self.state['runs']['100']['nodes'][c['id'] + '/mqttsuite']['source']['inputs'],
                         self.state['runs']['110']['nodes'][a['id'] + '/mqttsuite']['source']['inputs'])
        return None

    def test_lagging_vector_and_interleavings_align_only_above_valid_claims(self):
        a, b, c = self.rows[:3]
        self.assertEqual(self.reserve(b, 200, commit='d' * 40), 3)
        self.register(b, 200, 3, commit='d' * 40)
        self.assertEqual(self.reserve(a, 201), 4)
        self.register(a, 201, 4)
        self.assertEqual(self.reserve(a, 202, holder='110', commit='d' * 40), 5)
        self.register(a, 202, 5, commit='d' * 40)
        self.assertEqual(self.reserve(c, 203), 4, 'Lagging V1 may reuse despite a later V2 counter')
        self.register(c, 203, 4)
        self.assertEqual(self.reserve(c, 204, holder='110', commit='d' * 40), 5)
        self.assertEqual(self.reserve(a, 205), 6, 'Moving back cannot reuse below the row claim')
        return None

    def test_published_claim_and_unrelated_rows_and_projects_remain_protected(self):
        a, b = self.rows[:2]
        self.reserve(a, 200)
        before = copy.deepcopy(self.state['runs']['100']['nodes'][a['id'] + '/mqttsuite'])
        info, directory = publication.published(self.root, b)
        info['releases']['mqttsuite'] = {'v1.0.0': dict(revision='7', sources={'mqttsuite': self.sources['mqttsuite']},
            versions={'mqttsuite': repository.package_version(b, '1.0.0', '7')}, context=dict(build_project='mqttsuite'))}
        self.assertEqual(repository.project_revision(repository.release_view(info, 'mqttsuite', 'v1.0.0'), 'mqttsuite'), 7)
        path = self.root / directory / 'build.json'
        manifest = publication.read(path)
        manifest['targets'][b['arch']] = info
        publication.write(path, manifest)
        self.state['counters']['mqttsuite'] = 7
        counters = copy.deepcopy(self.state['counters'])
        self.save()
        self.assertEqual(self.reserve(b, 201), 8)
        self.assertEqual(self.state['runs']['100']['nodes'][a['id'] + '/mqttsuite'], before)
        self.assertEqual({p: v for p, v in self.state['counters'].items() if p != 'mqttsuite'},
                         {p: v for p, v in counters.items() if p != 'mqttsuite'})
        return None

    def test_two_real_shell_cas_reservations_share_and_replay_does_not_commit(self):
        first = self.intent(self.rows[0], 200)
        second = self.intent(self.rows[1], 201, holder='110')
        command = ['bash', str(repository.ROOT / 'ci/publish/status.sh'), str(self.root), 'reserve']
        # Separate file-Git metadata writers, as the existing CAS fixture does.
        writers = []
        for i in range(2):
            writer = self.base / ('cas-writer-' + str(i))
            self.git('clone', str(self.remote), str(writer))
            writers.append(writer)
        processes = [subprocess.Popen(command[:2] + [str(writer), 'reserve'], env=os.environ | env,
                      cwd=repository.ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for writer, env in zip(writers, [first, second])]
        results = [process.communicate(timeout=90) for process in processes]
        for process, (out, err) in zip(processes, results):
            self.assertEqual(process.returncode, 0, (out + err).decode())
        state = json.loads(self.git('show', 'main:status.json', cwd=self.remote))
        self.assertEqual([state['allocations'][str(n)]['mqttsuite'] for n in [200, 201]], ['3', '3'])
        self.assertEqual(state['counters']['mqttsuite'], 3)
        before = self.git('rev-parse', 'main', cwd=self.remote)
        subprocess.run(command[:2] + [str(writers[0]), 'reserve'], env=os.environ | first,
                       cwd=repository.ROOT, check=True, capture_output=True)
        self.assertEqual(self.git('rev-parse', 'main', cwd=self.remote), before)
        workflow = (repository.ROOT / '.github/workflows/orchestrate-packages.yml').read_text()
        self.assertIn('group: package-release-${{', workflow)
        return None


class DeploymentAlignmentTest(deployments.DeploymentTest):
    # Do not inherit and rerun the existing two-deployment acceptance test here.
    test_snodec_first_deployment_and_independent_non_cmake_deployment = None

    def test_real_two_architecture_diamond_aligns_each_level_and_replays_without_feed_write(self):
        names = ('engine', 'client', 'plugin', 'bundle')
        with self.deployment('AlignmentOrg', 'Control', 'Feed', names, ('amd64', 'arm64')):
            for project in names:
                self.notify(project, 'v1.0.0', self.tag(project, 'v1.0.0'))
                self.drain()
            start = len(self.posts)
            root_sha = self.tag('engine', 'v1.0.0', 'moved framework')
            self.notify('engine', 'v1.0.0', root_sha)
            self.drain()
            wave = self.posts[start:]
            for project in names[1:]:
                selected = [(n, r) for n, _, k, r in wave if k == 'capture' and r['project'] == project]
                self.assertEqual(len(selected), 2)
                revisions = []
                for number, request in selected:
                    bundle = self.bundles[str(number)]
                    context = publication.read(bundle / 'context.json')
                    targets = publication.read(bundle / 'targets.json')
                    profile = publication.read(bundle / 'profiles.json')[request['target']]
                    self.assertEqual([r['id'] for r in targets], [request['target']])
                    self.assertEqual(profile['context']['source_tags'][project], 'v1.0.0')
                    self.assertEqual(context['packages_commit'], self.git('rev-parse', context['packages_commit'], cwd=self.root))
                    revisions.append(publication.read(bundle / 'revisions.json')[project])
                self.assertEqual(revisions, ['2', '2'])
                self.assertEqual(len([1 for _, _, k, r in wave if k == 'build' and r['project'] == project]), 2)
                self.assertEqual(len([1 for _, _, k, r in wave if k == 'publish' and r['project'] == project]), 2)
            state = publication.read(self.root / 'status.json')
            for row in repository.rows(self.graph['bundle']):
                info = publication.published(self.root, row)[0]
                for project in names:
                    release = info['releases'][project]['v1.0.0']
                    self.assertEqual(release['revision'], '2')
                    capture = release['publications'][project]['capture']
                    node = state['runs'][capture]['nodes'][row['id'] + '/' + project]
                    self.assertEqual(node['dependencies'], repository.binding(info, node.get('requires', [])))
                self.assertEqual(repository.source_commit(info['sources']['engine']), root_sha)
            pages = self.pages()
            self.assertNotIn(b'1.0.0 \xc2\xb7 r', pages['status/bundle.md'])
            final = next((n, r) for n, _, k, r in reversed(wave) if k == 'publish' and r['project'] == 'bundle')
            before = self.git('rev-parse', 'stable', cwd=self.base / 'feed.git')
            self.publish(final[0], final[1], self.bundles[final[1]['capture']])
            self.assertEqual(self.git('rev-parse', 'stable', cwd=self.base / 'feed.git'), before)
        return None

    def test_five_prepare_created_rows_from_two_roots_share_exact_provenance(self):
        names = ('engine', 'client', 'plugin', 'bundle')
        with self.deployment('CaptureOrg', 'Control', 'Feed', names, ('amd64', 'arm64', 'armhf', 'riscv64')):
            self.graph['plugin']['depends_on'] = []
            self.graph['client']['depends_on'] = ['engine', 'plugin']
            for config in self.graph.values():
                config['matrix']['linux'].append(dict(distribution='debian', suite='forky', image='debian:forky', architectures=['amd64']))
            direct, _ = self.notify('client', 'v1.0.0', self.tag('client', 'v1.0.0'))
            self.drain()
            holders = {}
            for project in ['engine', 'plugin']:
                holders[project], _ = self.notify(project, 'v1.0.0', self.tag(project, 'v1.0.0'))
            state = publication.read(self.root / 'status.json')
            requests = copy.deepcopy(state['requests'])
            all_rows = repository.rows(self.graph['client'])
            for i, row in enumerate(all_rows):
                # Synthetic feed facts isolate the real capture boundary from package compilation.
                sources = {p: {'refs/tags/v1.0.0': state['requests'][p]['v1.0.0']['sha']} for p in holders}
                info = support.feed_manifest(dict(sources=sources,
                    versions={p: repository.package_version(row, '1.0.0', '1') for p in holders},
                    files={f'{p}_1.0.0-1_{row["arch"]}.deb': row['id'] + p for p in holders},
                    publications={p: dict(capture=capture, revision='1', published_at='2026-10-21T00:00:00Z',
                        job_url=f'https://github.com/{self.owner}/{p}/actions/runs/1/job/1') for p, capture in holders.items()}), repository.PROJECTS)
                path = self.root / 'debian/dists' / row['suite'] / 'build.json'
                manifest = publication.read(path, {'targets': {}})
                manifest['targets'][row['arch']] = info
                publication.write(path, manifest)
                for project, holder in holders.items():
                    state['runs'][holder].setdefault('nodes', {})[row['id'] + '/' + project] = dict(status='published')
                if i % 2:
                    state['runs'][holders['engine']]['nodes'][row['id'] + '/client'] = dict(status='superseded', cause='dependent')
            publication.write(self.root / 'status.json', state)
            self.commit()
            with patch.dict(os.environ, GITHUB_WORKFLOW_REF=self.coordinator + '/.github/workflows/control-packages.yml@refs/heads/control'):
                dispatch.tick(self.root, self.bundles)
            captures = [(n, r) for n, _, k, r in self.posts if k == 'capture']
            self.assertEqual(len(captures), 5)
            self.assertEqual({r['capture'] for _, r in captures}, set(holders.values()))
            expected = set()
            for number, request in captures:
                self.capture(request, number)
                bundle = self.bundles[str(number)]
                context = publication.read(bundle / 'context.json')
                row = publication.read(bundle / 'targets.json')[0]
                profile = publication.read(bundle / 'profiles.json')[row['id']]
                revisions = publication.read(bundle / 'revisions.json')
                self.assertEqual(revisions, {'client': '2'})
                self.assertEqual(context['run_id'], str(number))
                self.assertEqual(profile['context']['source_tags']['client'], 'v1.0.0')
                selected_sha = repository.source_commit(profile['sources']['client'])
                self.assertEqual(selected_sha, state['requests']['client']['v1.0.0']['sha'])
                self.assertEqual(profile['projects']['client']['_commit'], selected_sha)
                definition = self.content('client', 'ci/packages.json', selected_sha)
                self.assertEqual(profile['projects']['client']['_digest'], hashlib.sha256(definition).hexdigest())
                value = dict(tag='v1.0.0', commit=selected_sha, recipe=context['recipe_commit'],
                    dependencies={p: dict(source=profile['baseline']['releases'][p]['v1.0.0']['sources'][p], revision=1) for p in holders})
                digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
                expected.add(digest)
                current = publication.read(self.root / 'status.json')
                held = current['runs'][request['capture']]['nodes'][row['id'] + '/client']
                self.assertEqual(held['source'], dict(run=number, attempt=1, inputs=digest))
                self.assertEqual(current['runs'][str(number)]['profiles_hash'], repository.digest(bundle / 'profiles.json'))
                self.assertEqual(current['requests'], requests)
                self.assertEqual(context['packages_commit'], self.git('rev-parse', context['packages_commit'], cwd=self.root))
            self.assertEqual(len(expected), 1)
            self.assertEqual(publication.read(self.root / 'status.json')['counters']['client'], 2)
            pages = self.pages()
            self.assertIn('# client package status · latest release 1.0.0\n'.encode(), pages['status/client.md'])
            self.assertNotIn(b'1.0.0 \xc2\xb7 r', pages['status/client.md'])
            self.assertEqual(publication.read(self.root / 'status.json')['requests']['client']['v1.0.0']['capture'], direct)
        return None


class OpenWrtAlignmentTest(support.PinnedJsonCase):
    def test_shared_revision_publishes_independently_replays_and_rejects_conflicting_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            helper = controls.TrustedControlsTest()
            fixtures = []
            for arch, capture in [('x86_64', '100'), ('aarch64_generic', '101')]:
                folder = base / arch
                folder.mkdir()
                fixture = helper.fixture(folder, target='openwrt-24.10-' + arch)
                if fixtures:
                    fixture = (fixtures[0][0], *fixture[1:])
                fixture[4]['run_id'] = capture
                receipt = dict(capture=capture, source=dict(run=int(capture) + 100, attempt=1), job=int(capture) + 200,
                               artifact=dict(id=int(capture) + 300, digest='sha256:' + 'a' * 64))
                with patch.dict(os.environ, BUILD_RECEIPT=json.dumps(receipt)):
                    helper.publish(fixture)
                fixtures.append(fixture)
            root = fixtures[0][0]
            for fixture in fixtures:
                row = fixture[3]
                directory = root / publication.feed_paths(row)[0]
                info = publication.read(directory / 'build.json')
                self.assertEqual(info['revision'], '2')
                self.assertEqual(info['versions']['snode.c'], '1.0.0-r2')
                self.assertIn('Architecture: ' + row['arch'], (directory / 'Packages').read_text())
                self.assertEqual(info['publications']['snode.c']['capture'], fixture[4]['run_id'])
            first = fixtures[0]
            receipt = publication.read(root / publication.feed_paths(first[3])[0] / 'build.json')['publications']['snode.c']
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            sign = unittest.mock.Mock()
            with patch.dict(os.environ, BUILD_RECEIPT=json.dumps(receipt)):
                helper.publish(first, on_sign=sign)
                sign.assert_not_called()
                self.assertEqual({str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)
                directory = first[-1]
                package = next(directory.glob('*.ipk'))
                support.ipk(package, 'snodec', '1.0.0-r2', 'x86_64')
                with package.open('ab') as stream:
                    stream.write(b'different bytes')
                metadata = publication.read(directory / 'build.json')
                metadata['files'][package.name] = repository.digest(package)
                publication.write(directory / 'build.json', metadata)
                with self.assertRaisesRegex(RuntimeError, 'Different package content under the same publication identity'):
                    helper.publish(first, on_sign=sign)
                sign.assert_not_called()
                self.assertEqual({str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)
        return None
