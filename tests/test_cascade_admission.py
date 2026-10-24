"""Row ownership and overlapping cascades at the coordinator's public boundary."""
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from ci import dispatch, repository
from ci.publish import publication
from support import CoordinatorCase
import test_corrective_revision2 as corrections
import test_deployments as deployments


class CascadeAdmissionTest(CoordinatorCase):
    def test_row_only_child_does_not_supersede_another_row(self):
        self.feed(['snode.c'], capture='previous', revision='1')
        self.state['runs']['100']['nodes'] = {
            self.row['id'] + '/snode.c': dict(status='skipped', category='excluded')}
        self.save()
        self.add_capture('mqttsuite', '200', revision='2')
        other = next(r for r in repository.rows(self.graph['mqttsuite']) if r['id'] == 'debian-trixie-arm64')
        generation = self.state['runs']['200']
        generation['targets'].append(other)
        generation['sources'][other['id']] = copy.deepcopy(generation['sources'][self.row['id']])
        profiles = publication.read(self.bundles['200'] / 'profiles.json')
        profiles[other['id']] = copy.deepcopy(profiles[self.row['id']])
        for name, value in [('targets', generation['targets']), ('sources', generation['sources']), ('profiles', profiles)]:
            publication.write(self.bundles['200'] / (name + '.json'), value)
        generation['profiles_hash'] = repository.digest(self.bundles['200'] / 'profiles.json')
        info = publication.read(self.root / 'debian/dists/trixie/build.json')
        info['targets']['arm64'] = copy.deepcopy(info['targets']['amd64'])
        publication.write(self.root / 'debian/dists/trixie/build.json', info)
        self.save()
        self.add_capture('mqttsuite', '201', revision='3', cause='dependent', cascade='100')
        self.state['runs']['201']['nodes'] = {
            self.row['id'] + '/mqttsuite': dict(status='failed', category='deterministic', reason='Child failed')}
        self.save()
        with patch.object(dispatch, 'capacity', return_value=(0, {})):
            self.tick()
            self.tick()
        pushed = json.loads(self.git('show', 'main:status.json', cwd=self.remote))
        node = pushed['runs']['200']['nodes'][other['id'] + '/mqttsuite']
        self.assertEqual(node['status'], 'pending')
        self.assertNotIn('category', node)
        self.assertEqual(node.get('builds', 0), 0)
        self.assertEqual(pushed['runs']['201']['targets'], [self.row])
        self.assertEqual(self.posts, [])
        return None

    def test_cascade_reservation_preserves_the_verified_direct_request(self):
        self.feed(['snode.c'])
        self.tick()
        request = next(json.loads(p['inputs']['request']) for _, p in self.posts
                       if json.loads(p['inputs']['request'])['project'] == 'mqttsuite')
        before = copy.deepcopy(self.state['requests']['mqttsuite'])
        capture = str(self.node('mqttsuite')['source']['run'])
        with patch.dict(os.environ, RELEASE_PARENT=json.dumps(request), RELEASE_TAG='v1.0.0', RELEASE_SHA='b' * 40,
                        RELEASE_REQUESTED_AT='', RELEASE_RUN='0', RELEASE_PROJECT='mqttsuite', GITHUB_RUN_ID=capture,
                        GITHUB_RUN_ATTEMPT='1', GITHUB_WORKFLOW_REF=dispatch.COORDINATOR +
                        '/.github/workflows/orchestrate-packages.yml@refs/heads/main'):
            repository.run('bash', str(repository.ROOT / 'ci/publish/status.sh'), str(self.root), 'reserve')
        pushed = json.loads(self.git('show', 'main:status.json', cwd=self.remote))
        self.assertEqual(pushed['requests']['mqttsuite'], before)
        self.assertEqual(pushed['runs']['100']['nodes'][self.row['id'] + '/mqttsuite']['source']['run'], int(capture))
        self.assertIn('mqttsuite', pushed['allocations'][capture])
        return None

    def test_deterministic_failure_keeps_its_reason_and_budgets_after_a_dependency_change(self):
        info = corrections.CorrectiveRevision2Test.application_fixture(self, dict(
            status='failed', category='deterministic', reason='Original failure', builds=2, publications=1))
        info['releases']['snode.c']['v1.0.0']['files']['snodec_1_amd64.deb'] = '3' * 64
        publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
        self.save()
        self.tick()
        node = self.node('mqttsuite')
        self.assertEqual((node['status'], node.get('category'), node.get('reason')),
                         ('failed', 'deterministic', 'Original failure'))
        self.assertEqual((node['builds'], node['publications']), (2, 1))
        self.assertEqual(self.posts, [])
        return None

    def test_failed_unregistered_capture_lifts_deferral_without_superseding_old_work(self):
        self.feed(['snode.c'], capture='previous', revision='1')
        self.state['runs']['100']['nodes'] = {
            self.row['id'] + '/snode.c': dict(status='skipped', category='excluded')}
        self.save()
        self.add_capture('mqttsuite', '200', revision='2')
        self.state['requests']['mqttsuite']['v1.0.0'].update(
            capture='300', revision='3', eligible=True, definition=self.graph['mqttsuite'])
        self.runs[dispatch.COORDINATOR, 300] = dict(event='workflow_dispatch', status='in_progress',
            path='.github/workflows/orchestrate-packages.yml', head_repository={'full_name': dispatch.COORDINATOR})
        self.save()
        self.tick()
        self.assertEqual(self.node('mqttsuite', '200')['status'], 'pending')
        self.assertNotIn('request', self.node('mqttsuite', '200'))
        self.assertEqual(self.posts, [])
        self.runs[dispatch.COORDINATOR, 300]['status'] = 'completed'
        self.tick()
        self.state = publication.read(self.root / 'status.json')
        self.assertFalse(self.state['requests']['mqttsuite']['v1.0.0']['eligible'])
        node = self.node('mqttsuite', '200')
        self.assertEqual((node['status'], node['builds'], node['request']['capture']), ('pending', 1, '200'))
        self.assertEqual([json.loads(p['inputs']['request'])['capture'] for _, p in self.posts], ['200'])
        return None

    def test_same_version_revision_order_survives_a_higher_semantic_version(self):
        self.feed(['snode.c'], capture='previous', revision='1')
        self.state['runs']['100']['nodes'] = {
            self.row['id'] + '/snode.c': dict(status='skipped', category='excluded')}
        self.save()
        self.add_capture('mqttsuite', '200', revision='10')
        self.add_capture('mqttsuite', '201', revision='11')
        self.add_capture('mqttsuite', '202', revision='9')
        high = self.state['runs']['202']
        high['context']['tag'] = 'v2.0.0'
        high['sources'][self.row['id']]['mqttsuite'] = {'refs/tags/v2.0.0': 'e' * 40}
        profile = publication.read(self.bundles['202'] / 'profiles.json')
        profile[self.row['id']]['sources']['mqttsuite'] = {'refs/tags/v2.0.0': 'e' * 40}
        for name, value in [('context', high['context']), ('sources', high['sources']), ('profiles', profile)]:
            publication.write(self.bundles['202'] / (name + '.json'), value)
        high['profiles_hash'] = repository.digest(self.bundles['202'] / 'profiles.json')
        self.save()
        with patch.object(dispatch, 'capacity', return_value=(0, {})):
            self.tick()
        self.assertEqual(self.node('mqttsuite', '200')['status'], 'superseded')
        self.assertEqual(self.node('mqttsuite', '201')['status'], 'pending')
        self.assertEqual(self.node('mqttsuite', '202')['status'], 'pending')
        self.assertEqual(self.posts, [])
        return None

    def test_late_callback_cannot_revive_excluded_work_but_operator_retry_can(self):
        self.tick()
        node = self.node()
        node.update(status='superseded', category='excluded', reason='Newer revision owns row', waiting=False)
        self.state['runs']['100']['nodes'][self.row['id'] + '/snode.c'] = node
        self.save()
        request = dict(node['request'], attempt=2, artifact={'id': 1234, 'digest': 'sha256:' + 'a' * 64})
        receipt = dict(source=dict(run=node['source']['run'], attempt=2), job=44, job_url='real-job')
        with patch.object(dispatch, 'receive', return_value={'receipt': json.dumps(receipt)}):
            dispatch.apply_report(self.root, request, self.bundle)
        self.assertEqual(self.node(), node)
        dispatch.transaction(self.root, dict(retry='100/snode.c/' + self.row['id']))
        retried = self.node()
        self.assertEqual(retried['status'], 'pending')
        self.assertNotIn('category', retried)
        self.assertEqual(retried['builds'], 0)
        self.assertFalse(retried['waiting'])
        return None

    def diamond(self, published_arm_current=True, selected_status='running'):
        """Synthetic control fixture; the deployment tests cover prepare-created contexts."""
        self.graph['join'] = dict(copy.deepcopy(self.graph['mqttsuite']), package='join', title='Join',
                                  depends_on=['mqttsuite', 'snode.c-idp'], _commit='d' * 40)
        self.sources['join'] = {'refs/tags/v1.0.0': 'd' * 40}
        repository.PROJECTS.update(self.graph)
        master = self.base / 'master.json'
        publication.write(master, dict(repositories=list(self.graph)))
        publication.write(self.base / 'definitions.json', dict(projects=self.graph))
        for context in [patch.dict(os.environ, CI_MASTER=str(master)),
                        patch.object(repository, 'REPOSITORIES', tuple(self.graph)),
                        patch.object(dispatch, 'REPOSITORIES', tuple(self.graph)),
                        patch.object(publication, 'REPOSITORIES', tuple(self.graph)),
                        patch.object(dispatch, 'observe', side_effect=lambda node, project, row: node)]:
            context.start()
            self.addCleanup(context.stop)
        self.feed(['snode.c', 'mqttsuite', 'snode.c-idp'], capture='100', revision='2')
        self.state['runs']['100']['context'].update(cascade='100', cause='release')
        self.state['runs']['100']['nodes'] = {
            self.row['id'] + '/' + p: dict(status='superseded', reason='Capture handed off')
            for p in ('mqttsuite', 'snode.c-idp')}
        self.save()
        for project, capture in [('mqttsuite', '201'), ('snode.c-idp', '301')]:
            self.add_capture(project, capture, revision='2')
        self.add_capture('snode.c-idp', '302', revision='3', cause='dependent', cascade='100')
        selected = self.state['runs']['302']
        selected['context']['tag'] = 'v2.0.0'
        selected['sources'][self.row['id']]['snode.c-idp'] = {'refs/tags/v2.0.0': 'e' * 40}
        profiles = publication.read(self.bundles['302'] / 'profiles.json')
        profiles[self.row['id']]['sources']['snode.c-idp'] = {'refs/tags/v2.0.0': 'e' * 40}
        profiles[self.row['id']]['projects']['snode.c-idp']['_commit'] = 'e' * 40
        for name, value in [('sources', selected['sources']), ('context', selected['context']), ('profiles', profiles)]:
            publication.write(self.bundles['302'] / (name + '.json'), value)
        selected['profiles_hash'] = repository.digest(self.bundles['302'] / 'profiles.json')
        self.contents['SNodeC/snode.c-idp', 'e' * 40, 'ci/packages.json'] = json.dumps(
            {k: v for k, v in self.graph['snode.c-idp'].items() if not k.startswith('_')}).encode()
        info = publication.published(self.root, self.row)[0]
        old = copy.deepcopy(info)
        old['releases']['snode.c']['v1.0.0']['revision'] = '1'
        for project, capture in [('snode.c', '100'), ('mqttsuite', '201'), ('snode.c-idp', '301')]:
            info['publications'][project]['capture'] = capture
            info['releases'][project]['v1.0.0']['publications'][project]['capture'] = capture
            required = list(repository.dependencies(project, self.graph))
            baseline = old if project == 'snode.c-idp' and not published_arm_current else info
            self.state['runs'][capture].setdefault('nodes', {})[self.row['id'] + '/' + project] = dict(
                status='published', requires=required, dependencies=repository.binding(baseline, required))
        selected['nodes'] = {self.row['id'] + '/snode.c-idp': dict(
            status=selected_status, category='deterministic' if selected_status == 'failed' else 'execution',
            reason='Selected v2 arm', requires=['snode.c'], dependencies=repository.binding(info, ['snode.c']),
            builds=1, publications=0, source=dict(run=800, attempt=1), waiting=False,
            request=dict(kind='build', capture='302', project='snode.c-idp', target=self.row['id'], intent='arm-v2'))}
        publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
        self.state['requests']['join'] = {'v1.0.0': dict(definition=self.graph['join'], capture='100', revision='2')}
        self.save()
        return info

    def test_overlapping_root_waits_for_the_stale_other_arm(self):
        self.diamond(published_arm_current=False)
        for _ in range(3):
            self.tick()
        requests = [json.loads(p['inputs']['request']) for _, p in self.posts]
        self.assertEqual([r for r in requests if r['project'] == 'join'], [])
        self.assertEqual(self.node('snode.c-idp', '302')['builds'], 1)
        self.assertEqual(self.node('snode.c-idp', '302')['status'], 'running')
        return None

    def test_current_older_publication_does_not_discharge_selected_higher_arm(self):
        self.diamond()
        for _ in range(3):
            self.tick()
        requests = [json.loads(p['inputs']['request']) for _, p in self.posts]
        self.assertEqual([r for r in requests if r['project'] == 'join'], [])
        self.assertEqual(repository.source_tag(publication.published(self.root, self.row)[0], 'snode.c-idp'), 'v1.0.0')
        self.assertEqual(self.node('snode.c-idp', '302')['status'], 'running')
        self.assertEqual(self.node('snode.c-idp', '302')['builds'], 1)
        return None

    def test_failed_selected_higher_arm_does_not_admit_the_join(self):
        self.diamond(selected_status='failed')
        self.tick()
        requests = [json.loads(p['inputs']['request']) for _, p in self.posts]
        self.assertEqual([r for r in requests if r['project'] == 'join'], [])
        node = self.node('snode.c-idp', '302')
        self.assertEqual((node['status'], node['reason'], node['builds']), ('failed', 'Selected v2 arm', 1))
        return None

    def publish_selected_arm(self):
        info = publication.published(self.root, self.row)[0]
        arm = copy.deepcopy(info['releases']['snode.c-idp']['v1.0.0'])
        arm.update(sources={'snode.c-idp': {'refs/tags/v2.0.0': 'e' * 40}}, revision='3')
        arm['context'].update(source_tags={'snode.c-idp': 'v2.0.0'}, versions={'snode.c-idp': '2.0.0'})
        arm['publications']['snode.c-idp'].update(capture='302', revision='3')
        info['releases']['snode.c-idp']['v2.0.0'] = arm
        info['sources']['snode.c-idp'] = arm['sources']['snode.c-idp']
        info['publications']['snode.c-idp'] = arm['publications']['snode.c-idp']
        publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
        self.state = publication.read(self.root / 'status.json')
        self.state['runs']['302']['nodes'][self.row['id'] + '/snode.c-idp'].update(status='published', waiting=False)
        self.save()
        return info

    def test_outside_lineage_arm_publication_admits_exactly_one_join_then_one_child_build(self):
        self.diamond(published_arm_current=False)
        self.tick()
        self.assertEqual(self.posts, [])
        info = self.publish_selected_arm()
        self.state['runs'] = dict(reversed(list(self.state['runs'].items())))
        self.save()
        for _ in range(3):
            self.tick()
        requests = [json.loads(p['inputs']['request']) for _, p in self.posts]
        self.assertEqual([(r['project'], r['kind']) for r in requests], [('join', 'capture')])
        parent = requests[0]['capture']
        self.state = publication.read(self.root / 'status.json')
        self.state['runs'][parent]['nodes'][self.row['id'] + '/join'].update(status='superseded', waiting=False)
        self.save()
        self.add_capture('join', '400', revision='3', cause='dependent', cascade='100')
        self.tick()
        self.tick()
        requests = [json.loads(p['inputs']['request']) for _, p in self.posts]
        self.assertEqual([(r['project'], r['kind']) for r in requests], [('join', 'capture'), ('join', 'build')])
        node = self.node('join', '400')
        self.assertEqual(node['dependencies'], repository.binding(info, node['requires']))
        self.assertEqual(node['builds'], 1)
        self.assertEqual(node.get('publications', 0), 0)
        self.assertEqual(requests[-1]['capture'], '400')
        self.assertEqual(self.state['runs']['400']['sources'][self.row['id']]['join'], self.sources['join'])
        return None

    def test_captured_child_waits_for_all_selected_arms_and_closes_when_the_arm_fails(self):
        self.diamond()
        self.add_capture('join', '400', revision='3', cause='dependent', cascade='100')
        self.tick()
        node = self.node('join', '400')
        self.assertEqual(node['status'], 'pending')
        self.assertNotIn('request', node)
        self.assertEqual(self.posts, [])
        self.state['runs']['302']['nodes'][self.row['id'] + '/snode.c-idp'].update(status='failed', category='deterministic')
        self.save()
        self.tick()
        node = self.node('join', '400')
        self.assertEqual((node['status'], node['category']), ('unsatisfiable', 'blocked'))
        self.assertIn('snode.c-idp', node['reason'])
        self.assertIn('retry', node['reason'])
        self.assertEqual(node['dependencies'], repository.binding(publication.published(self.root, self.row)[0], node['requires']))
        self.assertEqual(self.posts, [])
        blocked = copy.deepcopy(node)
        dispatch.transaction(self.root, dict(retry='302/snode.c-idp/' + self.row['id']))
        self.publish_selected_arm()
        for _ in range(3):
            self.tick()
        self.assertEqual(self.node('join', '400'), blocked)
        requests = [json.loads(p['inputs']['request']) for _, p in self.posts]
        self.assertEqual([(r['project'], r['kind']) for r in requests], [('join', 'capture')])
        return None

    def test_new_publication_recovers_highest_failure_by_fresh_capture_without_resetting_old_node(self):
        self.diamond(selected_status='failed')
        old = copy.deepcopy(self.node('snode.c-idp', '302'))
        self.add_capture('snode.c', '110', revision='3')
        info = publication.published(self.root, self.row)[0]
        info['publications']['snode.c'].update(capture='110', revision='3')
        release = info['releases']['snode.c']['v1.0.0']
        release['publications']['snode.c'].update(capture='110', revision='3')
        release['revision'] = '3'
        publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
        self.save()
        for _ in range(3):
            self.tick()
        requests = [json.loads(p['inputs']['request']) for _, p in self.posts]
        self.assertEqual(len([r for r in requests if r['project'] == 'snode.c-idp']), 1)
        self.assertTrue(all(r['kind'] == 'capture' for r in requests))
        self.assertEqual(self.node('snode.c-idp', '302'), old)
        self.assertEqual([r for r in requests if r['project'] == 'join'], [])
        return None

    def test_terminal_failure_categories_never_reset_on_binding_changes(self):
        for category in ('configuration', 'expiry', 'deterministic'):
            with self.subTest(category=category):
                info = corrections.CorrectiveRevision2Test.application_fixture(self, dict(
                    status='failed', category=category, reason='Original operator action required', builds=3, publications=3))
                info['releases']['snode.c']['v1.0.0']['files']['snodec_1_amd64.deb'] = '3' * 64
                publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
                self.save()
                for _ in range(3):
                    self.tick()
                node = self.node('mqttsuite')
                self.assertEqual((node['status'], node.get('category'), node.get('reason')),
                                 ('failed', category, 'Original operator action required'))
                self.assertEqual((node['builds'], node['publications']), (3, 3))
                self.assertEqual(self.posts, [])
        return None

    def test_failed_capture_is_settled_for_other_roots_on_the_same_baseline(self):
        self.diamond()
        info = self.publish_selected_arm()
        required = list(repository.dependencies('join', self.graph))
        self.state['runs']['100']['nodes'][self.row['id'] + '/join'] = dict(
            status='failed', cause='dependent', category='configuration', reason='Bad highest tag',
            requires=required, dependencies=repository.binding(info, required), builds=1, publications=0, waiting=False,
            request=dict(kind='capture', intent='failed-child'))
        self.save()
        for _ in range(3):
            self.tick()
        node = self.node('join')
        self.assertEqual((node['status'], node['reason'], node['builds']), ('failed', 'Bad highest tag', 1))
        self.assertEqual([json.loads(p['inputs']['request']) for _, p in self.posts], [])
        return None



    def test_captured_join_waits_for_replacement_arms_then_builds_its_own_pinned_source(self):
        self.diamond()
        # Construct a single-version starting graph; the separate higher-arm tests
        # retain and test the v2 generation. No production ledger is pruned.
        self.state['runs'].pop('302')
        self.save()
        self.add_capture('join', '400', revision='3', cause='dependent', cascade='100')
        selected = copy.deepcopy(self.state['runs']['400']['sources'][self.row['id']]['join'])
        self.add_capture('snode.c', '110', revision='3')
        info = publication.published(self.root, self.row)[0]
        info['publications']['snode.c'].update(capture='110', revision='3')
        own = info['releases']['snode.c']['v1.0.0']
        own['revision'] = '3'
        own['publications']['snode.c'].update(capture='110', revision='3')
        publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
        self.save()
        for _ in range(3):
            self.tick()
        requests = [json.loads(p['inputs']['request']) for _, p in self.posts]
        self.assertEqual(sorted((r['project'], r['kind']) for r in requests),
                         [('mqttsuite', 'capture'), ('snode.c-idp', 'capture')])
        self.assertEqual(self.node('join', '400')['status'], 'pending')
        self.assertNotIn('request', self.node('join', '400'))
        self.state = publication.read(self.root / 'status.json')
        for project in ('mqttsuite', 'snode.c-idp'):
            self.state['runs']['110']['nodes'][self.row['id'] + '/' + project].update(status='superseded', waiting=False)
        self.save()
        for project, capture in [('mqttsuite', '211'), ('snode.c-idp', '311')]:
            self.add_capture(project, capture, revision='3', cause='dependent', cascade='110')
        for project, capture in [('mqttsuite', '211'), ('snode.c-idp', '311')]:
            info['publications'][project].update(capture=capture, revision='3')
            own = info['releases'][project]['v1.0.0']
            own['revision'] = '3'
            own['publications'][project].update(capture=capture, revision='3')
            self.state['runs'][capture]['nodes'] = {self.row['id'] + '/' + project: dict(
                status='published', requires=['snode.c'], dependencies=repository.binding(info, ['snode.c']))}
        publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
        self.save()
        for _ in range(3):
            self.tick()
        requests = [json.loads(p['inputs']['request']) for _, p in self.posts]
        self.assertEqual([(r['capture'], r['kind']) for r in requests if r['project'] == 'join'], [('400', 'build')])
        node = self.node('join', '400')
        self.assertEqual((node['status'], node['builds'], node.get('publications', 0)), ('pending', 1, 0))
        self.assertEqual(node['dependencies'], repository.binding(info, node['requires']))
        self.assertEqual(self.state['runs']['400']['sources'][self.row['id']]['join'], selected)
        return None


