from pathlib import Path
import subprocess
import tempfile
from support import registry_data, entry, replace, rejects
from coreci import build
from contract import read_json


def main():
    target=entry()
    doc={'depends_on':['b']}
    other={'package':'b','matrix':[target],'development_packages':{'deb':['b-dev']}}
    settings=registry_data()
    values={'prerequisites':'b=1.2.3-9','recipe_ref':'staging'}
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        def key(feed,kind,path):
            result=path/'test.asc'
            result.write_text('public')
            return result
        with replace(build,'dependency_definitions',lambda *args: {'b':other}), replace(build,'public_key',key):
            instructions=build.dependencies(settings,values,doc,target,{},root)
        metadata=read_json(root/'prerequisites/b/metadata.json')
        assert metadata == dict(package='b',version='1.2.3',revision=9,upstream_version='1.2.3',release='9~stable',target='t1',sdk=None)
        lines=build.install_lines(target,instructions)
        assert all('\n' not in line for line in lines), 'each Dockerfile RUN must occupy one physical line'
        source=subprocess.check_output(['sh','-c',lines[0][4:].rsplit(' > ',1)[0]],text=True)
        assert source == ('deb [signed-by=/inputs/prerequisites/b/test.asc] '
                          'https://feed.example/debian stable main\n')
        commands='\n'.join(lines)
        assert 'b-dev=1.2.3-9~stable' in commands and 'signed-by=/inputs/prerequisites/b/test.asc' in commands
        assert 'dpkg-query' in commands and '1.2.3-9~stable' in commands
        rejects(build.dependencies,settings,dict(values,prerequisites=''),doc,target,{},root,text='do not match')
        rpm=dict(instructions[0],names=['b-devel'],arch='x86_64',distribution='fedora')
        lines=build.install_lines(entry('rpm'),[rpm])
        assert all('\n' not in line for line in lines), 'each Dockerfile RUN must occupy one physical line'
        source=subprocess.check_output(['sh','-c',lines[0][4:].rsplit(' > ',1)[0]],text=True)
        assert source == ('[coreci-0]\nname=coreci\nbaseurl=https://feed.example/fedora/stable/x86_64/\n'
                          'gpgcheck=1\nrepo_gpgcheck=1\ngpgkey=file:///inputs/prerequisites/b/test.asc\n')
        commands='\n'.join(lines)
        assert 'gpgcheck=1' in commands and 'repo_gpgcheck=1' in commands and 'b-devel-1.2.3-9~stable' in commands
    print('prerequisites: exact versions, metadata and repository-signature installation passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
