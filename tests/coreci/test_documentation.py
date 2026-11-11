"""Source docs, stale deletion, no-op commits and safe output boundaries."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from support import ROOT, environment, replace, rejects
from coreci import presentation as p


def git(root, *args):
    result = subprocess.check_output(['git', '-C', str(root), *args]).strip()
    return result


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / 'source'
        docs = source / 'site/docs'
        docs.mkdir(parents=True)
        (docs / 'guide.md').write_bytes(b'Authoritative guide\n\n')
        (docs / 'image.png').write_bytes(b'\x89PNG\x00\xff')
        shutil.copytree(ROOT / 'status-templates', source / 'status-templates')
        feed = root / 'feed'
        subprocess.run(['git', 'init', '--quiet', str(feed)], check=True)
        (feed / 'docs').mkdir()
        (feed / 'docs/obsolete.md').write_text('retired')
        (feed / 'package.deb').write_bytes(b'unchanged package')
        git(feed, 'add', '.')
        git(feed, '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
        package = git(feed, 'rev-parse', 'HEAD:package.deb')
        settings = dict(feeds=dict(test=dict(repository='Example/Feed', presentation='Example/Recipes/.github/workflows/coreci-status.yml')))
        pushes = []
        env = dict(INPUT_FEED='test', GH_TOKEN='unit-test-only',
                   GITHUB_WORKFLOW_REF='Example/Recipes/.github/workflows/coreci-status.yml@refs/heads/main')
        with environment(env), replace(p, '__file__', str(source / 'coreci/presentation.py')), \
             replace(p, 'registry', lambda: settings), replace(p, 'metadata', lambda _: dict(default_branch='main')), \
             replace(p, 'refresh', lambda *args: []), replace(p, 'checked_push', lambda *args: pushes.append(git(feed, 'rev-parse', 'HEAD'))), \
             replace(sys, 'argv', ['presentation', 'run', '--root', str(feed)]):
            p.main()
            assert not (feed / 'docs/obsolete.md').exists()
            assert {str(path.relative_to(feed)): path.read_bytes() for path in (feed / 'docs').rglob('*') if path.is_file()} == p.documentation()
            first = git(feed, 'rev-parse', 'HEAD')
            p.main()
            assert git(feed, 'rev-parse', 'HEAD') == first and len(pushes) == 1
            assert git(feed, 'rev-parse', 'HEAD:package.deb') == package
            (docs / 'guide.md').unlink()
            p.main()
            assert not (feed / 'docs/guide.md').exists() and len(pushes) == 2
            outside = root / 'outside'
            outside.write_text('outside bytes')
            (docs / 'unsafe').symlink_to(outside)
            rejects(p.documentation, text='documentation cannot contain links')
            (docs / 'unsafe').unlink()
            (feed / 'docs/image.png').unlink()
            (feed / 'docs/image.png').symlink_to(outside)
            rejects(lambda: p.render(feed), text='unsafe status destination')
            assert outside.read_text() == 'outside bytes'
    print('documentation: exact source bytes, stale deletion, unchanged no-op, package preservation and symlink safety passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
