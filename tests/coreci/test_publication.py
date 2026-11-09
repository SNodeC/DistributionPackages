import copy
from pathlib import Path
import subprocess
import tempfile
from support import rejects, registry_data, entry, replace
from coreci import publish
from coreci.contract import file_hash


def main():
    manifest = dict(package='a', target='t1', version='1.0.0', revision=3, files={'a.deb':'0'*64})
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path, repeated = publish.immutable(root, manifest, ['debian/pool/stable/a.deb'])
        assert not repeated
        ledger = root/path
        ledger.parent.mkdir(parents=True)
        ledger.write_text(publish.ledger(manifest))
        file = root/'debian/pool/stable/a.deb'
        file.parent.mkdir(parents=True)
        file.write_bytes(b'existing unsigned or signed file')
        assert publish.immutable(root, manifest, ['debian/pool/stable/a.deb']) == (path, True)
        changed = copy.deepcopy(manifest)
        changed['files']['a.deb'] = '1'*64
        rejects(publish.immutable, root, changed, ['debian/pool/stable/a.deb'], text='immutable')
        ledger.unlink()
        rejects(publish.immutable, root, manifest, ['debian/pool/stable/a.deb'], text='immutable')
        subprocess.run(['git','init','-q',str(root)],check=True)
        subprocess.run(['git','-C',str(root),'add','.'],check=True)
        subprocess.run(['git','-C',str(root),'-c','user.name=Test','-c','user.email=test@example.invalid',
                        'commit','-qm','baseline'],check=True)
        file2=root/'new.txt'
        file2.write_text('new bytes')
        base = publish.prepare_commit(root, {'new.txt'}, orphan=True)
        head = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
        assert head != base
        parents = subprocess.check_output(['git','-C',str(root),'rev-list','--parents','-n1','HEAD'],text=True).split()
        assert parents == [head], f'expected orphan root, got {parents}'
        assert file.read_bytes() == b'existing unsigned or signed file'
    definitions = [dict(package='z',matrix=[dict(id='t2'),dict(id='t1')]), dict(package='a',matrix=[dict(id='t1')])]
    readme = '# Feed\n'
    rendered = publish.badges(readme, registry_data(), definitions)
    assert rendered.startswith('# Feed\n\n<!-- coreci:badges:begin -->\n')
    assert rendered.index('| t1 |') < rendered.index('| t2 |')
    assert rendered.index('![a]') < rendered.index('![z]')
    assert publish.badges(rendered, registry_data(), definitions) == rendered
    surrounded='before\n'+rendered[rendered.index('<!--'):]+ '\nafter\n'
    assert publish.badges(surrounded, registry_data(), definitions).endswith('\nafter\n')
    for text in ['<!-- coreci:badges:begin -->', '<!-- coreci:badges:end --><!-- coreci:badges:begin -->']:
        rejects(publish.badges,text,registry_data(),definitions)
    print('publication: immutable retries/conflicts, orphan commit and badge preservation passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
