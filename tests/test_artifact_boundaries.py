"""Publisher inventories and OpenWrt post-compile prerequisite integrity."""
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from support import PinnedJsonCase, feed_manifest
from ci import repository
from ci.publish import publication

ROOT = repository.ROOT
BASE = Path(os.environ.get('TMPDIR', tempfile.gettempdir()))

class BoundaryTest(unittest.TestCase):
    def test_publisher_rejects_unlisted_files_before_ownership_or_feed_writes(self):
        for extra in ('index.html', '.hidden', 'foreign_9.9.9-r1_x86_64.ipk', 'nested/install.sh', 'directory-link'):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory(dir=BASE) as tmp:
                base = Path(tmp)
                incoming, feed = base/'incoming', base/'feed'
                incoming.mkdir()
                feed.mkdir()
                (feed/'sentinel').write_text('unchanged')
                (incoming/'own.ipk').write_bytes(b'verified')
                publication.write(incoming/'build.json', dict(sources={}, files={'own.ipk': repository.digest(incoming/'own.ipk')}))
                target = incoming/extra
                target.parent.mkdir(parents=True, exist_ok=True)
                if extra == 'directory-link':
                    target.symlink_to(feed, target_is_directory=True)
                else:
                    target.write_bytes(b'undeclared')
                before = (feed/'sentinel').read_bytes()
                with patch.dict(os.environ, BUILD_RECEIPT='{"capture":"42"}'), patch.object(
                        publication, 'published', return_value=({}, '')), patch.object(
                        publication, 'ownership', side_effect=AssertionError('Validation bypassed')):
                    with self.assertRaisesRegex(RuntimeError, 'undeclared|Unlisted'):
                        publication.publish(feed, base/'bundle', incoming, {}, {}, 'own')
                self.assertEqual((feed/'sentinel').read_bytes(), before)
                self.assertEqual(sorted(p.name for p in feed.iterdir()), ['sentinel'])
        return None

    def test_declared_flat_and_nested_files_pass_inventory_boundary(self):
        for name in ('own.ipk', 'Packages/own.rpm'):
            with self.subTest(name=name), tempfile.TemporaryDirectory(dir=BASE) as tmp:
                base = Path(tmp)
                package = base/name
                package.parent.mkdir(parents=True, exist_ok=True)
                package.write_bytes(b'verified')
                publication.write(base/'build.json', dict(sources={}, files={name: repository.digest(package)}))
                with patch.dict(os.environ, BUILD_RECEIPT='{"capture":"42"}'), patch.object(
                        publication, 'published', return_value=({}, '')), patch.object(
                        publication, 'ownership', side_effect=RuntimeError('Reached ownership')):
                    with self.assertRaisesRegex(RuntimeError, 'Reached ownership'):
                        publication.publish(base/'feed', base/'bundle', base, {}, {}, 'own')
        return None

    def test_openwrt_build_rechecks_import_after_compile(self):
        for overwrite in (False, True):
            with self.subTest(overwrite=overwrite), tempfile.TemporaryDirectory(dir=BASE) as tmp:
                base = Path(tmp)
                sdk, bundle, feed, commands = (base/n for n in ('sdk','bundle','feed','commands'))
                for p in (sdk, bundle, feed, commands, base/'dependencies'):
                    p.mkdir()
                (sdk/'scripts').mkdir()
                (sdk/'scripts/feeds').write_text('#!/bin/sh\nexit 0\n')
                (sdk/'scripts/feeds').chmod(0o755)
                (sdk/'feeds.conf.default').write_text('')
                (sdk/'imported.h').write_text('pinned')
                hook = ('compile() { printf changed > imported.h; }\n' if overwrite else 'compile() { :; }\n')
                with tarfile.open(bundle/'own-source.tar.gz', 'w:gz') as tar:
                    item = tarfile.TarInfo('own/hook.sh')
                    item.size = len(hook.encode())
                    tar.addfile(item, io.BytesIO(hook.encode()))
                python = commands/'python3'
                python.write_text('''#!/usr/bin/env python3
import os,sys
from pathlib import Path
if sys.argv[1:4] == ['-m','ci.repository','sdk-dependency']:
 p=Path(sys.argv[4])
 with (p/'checks').open('a') as f:f.write('check\\n')
 if (p/'imported.h').read_text()!='pinned': raise SystemExit('Conflicting development exports: imported.h')
elif sys.argv[1]=='-c': print('hook.sh' if 'openwrt' in sys.argv[2] else 'own')
'''.replace('#!/usr/bin/env python3', '#!'+os.sys.executable))
                python.chmod(0o755)
                make = commands/'make'
                make.write_text('#!/bin/sh\nif [ "$1" = defconfig ]; then printf \'CONFIG_TARGET_ARCH_PACKAGES="x86_64"\\n\' >> .config; '
                                'mkdir -p bin/packages/x86_64/package_ci; fi\n')
                make.chmod(0o755)
                env = dict(os.environ, PATH=str(commands)+':'+os.environ['PATH'], BUILD_PROJECT='own', PACKAGE_RELEASE='1')
                result = subprocess.run(['bash',str(ROOT/'ci/build/openwrt.sh'),str(feed),str(bundle),str(sdk)],
                                        env=env, capture_output=True, text=True)
                self.assertEqual((sdk/'checks').read_text().splitlines(), ['check','check'])
                self.assertEqual(result.returncode == 0, not overwrite, result.stderr)
                if overwrite:
                    self.assertIn('Conflicting development exports', result.stderr)
        return None

