"""Sign the SDK-generated index, once, in the trusted publisher."""
import gzip
import json
import os
from pathlib import Path
import tempfile

from ci.repository import ROOT, digest, run, package_owner


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
            run('usign', '-V', '-m', str(index), '-p', str(ROOT / 'keys/snodec-opkg.pub'), '-x', str(signature))
            info['files']['Packages.sig'] = digest(signature)
        else:
            key.write_text(os.environ['OPENWRT_APK_KEY'])
            key.chmod(0o600)
            index = directory / 'packages.adb'
            run('apk', 'adbsign', '--allow-untrusted', '--sign-key', str(key), str(index))
            run('apk', 'verify', '--keys-dir', str(ROOT / 'keys'), str(index))
            info['files']['packages.adb'] = digest(index)
    (directory / 'build.json').write_text(json.dumps(info, indent=2) + '\n')


def reindex(directory, previous, info, project):
    """Rebase retained products without recompiling or changing captured dependencies."""
    if info['series'] == '24.10':
        paragraphs = []
        for path, own in [(directory / 'Packages', True), (previous / 'Packages', False)]:
            if path.exists():
                for paragraph in path.read_text().strip().split('\n\n'):
                    name = next((line[9:] for line in paragraph.splitlines() if line.startswith('Package: ')), '')
                    if bool(package_owner(name) == project) == own:
                        paragraphs.append(paragraph)
        data = ('\n\n'.join(sorted(paragraphs)) + '\n\n').encode()
        (directory / 'Packages').write_bytes(data)
        (directory / 'Packages.gz').write_bytes(gzip.compress(data, mtime=0))
        indexes = ['Packages', 'Packages.gz']
    else:
        run('apk', 'mkndx', '--allow-untrusted', '--output', str(directory / 'packages.adb'),
            *(str(path) for path in sorted(directory.glob('*.apk'))))
        indexes = ['packages.adb']
    for name in indexes:
        info['files'][name] = digest(directory / name)
