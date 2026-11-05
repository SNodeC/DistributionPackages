import copy
from pathlib import Path
from support import entry, rejects, replace
from coreci import validate


def main():
    deb=entry()
    script=validate.native_script(deb,['debian/pool/stable/a_1.2.3-7_amd64.deb'],'http://127.0.0.1:1234/',Path('/public/test.asc'))
    assert 'apt-get update' in script and 'apt-get install --dry-run' in script
    assert 'signed-by=/key/test.asc' in script and 'trusted=yes' not in script
    assert 'dpkg-deb --field' in script and 'NO_PUBKEY' in script
    rpm=entry('rpm')
    script=validate.native_script(rpm,['fedora/stable/x86_64/Packages/a-1.2.3-7.x86_64.rpm'],
                                  'http://127.0.0.1:1234/',Path('/public/test.asc'))
    assert 'dnf makecache --refresh' in script and 'dnf install -y --downloadonly' in script
    assert 'gpgcheck=1' in script and 'repo_gpgcheck=1' in script and '--assumeno' not in script
    print('validation: local repository URLs, signature enforcement and exact package dry-run/download contracts passed')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
