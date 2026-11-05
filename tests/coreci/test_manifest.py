from pathlib import Path
import tempfile
from support import rejects, entry
from coreci import common
from contract import file_hash, write_json


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root/'a.deb').write_bytes(b'unsigned')
        manifest = dict(build_id='a~t1~1.0.0~r1', package='a', version='1.0.0', revision=1,
                        target='t1', feed='test', entry=entry(), files={'a.deb': file_hash(root/'a.deb')})
        values = dict(build_id=manifest['build_id'], package='a', version='1.0.0', revision='1', target='t1')
        write_json(root/'manifest.json', manifest)
        assert common.checked_manifest(root, values) == manifest
        (root/'a.deb').write_bytes(b'changed')
        rejects(common.checked_manifest, root, values, text='checksum')
        (root/'a.deb').write_bytes(b'unsigned')
        (root/'unexpected').write_text('x')
        rejects(common.checked_manifest, root, values, text='unexpected')
        (root/'unexpected').unlink()
        (root/'a.deb').unlink()
        (root/'a.deb').symlink_to('/etc/passwd')
        rejects(common.checked_manifest, root, values, text='regular')
        (root/'a.deb').unlink()
        manifest['files'] = {'../escape': 'a'*64}
        write_json(root/'manifest.json', manifest)
        rejects(common.checked_manifest, root, values)
    print('manifest: exact inputs, checksums, extra files, symlinks and traversal passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
