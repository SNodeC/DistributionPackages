import copy
import stat
import os
import subprocess
import tempfile
from pathlib import Path
from support import entry, rejects, replace
from coreci import validate


def main():
    workflow=Path('.github/workflows/coreci-publish.yml').read_text()
    assert "if: contains(fromJSON(env.UBUNTU_EMULATORS), steps.sdk.outputs.emulator)" in workflow
    assert "sudo apt-get install -y qemu-user-static binfmt-support" in workflow
    assert "multiarch/qemu-user-static" not in workflow and "--privileged" not in workflow
    assert "platforms: ${{ steps.sdk.outputs.emulator }}" in workflow
    assert "grep -q '^flags:.*F' /proc/sys/fs/binfmt_misc/qemu-${{ steps.sdk.outputs.emulator }}" in workflow
    registration=workflow.split('      - name: Register Ubuntu emulation\n')[1].split('      - uses:')[0]
    registration=registration.split('        run: |\n', 1)[1]
    registration='\n'.join(line[10:] for line in registration.splitlines())
    registration=registration.replace('${{ steps.sdk.outputs.emulator }}', 'mipsel')
    with tempfile.TemporaryDirectory() as temporary:
        work=Path(temporary)
        sudo=work/'sudo'
        sudo.write_text('#!/bin/sh\nprintf "%s\\n" "$*"\n')
        sudo.chmod(0o755)
        flags=work/'qemu-mipsel'
        commands=registration.replace('/proc/sys/fs/binfmt_misc/qemu-mipsel',str(flags))
        for value,expected in [('enabled\nflags: POCF\n',0),('enabled\nflags: POC\n',1)]:
            flags.write_text(value)
            result=subprocess.run(['/bin/sh','-ec',commands],env={**os.environ,'PATH':str(work)+':'+os.environ['PATH']},capture_output=True,text=True)
            assert result.returncode==expected
            assert 'update-binfmts --enable qemu-mipsel' in result.stdout
    deb=entry()
    script=validate.native_script(deb,['debian/pool/stable/a_1.2.3-7_amd64.deb'],'http://127.0.0.1:1234/',Path('/public/test.asc'))
    assert 'apt-get update' in script and 'apt-get install --dry-run' in script
    assert 'signed-by=/key/test.asc' in script and 'trusted=yes' not in script
    assert 'dpkg-deb --field' in script and 'NO_PUBKEY' in script
    rpm=entry('rpm')
    script=validate.native_script(rpm,['fedora/stable/x86_64/Packages/a-1.2.3-7.x86_64.rpm'],
                                  'http://127.0.0.1:1234/',Path('/public/test.asc'))
    assert 'dnf makecache -y --refresh' in script and 'dnf install -y --downloadonly' in script
    assert 'rpm --import /key/test.asc' in script
    assert script.index('rpm --import') < script.index('dnf ')
    assert 'gpgcheck=1' in script and 'repo_gpgcheck=1' in script and '--assumeno' not in script
    assert 'epel-release' not in script and '--set-enabled crb' not in script
    for suite in ('9','10'):
        rocky=copy.deepcopy(rpm)
        rocky.update(distribution='rocky',suite=suite)
        prepared=validate.native_script(rocky,[], 'http://127.0.0.1:1234/',Path('/public/test.asc'))
        assert 'dnf install -y dnf-plugins-core epel-release\ndnf config-manager --set-enabled crb\n' in prepared
        assert prepared.index('epel-release') < prepared.index('dnf makecache')
        assert 'gpgcheck=1' in prepared and 'repo_gpgcheck=1' in prepared
    for fmt in ('ipk','apk'):
        target={'build':{'format':fmt}}
        package='openwrt/stable/x86_64/a_1.2.3-r7_x86_64.'+fmt
        key=Path('/public/test.pub' if fmt=='ipk' else '/public/test.pem')
        script=validate.openwrt_script(target,'http://127.0.0.1:1234/openwrt/stable/x86_64',
                                       [package],None,key,None)
        subprocess.run(['/bin/sh','-n'],input=script,text=True,check=True)
        if fmt=='ipk':
            assert 'opkg-key add /key/test.pub' in script
            assert 'opkg update' in script and 'opkg install --noaction /feed/'+package in script
            assert 'src/gz coreci http://127.0.0.1:1234/openwrt/stable/x86_64' in script
            with tempfile.TemporaryDirectory() as temporary:
                lock=Path(temporary)/'var/lock'
                before_opkg=script.split('opkg-key add',1)[0].replace('/var/lock',str(lock))
                subprocess.run(['/bin/sh','-c',before_opkg],check=True)
                assert lock.is_dir(), 'fresh rootfs must have its lock directory before opkg starts'
                assert stat.S_IMODE(lock.stat().st_mode)==0o1777, 'match OpenWrt boot lock permissions'
        else:
            assert 'cp /key/test.pem /etc/apk/keys/' in script
            assert 'apk update' in script and 'apk add --simulate /feed/'+package in script
            assert 'http://127.0.0.1:1234/openwrt/stable/x86_64/packages.adb' in script
    print('validation: native/OpenWrt signatures, dry runs and fresh-rootfs opkg lock setup passed')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
