"""Exercise downloaded installers with isolated configuration and command doubles."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.etc = self.root / 'etc'
        self.etc.mkdir()
        self.log = self.root / 'commands'
        self.download = self.root / 'download'
        self.download.mkdir()
        for source in (ROOT / 'install').glob('*.sh'):
            (self.download / source.name).write_text(source.read_text().replace('/etc/', str(self.etc) + '/'))
        self.command('id', 'echo 0')
        self.command('dpkg', 'echo amd64')
        self.command('rpm', 'if [ "$1" = --eval ]; then echo x86_64; else echo "rpm $*" >> "$LOG"; fi')
        self.command('curl', '[ "${FAIL_FETCH:-0}" = 0 ] || exit 22\nprintf key > "$4"')
        for name in ['apt-get', 'dnf', 'opkg', 'opkg-key', 'apk']:
            self.command(name, f'echo "{name} $*" >> "$LOG"')
        self.platform('debian')

    def command(self, name, body):
        script = self.bin / name
        script.write_text('#!/bin/sh\nset -eu\n' + body + '\n')
        script.chmod(0o755)

    def platform(self, distribution):
        (self.etc / 'os-release').write_text(f'ID={distribution}\nVERSION_CODENAME=trixie\nVERSION_ID=44\n')
        if distribution == 'openwrt':
            (self.etc / 'openwrt_release').write_text('DISTRIB_RELEASE=25.12.0\nDISTRIB_ARCH=aarch64_cortex-a53\n')

    def run_installer(self, *args, script='install.sh', fail_fetch=False):
        result = subprocess.run(['sh', str(self.download / script), *args], cwd=self.root,
                                env=os.environ | {'PATH': str(self.bin) + os.pathsep + os.defpath,
                                                  'LOG': str(self.log), 'FAIL_FETCH': str(int(fail_fetch))},
                                capture_output=True, text=True)
        return result

    def test_help_and_invalid_selection_do_not_modify_configuration(self):
        for args, code in [((), 0), (('--help',), 0), (('--project', 'other'), 2),
                           (('--component', 'broker'), 2), (('--project', 'mqttsuite', '--component', 'client-dev'), 2),
                           (('--project', 'snodec', '--component', '*'), 2), (('--project',), 2),
                           (('--prepare', '--project', 'snodec'), 2), (('--prepare', '--component', 'broker'), 2),
                           (('--project', 'snodec', '--project', 'mqttsuite'), 2)]:
            with self.subTest(args=args):
                result = self.run_installer(*args)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertFalse(self.log.exists())
                self.assertEqual(list(self.etc.iterdir()), [self.etc / 'os-release'])

    def test_project_wrappers_select_only_their_project(self):
        for project, package in [('snodec', 'snodec'), ('mqttsuite', 'mqttsuite'), ('snodec-idp', 'snodec-idp')]:
            with self.subTest(project=project):
                self.log.unlink(missing_ok=True)
                result = self.run_installer(script=project + '.sh')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.log.read_text().splitlines(), ['apt-get update', 'apt-get install -y ' + package])

    def test_repeatable_components_and_repository_only(self):
        result = self.run_installer('--component', 'broker', '--component', 'cli', script='mqttsuite.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('apt-get install -y mqttsuite-broker mqttsuite-cli', self.log.read_text())
        self.log.unlink()
        result = self.run_installer('--prepare')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text(), 'apt-get update\n')

    def test_all_package_managers(self):
        for distribution, expected in [('ubuntu', 'apt-get install -y snodec-http-server-express-tls-in'),
                                       ('fedora', 'dnf install -y snodec-http-server-express-tls-in'),
                                       ('rocky', 'dnf install -y snodec-http-server-express-tls-in'),
                                       ('openwrt', 'apk add snodec-http-server-express-tls-in')]:
            self.platform(distribution)
            result = self.run_installer('--component', 'http-server-express-tls-in', script='snodec.sh')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, self.log.read_text())
        (self.etc / 'openwrt_release').write_text('DISTRIB_RELEASE=24.10.4\nDISTRIB_ARCH=aarch64_cortex-a53\n')
        (self.etc / 'opkg').mkdir()
        result = self.run_installer('--component', 'broker', script='mqttsuite.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('opkg install mqttsuite-broker', self.log.read_text())

    def test_unsupported_platform_and_fetch_failure_stop_before_configuration(self):
        self.platform('openwrt')
        result = self.run_installer(script='snodec-idp.sh')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.log.exists())
        (self.etc / 'openwrt_release').unlink()
        self.platform('unsupported')
        self.assertNotEqual(self.run_installer(script='mqttsuite.sh').returncode, 0)
        self.platform('debian')
        self.assertNotEqual(self.run_installer(script='mqttsuite.sh', fail_fetch=True).returncode, 0)
        self.assertFalse(self.log.exists())
        self.assertEqual(list(self.etc.iterdir()), [self.etc / 'os-release'])


if __name__ == '__main__':
    unittest.main()