class SdkImportBoundaryTest(PinnedJsonCase):
    def test_real_export_reimport_conflicts_and_documented_missing_file_repair(self):
        for change in ('none', 'bytes', 'link', 'type', 'missing'):
            with self.subTest(change=change), tempfile.TemporaryDirectory(dir=BASE) as tmp:
                base = Path(tmp)
                origin, sdk, bundle, archives = (base/n for n in ('origin', 'sdk', 'bundle', 'archives'))
                for folder in (origin, sdk, bundle, archives):
                    folder.mkdir()
                info = dict(release='24.10.8', target='x86/64', arch='x86_64', sha256='a'*64)
                for folder in (origin, sdk):
                    publication.write(folder/'ci-sdk.json', info)
                source = origin/'staging_dir/target-test/usr/lib'
                source.mkdir(parents=True)
                (source/'libcore.so.1').write_bytes(b'pinned library')
                (source/'libcore.so').symlink_to('libcore.so.1')
                for suffix in ('cmake', 'pc', 'la'):
                    (source/('core.'+suffix)).write_text(str(origin)+'/staging_dir/target-test/usr/lib')
                publication.write(bundle/'context.json', dict(build_project='snode.c', versions={'snode.c':'1.0.0'}))
                names = [str(p.relative_to(origin)) for p in source.iterdir()]
                with patch.dict(os.environ, PACKAGE_RELEASE='2'):
                    repository.sdk_export(origin, bundle, *names)
                export = next(origin.glob('*.tar.zst'))
                (archives/export.name).write_bytes(export.read_bytes())
                baseline = feed_manifest(dict(info, revision='2',
                    sources={'snode.c':{'refs/tags/v1.0.0':'a'*40}}, versions={'snode.c':'1.0.0-r2'},
                    context=dict(build_project='snode.c'), files={export.name:repository.digest(export)}))
                publication.write(bundle/'baseline.json', baseline)
                publication.write(bundle/'context.json', dict(build_project='mqttsuite'))
                repository.sdk_dependency(sdk, bundle, archives)
                destination = sdk/source.relative_to(origin)
                for suffix in ('cmake', 'pc', 'la'):
                    self.assertEqual((destination/('core.'+suffix)).read_text(),
                                     str(sdk)+'/staging_dir/target-test/usr/lib')
                if change in {'bytes', 'type'}:
                    (destination/'libcore.so.1').unlink()
                    if change == 'bytes':
                        (destination/'libcore.so.1').write_bytes(b'changed library')
                    elif change == 'type':
                        (destination/'libcore.so.1').symlink_to('core.pc')
                elif change == 'missing':
                    (destination/'core.pc').unlink()
                elif change == 'link':
                    (destination/'libcore.so').unlink()
                    (destination/'libcore.so').symlink_to('core.pc')
                if change in {'bytes', 'link', 'type'}:
                    with self.assertRaisesRegex(RuntimeError, 'Conflicting development exports'):
                        repository.sdk_dependency(sdk, bundle, archives)
                else:
                    repository.sdk_dependency(sdk, bundle, archives)
                    self.assertEqual((destination/'libcore.so.1').read_bytes(), b'pinned library')
                    self.assertEqual(os.readlink(destination/'libcore.so'), 'libcore.so.1')
                    self.assertEqual((destination/'core.pc').read_text(), str(sdk)+'/staging_dir/target-test/usr/lib')
                    self.assertEqual(repository.digest(archives/export.name), repository.digest(export))
        return None


if __name__ == '__main__':
    unittest.main(verbosity=2)
