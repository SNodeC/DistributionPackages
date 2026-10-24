"""Sign the SDK-generated index, once, in the trusted publisher."""
import gzip
import json
import os
import re
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
            run('usign', '-V', '-m', str(index), '-p', str(ROOT / 'keys/opkg.pub'), '-x', str(signature))
            info['files']['Packages.sig'] = digest(signature)
        else:
            key.write_text(os.environ['OPENWRT_APK_KEY'])
            key.chmod(0o600)
            index = directory / 'packages.adb'
            run('apk', 'adbsign', '--allow-untrusted', '--sign-key', str(key), str(index))
            run('apk', 'verify', '--keys-dir', str(ROOT / 'keys'), str(index))
            info['files']['packages.adb'] = digest(index)
    (directory / 'build.json').write_text(json.dumps(info, indent=2) + '\n')


def reindex(directory, info, controls):
    """Index verified package bytes, including retained products absent from SDK indexes."""
    if info['series'] == '24.10':
        paragraphs = []
        for name, fields in sorted(controls.items()):
            derived = f'Filename: {name}\nSize: {(directory / name).stat().st_size}\nSHA256sum: {digest(directory / name)}\n'
            control = fields['control'].strip()
            paragraphs.append(re.sub(r'(?m)^Description:', lambda match: derived + match[0], control, count=1)
                              if re.search(r'(?m)^Description:', control) else control + '\n' + derived.rstrip())
        data = ('\n\n'.join(paragraphs) + '\n\n').encode()
        (directory / 'Packages').write_bytes(data)
        (directory / 'Packages.gz').write_bytes(gzip.compress(data, mtime=0))
        indexes = ['Packages', 'Packages.gz']
    else:
        run('apk', 'mkndx', '--allow-untrusted', '--output', str(directory / 'packages.adb'),
            *(str(path) for path in sorted(directory.glob('*.apk'))))
        indexed = json.loads(run('apk', 'adbdump', '--format', 'json', str(directory / 'packages.adb')))['packages']
        if sorted(tuple(p[k] for k in ['name', 'version', 'arch']) for p in indexed) != sorted(
                tuple(p[k] for k in ['name', 'version', 'arch']) for p in controls.values()):
            raise ValueError('APK index does not exactly cover verified package identities')
        indexes = ['packages.adb']
    for name in indexes:
        info['files'][name] = digest(directory / name)
    return None
