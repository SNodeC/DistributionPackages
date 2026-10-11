"""Execute the published examples against disposable paths and command fixtures only."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ci.repository import ROOT


class DocumentedCommandsTest(unittest.TestCase):
    def examples(self):
        for name in ['debian', 'ubuntu', 'raspberrypi', 'fedora', 'rocky', 'openwrt']:
            guide = {'raspberrypi': 'raspberry-pi-os', 'rocky': 'rocky-linux'}.get(name, name)
            text = (ROOT / f'site/docs/installation/{guide}.md').read_text()
            blocks = re.findall(r'```sh\n(.*?)\n```', text, re.S)
            for block in blocks:
                if 'mktemp -d' in block:
                    yield name, block

    def test_syntax_under_bash_dash_and_busybox_ash(self):
        shells = [['/bin/bash'], ['/bin/dash']]
        if shutil.which('busybox'):
            shells.append([shutil.which('busybox'), 'ash'])
        for name, block in self.examples():
            for shell in shells:
                with self.subTest(guide=name, shell=shell, block=block[:50]):
                    result = subprocess.run(shell + ['-n'], input=block, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_pasted_downloads_are_private_fail_closed_and_preserve_parent_shell(self):
        shells = [['/bin/bash'], ['/bin/dash']]
        if shutil.which('busybox'):
            shells.append([shutil.which('busybox'), 'ash'])
        for name, block in self.examples():
            manual = '/install/install.sh' not in block
            modes = ['success', 'download-1'] + (['download-2', 'bad-release', 'bad-arch'] if manual else [])
            for shell in shells:
                for mode in modes:
                    with self.subTest(guide=name, shell=shell, mode=mode, manual=manual):
                        with tempfile.TemporaryDirectory() as temporary:
                            root = Path(temporary)
                            (root / 'etc').mkdir()
                            (root / 'tmp').mkdir()
                            tools = root / 'bin'
                            tools.mkdir()
                            suite = {'debian': 'trixie', 'ubuntu': 'noble', 'raspberrypi': 'trixie', 'fedora': '43', 'rocky': '9'}.get(name, '24.10.8')
                            if name == 'openwrt' and '25.12' in block:
                                suite = '25.12.5'
                            distro = 'debian' if name == 'raspberrypi' else name
                            (root / 'etc/os-release').write_text(f'ID={distro}\nVERSION_ID={suite}\nVERSION_CODENAME={suite}\n')
                            (root / 'etc/openwrt_release').write_text(f'DISTRIB_RELEASE={suite}\nDISTRIB_ARCH=aarch64_cortex-a53\n')
                            if name == 'raspberrypi':
                                (root / 'etc/rpi-issue').touch()
                            key = 'snodec-opkg.pub' if name == 'openwrt' and '24.10' in block else 'snodec-apk.pem' if name == 'openwrt' else 'snodec-apt.asc'
                            shutil.copyfile(ROOT / 'keys' / key, root / 'published-key')
                            driver = tools / 'fixture'
                            driver.write_text('''#!/usr/bin/env python3
import json,os,pathlib,subprocess,sys
r=pathlib.Path(os.environ['FIXTURE_ROOT']);name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:]
with (r/'calls').open('a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='sudo': os.execvp(a[0],a)
if name=='dpkg': print(os.environ['FIXTURE_ARCH'])
elif name=='rpm' and '--eval' in a: print(os.environ['FIXTURE_ARCH'])
elif name in ['curl','wget']:
 count=int((r/'count').read_text())+1 if (r/'count').exists() else 1;(r/'count').write_text(str(count))
 target=pathlib.Path(a[a.index('-o' if name=='curl' else '-O')+1])
 assert target.parent.stat().st_mode & 0o777 == 0o700
 if os.environ['FIXTURE_MODE']=='download-'+str(count):target.write_text('PARTIAL');sys.exit(22)
 url=next(x for x in a if x.startswith('https:'))
 target.write_bytes((r/'published-key').read_bytes() if '/keys/' in url else b'#!/bin/sh\\necho executed >> "$FIXTURE_ROOT/installer-executed"\\n' if '/install/' in url else b'index')
elif name=='opkg-key':
 dest=r/'etc/opkg/keys/test-id';dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(pathlib.Path(a[-1]).read_bytes())
elif name=='sh':os.execv('/bin/sh',['sh',*a])
''')
                            driver.chmod(0o755)
                            for command in ['sudo', 'apt-get', 'dnf', 'dpkg', 'rpm', 'curl', 'wget', 'opkg', 'opkg-key', 'apk', 'sh']:
                                (tools / command).symlink_to(driver)
                            transformed = block.replace('/etc/', str(root / 'etc') + '/').replace('/tmp/snodec.XXXXXX', str(root / 'tmp/snodec.XXXXXX'))
                            if mode == 'bad-release':
                                if name in ['debian', 'ubuntu']:
                                    transformed = re.sub(r'  suite=\w+\n', '  suite=unsupported\n', transformed, count=1)
                                elif name == 'openwrt':
                                    (root / 'etc/openwrt_release').write_text('DISTRIB_RELEASE=unsupported\nDISTRIB_ARCH=aarch64_cortex-a53\n')
                                else:
                                    (root / 'etc/os-release').write_text(f'ID={distro}\nVERSION_ID=999\nVERSION_CODENAME=unsupported\n')
                            arch = 'arm64' if name in ['debian', 'ubuntu', 'raspberrypi'] else 'aarch64'
                            if mode == 'bad-arch':
                                arch = 'unsupported'
                                if name == 'openwrt':
                                    # OpenWrt guards feed existence rather than duplicating the architecture registry.
                                    mode = 'download-1'
                            env = os.environ | dict(PATH=str(tools) + ':' + os.environ['PATH'], FIXTURE_ROOT=str(root), FIXTURE_MODE=mode, FIXTURE_ARCH=arch)
                            result = subprocess.run(shell, input=transformed + '\nresult=$?\nprintf "PARENT_ALIVE:%s\\n" "$result"\n', env=env, text=True, capture_output=True)
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertIn('PARENT_ALIVE:', result.stdout)
                            succeeded = mode == 'success'
                            self.assertIn(f'PARENT_ALIVE:{0 if succeeded else 1 if mode.startswith("bad-") else 22}', result.stdout)
                            self.assertEqual(list((root / 'tmp').iterdir()), [])
                            configs = [p for p in (root / 'etc').rglob('*') if p.is_file() and p.name not in ['os-release', 'openwrt_release', 'rpi-issue']]
                            if not succeeded:
                                self.assertFalse(configs)
                                self.assertFalse((root / 'installer-executed').exists())
                            elif manual:
                                keyfiles = [p for p in configs if p.read_bytes() == (root / 'published-key').read_bytes()]
                                self.assertEqual(len(keyfiles), 1)
                                if name in ['rocky', 'fedora']:
                                    repo = (root / 'etc/yum.repos.d/snodec.repo').read_text()
                                    self.assertIn(f'/{name}/$releasever/$basearch/', repo)
                                    self.assertIn('gpgcheck=1\nrepo_gpgcheck=1', repo)
                                elif name in ['debian', 'ubuntu', 'raspberrypi']:
                                    self.assertIn('signed-by=', (root / 'etc/apt/sources.list.d/snodec.list').read_text())
                            else:
                                self.assertTrue((root / 'installer-executed').exists())


if __name__ == '__main__':
    unittest.main()
