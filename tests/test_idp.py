"""Third-product boundaries, including sibling publication while an IDP build runs."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from support import PinnedJsonCase
from unittest.mock import patch

from ci import repository, dispatch
from ci.publish import publication


class IdpTest(PinnedJsonCase):
    def test_package_ownership_is_unambiguous(self):
        for filename in ['snodec-idp_2.0.0_amd64.deb', 'snodec-idp-client-dev-2.0.0-1.x86_64.rpm']:
            self.assertTrue(repository.project_file(filename, 'snode.c-idp'))
            self.assertFalse(repository.project_file(filename, 'snode.c'))
        self.assertTrue(repository.project_file('snodec-core_2.0.0_amd64.deb', 'snode.c'))
        self.assertEqual(repository.package_owner('snodec-idp-server-dev'), 'snode.c-idp')

    def test_idp_support_is_native_only(self):
        for row in publication.targets():
            self.assertEqual(repository.supports('snode.c-idp', row), row['family'] != 'openwrt')
        self.assertNotIn('openwrt', repository.PROJECTS['snode.c-idp']['matrix'])
        return None

    def test_old_counter_state_adds_idp_without_resetting_products(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            publication.write(root / 'status.json', {'counters': {'snode.c': 17, 'mqttsuite': 21}})
            self.assertEqual(publication.reserve(root, 'snode.c', '100'),
                             {'snode.c': '18', 'mqttsuite': '22', 'snode.c-idp': '1'})
            self.assertEqual(publication.reserve(root, 'snode.c-idp', '101'), {'snode.c-idp': '2'})

    def test_idp_handoff_uses_the_shared_identity_contract(self):
        import yaml
        workflow = yaml.load((repository.ROOT / '.github/workflows/build-packages.yml').read_text(), Loader=yaml.BaseLoader)
        reporter = next(step for step in workflow['jobs']['build']['steps'] if step.get('name') == 'Report completed build')
        self.assertEqual(reporter['env']['BUILD_JOB_ID'], '${{ job.check_run_id }}')
        self.assertIn('ci.dispatch report', reporter['run'])
        return None

    def test_native_publication_preserves_newer_unrelated_sibling(self):
        row = next(row for row in publication.targets() if row['id'] == 'debian-trixie-amd64')
        with tempfile.TemporaryDirectory() as tmp:
            root, bundle, incoming = (Path(tmp) / name for name in ('root', 'bundle', 'incoming'))
            directory = incoming / 'linux/debian/trixie/amd64'
            directory.mkdir(parents=True)
            pool = root / 'debian/pool/trixie'
            pool.mkdir(parents=True)
            files = {}
            for name in ['snodec_2_amd64.deb', 'mqttsuite_1_amd64.deb', 'mqttsuite_2_amd64.deb', 'snodec-idp_2_amd64.deb']:
                (pool / name).write_text(name)
                files[name] = repository.digest(pool / name)
            context = dict(build_project='snode.c-idp', release_project='snode.c-idp', run_id='100',
                           source_tags={'snode.c': 'v2.0.0', 'mqttsuite': 'v1.0.0', 'snode.c-idp': 'v2.0.0'},
                           versions={'snode.c': '2.0.0', 'mqttsuite': '1.0.0', 'snode.c-idp': '2.0.0'})
            baseline = dict(sources={'snode.c': {'refs/tags/v2.0.0':'a'*40}, 'mqttsuite': {'refs/tags/v1.0.0':'b'*40}}, context=copy.deepcopy(context),
                            files={k: files[k] for k in ['snodec_2_amd64.deb', 'mqttsuite_1_amd64.deb']},
                            packages=['snodec', 'mqttsuite'], versions={'snodec': '2.0.0-2~trixie', 'mqttsuite': '1.0.0-1~trixie'})
            current = copy.deepcopy(baseline)
            current['sources']['mqttsuite'] = {'refs/tags/v1.0.1':'c'*40}
            current['context']['source_tags']['mqttsuite'] = 'v1.0.1'
            current['context']['versions']['mqttsuite'] = '1.0.1'
            current['versions']['mqttsuite'] = '1.0.1-2~trixie'
            current['files'] = {k: files[k] for k in ['snodec_2_amd64.deb', 'mqttsuite_2_amd64.deb']}
            publication.write(root / 'debian/dists/trixie/build.json', {'targets': {'amd64': current}})
            profile = dict(projects=copy.deepcopy(repository.PROJECTS), baseline=baseline, context=context, sources={'snode.c-idp': {'refs/tags/v2.0.0':'d'*40}},
                           archives={'snode.c-idp': 'idp.tar.gz'})
            publication.write(bundle / 'profiles.json', {row['id']: profile})
            (bundle / 'archives').mkdir()
            (bundle / 'archives/idp.tar.gz').touch()
            selected = repository.select(bundle, row['id'], 'snode.c-idp')
            metadata = dict(revision='1', sources=selected['sources'], context=selected['context'],
                            versions=baseline['versions'] | {'snodec-idp': '2.0.0-1~trixie'},
                            packages=['snodec', 'mqttsuite', 'snodec-idp'],
                            files=baseline['files'] | {'snodec-idp_2_amd64.deb': files['snodec-idp_2_amd64.deb']})
            for name in metadata['files']:
                (directory / name).write_bytes((pool / name).read_bytes())
            publication.write(directory / 'build.json', metadata)
            generation = dict(revisions={'snode.c-idp': '1'}, profiles_hash=repository.digest(bundle / 'profiles.json'))
            import ci.publish.linux as linux
            def sign(*args):
                result = publication.read(directory / 'build.json')
                self.assertIn('mqttsuite_2_amd64.deb', result['files'])
                self.assertNotIn('mqttsuite_1_amd64.deb', result['files'])
                self.assertEqual(result['sources']['mqttsuite'], {'refs/tags/v1.0.1':'c'*40})
                self.assertEqual(result['versions']['mqttsuite'], '1.0.1-2~trixie')
                self.assertEqual(result['files']['snodec-idp_2_amd64.deb'], files['snodec-idp_2_amd64.deb'])
                return None
            with patch.object(repository, 'activate'), patch.object(publication, 'activate'), patch.object(linux, 'publish', side_effect=sign), patch('ci.publish.cleanup.cleanup'):
                publication.publish(root, bundle, incoming, row, generation, 'snode.c-idp')
            # Same source and revision with changed prerequisite bytes is also stale.
            prerequisite=pool/'snodec_2_amd64.deb'
            original=prerequisite.read_bytes()
            prerequisite.write_bytes(b'replaced prerequisite bytes')
            current['files'][prerequisite.name]=repository.digest(prerequisite)
            publication.write(root/'debian/dists/trixie/build.json',{'targets':{'amd64':current}})
            with patch.object(repository,'activate'),patch.object(publication,'activate'),self.assertRaisesRegex(RuntimeError,'dependency changed'):
                publication.publish(root,bundle,incoming,row,generation,'snode.c-idp')
            prerequisite.write_bytes(original)
            current['files'][prerequisite.name]=repository.digest(prerequisite)
            # A changed framework is a real dependency conflict, unlike its unrelated sibling.
            current['sources']['snode.c'] = {'refs/tags/v2.0.0':'e'*40}
            publication.write(root / 'debian/dists/trixie/build.json', {'targets': {'amd64': current}})
            with patch.object(repository, 'activate'), patch.object(publication, 'activate'), self.assertRaisesRegex(RuntimeError, 'dependency changed'):
                publication.publish(root, bundle, incoming, row, generation, 'snode.c-idp')
        return None


if __name__ == '__main__':
    unittest.main()
