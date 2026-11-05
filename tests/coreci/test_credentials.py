from pathlib import Path
import re
import stat
import tempfile
from support import ROOT, environment, registry_data, replace
from coreci import publish


def main():
    names = ('APT_SIGNING_KEY', 'PACKAGES_GPG_PASSPHRASE', 'OPENWRT_USIGN_KEY', 'OPENWRT_APK_KEY')
    old = (ROOT / '.github/workflows/core-ci-publish.yml').read_text()
    workflow = (ROOT / '.github/workflows/coreci-publish.yml').read_text()
    writer = workflow.split('      - id: writer\n', 1)[1].split('      - id: publish\n', 1)[0]
    major = re.search(r'uses: actions/create-github-app-token@[^\s]+ # (v\d+)', old)[1]
    assert f'uses: actions/create-github-app-token@{major}' in writer
    for name in names:
        assert '${{ secrets.' + name + ' }}' in workflow, f'missing environment signing secret {name}'
        assert 'secrets.' + name in old, f'credential name differs from old publisher: {name}'
    assert 'app-id: ${{ vars.FEED_WRITER_APP_ID }}' in writer
    assert 'private-key: ${{ secrets.PACKAGES_APP_PRIVATE_KEY }}' in writer
    assert 'owner: ${{ needs.resolve.outputs.owner }}' in writer
    assert 'repositories: ${{ needs.resolve.outputs.repository_name }}' in writer
    assert 'permission-contents: write' in writer
    assert 'GH_TOKEN: ${{ steps.writer.outputs.token }}' in workflow
    assert workflow.count('secrets.PACKAGES_APP_PRIVATE_KEY') == 1
    assert 'GITHUB_TOKEN: ${{ github.token }}' in workflow
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        fixtures = {name: 'fixture-only-' + name for name in names}
        with environment(fixtures):
            with publish.secrets(work) as files:
                assert set(files) == set(names)
                for name, path in files.items():
                    assert path.read_text() == fixtures[name]
                    assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert not list(work.iterdir()), 'temporary signing files must be removed'
    settings = registry_data()
    settings['feeds']['test']['repository'] = 'Another-Owner/Packages-staging'
    captured = {}
    with environment({'GITHUB_REPOSITORY': 'Example/Recipes',
                      'GITHUB_WORKFLOW_REF': 'Example/Recipes/.github/workflows/coreci-publish.yml@refs/heads/test'}), \
         replace(publish, 'inputs', lambda _: {}), \
         replace(publish, 'registry', lambda: settings), \
         replace(publish, 'checked_manifest', lambda *args: {'feed': 'test'}), \
         replace(publish, 'metadata', lambda _: {'default_branch': 'feed-branch'}), \
         replace(publish, 'github_outputs', lambda **values: captured.update(values)):
        publish.resolve('unused-artifact-root')
    assert captured == dict(environment='staging', repository='Another-Owner/Packages-staging',
                            branch='feed-branch', owner='Another-Owner', repository_name='Packages-staging')
    print('credentials: existing names, private-file lifecycle and feed-only App-token wiring passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
