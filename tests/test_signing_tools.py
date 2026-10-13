"""Exercise the signing-tool install boundary without root, network or production keys."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

from ci.repository import ROOT


class SigningToolsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.cache = self.root / 'cache'
        self.log = self.root / 'commands'
        stub = self.bin / 'command'
        stub.write_text('''#!/usr/bin/env python3
import os, pathlib, subprocess, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['COMMAND_LOG'], 'a') as log:
    log.write(name + ' ' + ' '.join(args) + '\\n')
if name == 'sudo':
    if args[0] == 'install':
        subprocess.run(['/usr/bin/install', *args[1:-1], os.environ['INSTALLED']], check=True)
elif name == 'git' and args[0] == 'clone':
    pathlib.Path(args[-1]).mkdir(exist_ok=True)
elif (name == 'cmake' and args[0] == '--build') or (name == 'meson' and args[0] == 'compile'):
    output = pathlib.Path('signing-usign/build/usign' if name == 'cmake' else 'signing-apk/build/src/apk')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('#!/bin/sh\\nexit 0\\n')
    output.chmod(0o755)
''')
        stub.chmod(0o755)
        for name in ('sudo', 'git', 'cmake', 'meson'):
            (self.bin / name).symlink_to(stub)
        self.installed = self.root / 'installed'
        self.installed.mkdir()

    def execute(self, family='openwrt'):
        self.log.write_text('')
        subprocess.run(['bash', str(ROOT / 'ci/publish/tools.sh'), family, str(self.cache)],
                       cwd=self.root, check=True, capture_output=True,
                       env=os.environ | {'PATH': str(self.bin) + ':' + os.defpath,
                                         'COMMAND_LOG': str(self.log), 'INSTALLED': str(self.installed)})
        return self.log.read_text()

    def test_miss_builds_pinned_tools_and_hit_installs_without_compilation(self):
        miss = self.execute()
        self.assertEqual(miss.count('git clone '), 2)
        self.assertIn('c4c72b1b07945ee192361dc751291a7c98d6adcd', miss)
        self.assertIn('b5a31c0d865342ad80be10d68f1bb3d3ad9b0866', miss)
        self.assertEqual({p.name for p in self.cache.iterdir()}, {'usign', 'apk'})
        hit = self.execute()
        for command in ('git ', 'cmake ', 'meson ', 'install -y cmake'):
            self.assertNotIn(command, hit)
        self.assertIn('sudo install ', hit)
        for tool in ('usign', 'apk'):
            self.assertEqual((self.cache / tool).read_bytes(), (self.installed / tool).read_bytes())

    def test_incomplete_cache_rebuilds(self):
        self.execute()
        (self.cache / 'apk').unlink()
        self.assertEqual(self.execute().count('git clone '), 2)

    def test_other_families_do_not_build_or_cache_openwrt_tools(self):
        self.assertNotIn('git ', self.execute('linux'))
        self.assertFalse(self.cache.exists())

    def test_cache_is_exact_platform_and_capture_script_scoped(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/sign-and-publish-packages.yml').read_text())
        steps = workflow['jobs']['write']['steps']
        cache = next(s for s in steps if s.get('name') == 'Cache compiled OpenWrt signers')
        restore = next(s for s in steps if s.get('id') == 'scope')
        self.assertLess(steps.index(restore), steps.index(cache))
        self.assertIn('checkout --detach "$commit"', restore['run'])
        for part in ("hashFiles('feed/ci/publish/tools.sh')", 'runner.os', 'runner.arch', 'signer-platform'):
            self.assertIn(part, cache['with']['key'])
        self.assertNotIn('restore-keys', cache['with'])
        self.assertEqual(cache['with']['path'], '${{ runner.temp }}/openwrt-signers')


if __name__ == '__main__':
    unittest.main()
