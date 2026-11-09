from pathlib import Path
import tempfile
from support import entry, environment
from coreci import publish


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        target = entry('ipk')
        target.update(family='openwrt', distribution='openwrt', suite='24.10')
        exports = root / 'dev' / target['id']
        exports.mkdir(parents=True)
        names = ['notes.txt', 'snodec_notes.tar.gz', 'snodec_1.0.0-alpha.01-r3.tar.gz',
                 'snodec_1.0.0-r18446744073709551616.tar.gz', 'foreign_1.0.0-r1.tar.gz']
        protected = names + ['SHA256SUMS', 'SHA256SUMS.asc', 'mqttsuite_1.0.0-r1.tar.gz']
        for name in protected:
            (exports / name).write_text('preserve ' + name)
        for revision in (1, 2, 3):
            (exports / f'snodec_1.0.0-r{revision}.tar.gz').write_text('export')
        before = {name: (exports / name).read_bytes() for name in protected}
        summary = root / 'summary'
        with environment({'GITHUB_STEP_SUMMARY': str(summary)}):
            removed = publish.retention(root, dict(package='snodec', entry=target), ['snodec', 'snodec-idp', 'mqttsuite'])
        assert removed == {f'dev/{target["id"]}/snodec_1.0.0-r1.tar.gz'}
        assert all((exports / name).read_bytes() == contents for name, contents in before.items())
        assert all(name in summary.read_text() for name in names)
        assert 'mqttsuite_1.0.0-r1.tar.gz' not in summary.read_text()
    print('retention unknown files: malformed/unknown exports preserved and summarized; valid foreign exports and indices preserved')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
