"""A third SDK product uses the registry/export contract without generic edits."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ci import repository
from ci.publish import publication


class RecipeTest(unittest.TestCase):
    def test_third_product_preserves_every_retained_version(self):
        with tempfile.TemporaryDirectory() as t:
            sdk, bundle, output = (Path(t) / name for name in ('sdk', 'bundle', 'output'))
            feed = sdk / 'bin/packages/test/snodec'
            feed.mkdir(parents=True)
            publication.write(sdk / 'ci-sdk.json', dict(arch='test', series='24.10'))
            for name in ['demo.ipk', 'Packages', 'Packages.gz']:
                (feed / name).write_bytes(b'fixture')
            publication.write(bundle / 'context.json', dict(build_project='demo', versions={'demo':'1.0.0', 'snode.c':'2.0.0', 'mqttsuite':'1.0.2'}))
            publication.write(bundle / 'sources.json', {})
            retained = {'snode.c':'2.0.0-r2', 'mqttsuite':'1.0.2-r3'}
            publication.write(bundle / 'baseline.json', dict(versions=retained))
            with patch.dict(os.environ, PACKAGE_RELEASE='9'):
                repository.stage(sdk, bundle, output)
            self.assertEqual(publication.read(output / 'openwrt/24.10/test/build.json')['versions'], retained | {'demo':'1.0.0-r9'})

    def test_unreleased_dependent_does_not_abort_capture(self):
        # Reuse the existing real local-source capture regression for the root;
        # missing-tag behavior is verified before any source fetch below.
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            graph = {'demo':dict(title='Demo',package='demo',depends_on=[],families=['linux']),
                     'new':dict(title='New',package='new',depends_on=['demo'],families=['linux'])}
            publication.write(root / 'status.json', {'allocations': {'123':dict(demo='1',new='1')}})
            def run(*args, **kwargs):
                if args[:3] == ('git','ls-remote','--tags'):
                    value = ''
                elif args[:2] == ('git','init'):
                    raise InterruptedError('reached root source fetch')
                else:
                    value = 'a' * 40
                return value
            row = dict(id='test',family='linux')
            with patch.object(repository,'PROJECTS',graph),patch.object(repository,'REPOSITORIES',tuple(graph)), \
                 patch.object(publication,'targets',return_value=[row]),patch.object(publication,'published',return_value=({},'feed')), \
                 patch.object(repository,'run',side_effect=run),patch.dict(os.environ,RELEASE_PROJECT='demo',RELEASE_TAG='v1.0.0',RELEASE_SHA='a'*40,GITHUB_RUN_ID='123'):
                with self.assertRaisesRegex(InterruptedError,'root source fetch'):
                    repository.prepare(root,root/'bundle')

    def test_openwrt_reindex_preserves_third_product_after_sibling_changes(self):
        from ci.publish.openwrt import reindex
        import gzip
        with tempfile.TemporaryDirectory() as temporary:
            directory, previous = (Path(temporary) / name for name in ('incoming', 'published'))
            directory.mkdir()
            previous.mkdir()
            graph = repository.PROJECTS | {'demo': dict(title='Demo', package='demo', depends_on=[], families=['openwrt'])}
            (directory / 'Packages').write_text('Package: demo\nVersion: 2-r2\n\nPackage: mqttsuite\nVersion: 1-r1\n\n')
            (previous / 'Packages').write_text('Package: demo\nVersion: 1-r1\n\nPackage: mqttsuite\nVersion: 3-r3\n\nPackage: snodec\nVersion: 2-r4\n\n')
            info = dict(series='24.10', files={})
            with patch.object(repository, 'PROJECTS', graph):
                reindex(directory, previous, info, 'demo')
            index = (directory / 'Packages').read_text()
            self.assertIn('Version: 3-r3', index)
            self.assertIn('Version: 2-r4', index)
            self.assertIn('Version: 2-r2', index)
            self.assertNotIn('Version: 1-r1', index)
            self.assertEqual(gzip.decompress((directory / 'Packages.gz').read_bytes()).decode(), index)
            self.assertEqual(info['files']['Packages'], repository.digest(directory / 'Packages'))

    def test_capture_pinning_includes_transitive_dependencies(self):
        from ci import dispatch
        graph = repository.PROJECTS | {'demo': dict(title='Demo', package='demo', depends_on=['mqttsuite'], families=['linux'])}
        sources = {name: {f'refs/tags/v1.0.0': 'a' * 40} for name in graph}
        baseline = dict(versions={'snodec': '1.0.0-1~trixie', 'mqttsuite': '1.0.0-2~trixie'})
        profile = dict(baseline=baseline, sources=sources)
        current = dict(versions={'snodec': '1.0.0-3~trixie', 'mqttsuite': '1.0.0-2~trixie'}, sources=sources)
        with patch.object(repository, 'PROJECTS', graph):
            self.assertFalse(dispatch.ready(profile, {'demo': '4'}, 'demo', current, graph))
            current['versions']['snodec'] = '1.0.0-1~trixie'
            self.assertTrue(dispatch.ready(profile, {'demo': '4'}, 'demo', current, graph))