class ActivationAdmissionTest(unittest.TestCase):
    def test_real_activation_and_older_prerequisite_do_not_create_extra_cascades(self):
        fixture = deployments.DeploymentTest()
        with fixture.deployment('SNodeC', 'DistributionPackages', 'Packages',
                                ('snode.c', 'mqttsuite', 'snode.c-idp', 'join')):
            fixture.notify('snode.c', 'v1.0.0', fixture.tag('snode.c', 'v1.0.0'))
            fixture.drain()
            start = len(fixture.posts)
            direct, _ = fixture.notify('mqttsuite', 'v2.0.0', fixture.tag('mqttsuite', 'v2.0.0'))
            fixture.drain()
            work = fixture.posts[start:]
            high = publication.published(fixture.root, fixture.row)[0]['releases']['mqttsuite']['v2.0.0']
            receipt = high['publications']['mqttsuite']
            with self.subTest('own tag activates exactly its direct capture'):
                self.assertEqual([r for _, _, kind, r in work if kind == 'capture'], [])
                self.assertEqual([r['capture'] for _, _, kind, r in work if kind == 'build'], [direct])
                self.assertEqual(receipt['capture'], direct)
            start = len(fixture.posts)
            before = fixture.pages()
            content = fixture.base / 'authored-content'
            for name in ('site/docs', 'site/keys', 'install'):
                (content / name).mkdir(parents=True)
            (content / 'site/README.md').write_bytes((fixture.real_root / 'site/README.md').read_bytes())
            for config in fixture.graph.values():
                catalog = 'docs/catalogs/' + config['package'] + '.md'
                if (fixture.real_root / 'site' / catalog).exists():
                    path = content / 'site' / catalog
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('Retained authored catalog')
            (content / 'site/keys/README.md').write_text('Current authored key guide')
            (content / 'site/docs/guide.md').write_text('Guide changed after highest publication')
            with patch.dict(os.environ, PACKAGE_SITE=str(content / 'site')):
                fixture.notify('snode.c', 'v0.9.0', fixture.tag('snode.c', 'v0.9.0'))
                fixture.drain()
                self.assertEqual(fixture.pages(), before)
                self.assertEqual((fixture.root / 'docs/guide.md').read_text(), 'Guide changed after highest publication')
                self.assertEqual((fixture.root / 'keys/README.md').read_text(), 'Current authored key guide')
            with self.subTest('older prerequisite publication changes no dependent work or highest display'):
                self.assertEqual([r for _, _, _, r in fixture.posts[start:] if r['project'] == 'mqttsuite'], [])
                self.assertEqual(repository.source_tag(publication.published(fixture.root, fixture.row)[0], 'snode.c'), 'v1.0.0')
                self.assertEqual(fixture.pages(), before)
        return None

    def test_publication_rejects_an_unchanged_but_stale_prerequisite_arm(self):
        fixture = deployments.DeploymentTest()
        with fixture.deployment('ExampleOrg', 'ReleaseControl', 'Binaries', ('engine', 'client', 'plugin', 'bundle')):
            for project in ('engine', 'client', 'plugin', 'bundle'):
                fixture.notify(project, 'v1.0.0', fixture.tag(project, 'v1.0.0'))
                fixture.drain()
            capture, _ = fixture.notify('bundle', 'v1.1.0', fixture.tag('bundle', 'v1.1.0'))
            with patch.dict(os.environ, GITHUB_WORKFLOW_REF=fixture.coordinator + '/.github/workflows/control-packages.yml@refs/heads/control'):
                dispatch.tick(fixture.root, fixture.bundles)
            number, repo, kind, request = fixture.posts[-1]
            self.assertEqual(kind, 'build')
            fixture.build(number, repo, request, fixture.bundles[capture])
            fixture.runs[repo, number].update(status='completed', conclusion='success')
            with patch.dict(os.environ, GITHUB_WORKFLOW_REF=fixture.coordinator + '/.github/workflows/control-packages.yml@refs/heads/control'):
                dispatch.tick(fixture.root, fixture.bundles)
            publisher, _, kind, request = fixture.posts[-1]
            self.assertEqual(kind, 'publish')
            state = publication.read(fixture.root / 'status.json')
            node = state['runs'][capture]['nodes'][fixture.row['id'] + '/bundle']
            node['cause'] = 'dependent'
            info = publication.published(fixture.root, fixture.row)[0]
            arm = info['publications']['plugin']['capture']
            state['runs'][arm]['nodes'][fixture.row['id'] + '/plugin']['dependencies'] = 'stale binding'
            publication.write(fixture.root / 'status.json', state)
            fixture.commit()
            before = (fixture.root / 'debian/dists/trixie/build.json').read_bytes()
            with self.assertRaisesRegex(RuntimeError, 'prerequisite arm not current'):
                fixture.publish(publisher, request, fixture.bundles[capture])
            self.assertEqual((fixture.root / 'debian/dists/trixie/build.json').read_bytes(), before)
            self.assertEqual(node['source']['run'], number)
            self.assertEqual(node['publications'], 1)
        return None

    def test_prepare_created_multirow_work_is_not_superseded_on_an_omitted_row(self):
        fixture = deployments.DeploymentTest()
        with fixture.deployment('ExampleOrg', 'ReleaseControl', 'Binaries', ('engine', 'client', 'plugin', 'bundle'),
                                architectures=('amd64', 'arm64')):
            fixture.notify('engine', 'v1.0.0', fixture.tag('engine', 'v1.0.0'))
            fixture.drain()
            original, _ = fixture.notify('client', 'v1.0.0', fixture.tag('client', 'v1.0.0'))
            fixture.graph['client']['matrix']['linux'][0]['architectures'] = ['amd64']
            replacement, _ = fixture.notify('client', 'v1.0.0', fixture.tag('client', 'v1.0.0', 'narrowed matrix'))
            with patch.dict(os.environ, GITHUB_WORKFLOW_REF=fixture.coordinator + '/.github/workflows/control-packages.yml@refs/heads/control'):
                dispatch.tick(fixture.root, fixture.bundles)
            state = json.loads(fixture.git('show', 'stable:status.json', cwd=fixture.base / 'feed.git'))
            old = state['runs'][original]['nodes']
            self.assertEqual(old['debian-trixie-amd64/client']['status'], 'superseded')
            self.assertEqual(old['debian-trixie-arm64/client']['status'], 'pending')
            self.assertEqual(old['debian-trixie-arm64/client']['builds'], 1)
            self.assertEqual(state['runs'][replacement]['targets'][0]['id'], 'debian-trixie-amd64')
            self.assertEqual(len(state['runs'][replacement]['targets']), 1)
            self.assertEqual(sorted((r['capture'], r['target']) for _, _, k, r in fixture.posts
                                    if k == 'build' and r['project'] == 'client'),
                             sorted([(original, 'debian-trixie-arm64'), (replacement, 'debian-trixie-amd64')]))
        return None

    def test_real_overlapping_direct_root_waits_for_the_other_arm_and_joins_once(self):
        fixture = deployments.DeploymentTest()
        with fixture.deployment('ExampleOrg', 'ReleaseControl', 'Binaries', ('engine', 'client', 'plugin', 'bundle')):
            for project in ('engine', 'client', 'plugin', 'bundle'):
                fixture.notify(project, 'v1.0.0', fixture.tag(project, 'v1.0.0'))
                fixture.drain()
            start = len(fixture.posts)
            fixture.notify('engine', 'v1.0.0', fixture.tag('engine', 'v1.0.0', 'new framework baseline'))

            def advance_without_plugin_build():
                progress = True
                rounds = 0
                while progress and rounds < 20:
                    rounds += 1
                    with patch.dict(os.environ, GITHUB_WORKFLOW_REF=fixture.coordinator +
                                    '/.github/workflows/control-packages.yml@refs/heads/control'):
                        dispatch.tick(fixture.root, fixture.bundles)
                    pending = [p for p in fixture.posts if p[0] not in fixture.handled
                               and not (p[2] == 'build' and p[3]['project'] == 'plugin')]
                    progress = bool(pending)
                    for number, repo, kind, request in pending:
                        fixture.handled.add(number)
                        bundle = fixture.bundles[request['capture']]
                        if kind == 'capture':
                            fixture.capture(request, number)
                        elif kind == 'build':
                            fixture.build(number, repo, request, bundle)
                        else:
                            fixture.publish(number, request, bundle)
                        fixture.runs[repo, number].update(status='completed', conclusion='success')
                        fixture.jobs[repo, number][0].update(status='completed', conclusion='success')
                self.assertLess(rounds, 20)
                return None

            advance_without_plugin_build()
            self.assertEqual([r for _, _, _, r in fixture.posts[start:] if r['project'] == 'bundle'], [])
            direct, _ = fixture.notify('client', 'v1.0.0', fixture.tag('client', 'v1.0.0', 'outside-lineage direct arm'))
            advance_without_plugin_build()
            self.assertEqual([r for _, _, _, r in fixture.posts[start:] if r['project'] == 'bundle'], [])
            self.assertEqual(publication.published(fixture.root, fixture.row)[0]['publications']['client']['capture'], direct)
            fixture.drain()
            work = [(kind, r) for _, _, kind, r in fixture.posts[start:] if r['project'] == 'bundle']
            self.assertEqual([k for k, _ in work], ['capture', 'build', 'publish'])
            child = work[1][1]['capture']
            state = publication.read(fixture.root / 'status.json')
            node = state['runs'][child]['nodes'][fixture.row['id'] + '/bundle']
            self.assertEqual((node['status'], node['builds'], node['publications']), ('published', 1, 1))
            self.assertEqual(node['dependencies'], repository.binding(publication.published(fixture.root, fixture.row)[0], node['requires']))
            self.assertEqual(publication.published(fixture.root, fixture.row)[0]['publications']['bundle']['capture'], child)
            fixture.drain()
            self.assertEqual([(kind, r) for _, _, kind, r in fixture.posts[start:] if r['project'] == 'bundle'], work)
        return None

    def test_failed_first_application_activation_recovers_via_one_highest_capture(self):
        fixture = deployments.DeploymentTest()
        with fixture.deployment('ExampleOrg', 'ReleaseControl', 'Binaries', ('engine', 'client', 'plugin', 'bundle')):
            fixture.runtime.unlink()
            decoy = fixture.base / 'old-feed'
            publication.write(decoy / 'status.json', dict(repository='OldOrg/Packages', runs={'999999999': {}}, counters={'client': 999999}))
            publication.write(decoy / 'build.json', dict(sources={'retired-product': {'refs/heads/main': 'f' * 40}}))
            old_bytes = {str(p): p.read_bytes() for p in decoy.rglob('*') if p.is_file()}
            reads = []
            original_read = publication.read
            original_run = fixture.local_run

            def read(path, default=None):
                reads.append(str(path))
                self.assertFalse(Path(path).resolve().is_relative_to(decoy))
                return original_read(path, default)

            def run(*args, **kwargs):
                fixture.accesses.append(('command', list(args)))
                return original_run(*args, **kwargs)

            with patch.object(publication, 'read', side_effect=read), patch.object(dispatch, 'read', side_effect=read), \
                    patch.object(repository, 'run', side_effect=run):
                with patch.dict(os.environ, GITHUB_WORKFLOW_REF=fixture.coordinator + '/.github/workflows/control-packages.yml@refs/heads/control'):
                    self.assertFalse(dispatch.tick(fixture.root, fixture.bundles))
                source = fixture.tag('client', 'v2.0.0')
                failed, _ = fixture.notify('client', 'v2.0.0', source)
                fixture.drain()
                state = publication.read(fixture.root / 'status.json')
                old = copy.deepcopy(state['runs'][failed]['nodes'][fixture.row['id'] + '/client'])
                self.assertEqual((old['status'], old['category']), ('unsatisfiable', 'blocked'))
                self.assertIn('engine', old['reason'])
                self.assertEqual(state['requests']['client']['v2.0.0']['sha'], source)
                self.assertEqual(fixture.posts, [])
                fixture.notify('engine', 'v1.0.0', fixture.tag('engine', 'v1.0.0'))
                fixture.drain()
                work = [(k, r) for _, _, k, r in fixture.posts if r['project'] == 'client']
                self.assertEqual([k for k, _ in work], ['capture', 'build', 'publish'])
                child = work[1][1]['capture']
                state = publication.read(fixture.root / 'status.json')
                self.assertEqual(state['runs'][failed]['nodes'][fixture.row['id'] + '/client'], old)
                self.assertEqual(state['runs'][child]['sources'][fixture.row['id']]['client'], {'refs/tags/v2.0.0': source})
                self.assertEqual(state['runs'][child]['nodes'][fixture.row['id'] + '/client']['status'], 'published')
                self.assertEqual(publication.published(fixture.root, fixture.row)[0]['publications']['client']['capture'], child)
            self.assertEqual({str(p): p.read_bytes() for p in decoy.rglob('*') if p.is_file()}, old_bytes)
            self.assertFalse(any(word in str(fixture.accesses) for word in ('OldOrg', 'retired-product', '999999999', str(decoy))))
            self.assertIn(str(fixture.root / 'status.json'), reads)
        return None

    def test_older_activation_builds_only_its_exact_tag_then_chain_selects_highest(self):
        fixture = deployments.DeploymentTest()
        with fixture.deployment('ExampleOrg', 'ReleaseControl', 'Binaries', ('engine', 'client', 'plugin', 'bundle')):
            fixture.notify('engine', 'v1.0.0', fixture.tag('engine', 'v1.0.0'))
            fixture.drain()
            old = fixture.tag('client', 'v1.9.0')
            high = fixture.tag('client', 'v2.0.0')
            start = len(fixture.posts)
            direct, _ = fixture.notify('client', 'v1.9.0', old)
            fixture.drain()
            work = [(k, r) for _, _, k, r in fixture.posts[start:] if r['project'] == 'client']
            self.assertEqual([k for k, _ in work], ['build', 'publish'])
            self.assertEqual([r['capture'] for _, r in work], [direct, direct])
            info = publication.published(fixture.root, fixture.row)[0]
            self.assertEqual(set(info['releases']['client']), {'v1.9.0'})
            start = len(fixture.posts)
            fixture.notify('engine', 'v1.0.0', fixture.tag('engine', 'v1.0.0', 'new prerequisite'))
            fixture.drain()
            work = [(k, r) for _, _, k, r in fixture.posts[start:] if r['project'] == 'client']
            self.assertEqual([k for k, _ in work], ['capture', 'build', 'publish'])
            child = work[1][1]['capture']
            state = publication.read(fixture.root / 'status.json')
            self.assertEqual(state['runs'][child]['sources'][fixture.row['id']]['client'], {'refs/tags/v2.0.0': high})
            self.assertEqual(repository.source_tag(publication.published(fixture.root, fixture.row)[0], 'client'), 'v2.0.0')
        return None
