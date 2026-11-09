from pathlib import Path
import tempfile
from unittest.mock import patch
from support import entry
from coreci import publish


def main():
    target = entry()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        directory = root / publish.target_directory(target)
        directory.mkdir(parents=True)
        records = {}
        for revision in (1, 12, 13):
            version = f'2.1.0-{revision}~stable'
            path = directory / f'snodec_{version}_amd64.deb'
            path.write_text(version)
            records[path] = dict(name='snodec', version=version, arch='amd64')
        before = publish.snapshot(root)
        with patch('coreci.contract.package_metadata', side_effect=lambda path, _: records[path]), \
             patch.object(Path, 'unlink', side_effect=AssertionError('selection must never delete')):
            removed = publish.retention(root, dict(package='snodec', entry=target, version='2.1.0', revision=14),
                                        ['snodec', 'snodec-idp', 'mqttsuite'])
        assert removed == {str(path.relative_to(root)) for path, info in records.items() if info['version'] != '2.1.0-13~stable'}
        assert publish.snapshot(root) == before
    print('retention selection: read-only, reserves hypothetical new publication and keeps newest existing one')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
