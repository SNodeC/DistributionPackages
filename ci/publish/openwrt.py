"""Sign the SDK-generated index, once, in the trusted publisher."""
import json
import os
from pathlib import Path
import tempfile

from ci.repository import ROOT, digest, run


def sign(directory, info):
    info['unsigned_files'] = info['files'].copy()
    with tempfile.TemporaryDirectory() as temporary:
        key = Path(temporary) / 'key'
        if info['series'] == '24.10':
            key.write_text(os.environ['OPENWRT_USIGN_KEY'])
            key.chmod(0o600)
            index = directory / 'Packages'
            signature = directory / 'Packages.sig'
            run('usign', '-S', '-m', str(index), '-s', str(key), '-x', str(signature))
            run('usign', '-V', '-m', str(index), '-p', str(ROOT / 'keys/snodec-usign.pub'), '-x', str(signature))
            info['files']['Packages.sig'] = digest(signature)
        else:
            key.write_text(os.environ['OPENWRT_APK_KEY'])
            key.chmod(0o600)
            index = directory / 'packages.adb'
            run('apk', 'adbsign', '--allow-untrusted', '--sign-key', str(key), str(index))
            run('apk', 'verify', '--keys-dir', str(ROOT / 'keys'), str(index))
            info['files']['packages.adb'] = digest(index)
    (directory / 'build.json').write_text(json.dumps(info, indent=2) + '\n')
