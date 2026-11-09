import json
from pathlib import Path
import re
from unittest.mock import patch
from support import ROOT
from coreci import sdk


FIXTURE = Path(__file__).parent / 'fixtures/emulation'


def rows():
    targets = json.loads((FIXTURE / 'targets.json').read_text())
    binaries = dict(re.findall(r'^\t"([^"]+)": \{\n\t\tbinary: "([^"]+)"', (FIXTURE / 'binfmt-config.go').read_text(), re.M))
    image = json.loads((FIXTURE / 'image.json').read_text())
    supported = {key for key, binary in binaries.items() if 'usr/bin/' + binary in image['qemu_members']}
    workflow = (ROOT / '.github/workflows/coreci-publish.yml').read_text()
    ubuntu = json.loads(re.search(r"UBUNTU_EMULATORS: '([^']+)'", workflow)[1])
    expected = {'arm': 'arm', 'aarch64': 'arm64', 'i386': '386', 'x86': '',
                'mips': 'mips', 'mipsel': 'mipsel', 'mips64': 'mips64',
                'powerpc': 'ppc', 'loongarch64': 'loong64', 'riscv64': 'riscv64'}
    result = []
    assert len(targets) == 76 and len({target['id'] for target in targets}) == 76
    for target in targets:
        values = []
        for publishing in (False, True):
            host = 'x86_64' if publishing or not target['runner'].endswith('-arm') else 'aarch64'
            captured = {}
            document = {'entry': target} if publishing else {'matrix': [target]}
            with patch.object(sdk, 'read_json', return_value=document), \
                 patch.object(sdk, 'inputs', return_value={'target': target['id']}), \
                 patch.object(sdk.platform, 'machine', return_value=host), \
                 patch.object(sdk, 'github_outputs', side_effect=lambda **fields: captured.update(fields)), \
                 patch.object(sdk, 'sdk', side_effect=ValueError('stop before SDK metadata')):
                try:
                    sdk.cache('manifest' if publishing else None)
                except ValueError as error:
                    assert target['family'] == 'openwrt' and str(error) == 'stop before SDK metadata'
            value = captured['emulator']
            if target['family'] == 'openwrt':
                assert value == (expected[target['arch'].split('_')[0]] if publishing else '')
            else:
                arch = target['build']['platform'].split('/')[1]
                assert value == ('' if (host, arch) in (('x86_64', 'amd64'), ('aarch64', 'arm64')) else arch)
            assert not value or value in supported or value in ubuntu, (target['id'], value)
            assert publishing or not value or value in supported, 'build workflow has no unsupported installer path'
            values.append(value)
        result.append(dict(target=target['id'], build=values[0], publish=values[1],
                           build_supported=values[0] in supported if values[0] else None,
                           publish_supported=values[1] in supported if values[1] else None))
    assert set(ubuntu) == {'mips', 'mipsel', 'ppc'}
    assert all(value not in supported for value in ubuntu)
    assert 'multiarch/' not in workflow and '--privileged' not in workflow
    assert 'sudo update-binfmts --disable' in workflow
    assert 'sudo update-binfmts --enable qemu-${{ steps.sdk.outputs.emulator }}' in workflow
    return result


def main():
    result = rows()
    print('emulation catalog: all', len(result), 'targets covered for build and publish; supported image binaries or Ubuntu fallback, no own-architecture registration')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
