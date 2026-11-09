"""The build's real package name survives publisher verification and receipt rendering."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from golden import prepare
from support import entry, environment, replace, rejects
from coreci import native_container, publish, presentation
from coreci.versions import versions
from coreci.contract import file_hash, package_metadata, read_json, write_json

CASES = [('debian',suite,'deb') for suite in ('trixie','forky','sid')]
CASES += [('ubuntu',suite,'deb') for suite in ('noble','resolute')]
CASES += [('raspberrypios',suite,'deb') for suite in ('bookworm','trixie')]
CASES += [('fedora',suite,'rpm') for suite in ('43','44')]
CASES += [('rocky',suite,'rpm') for suite in ('9','10')]


def probe(distribution, suite, fmt, root):
    target=dict(entry(fmt),distribution=distribution,suite=suite,id=distribution+'-'+suite)
    source=root/'source'; out=root/'out'; build=root/'build'; feed=root/'feed'
    source.mkdir(parents=True); out.mkdir(); prepare(feed)
    (source/'payload').write_text('small real package\n')
    (source/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
project(release_probe NONE)
install(FILES payload DESTINATION share/a)
set(CPACK_PACKAGE_NAME a)
set(CPACK_PACKAGE_VERSION 2.1.0)
set(CPACK_DEBIAN_FILE_NAME DEB-DEFAULT)
set(CPACK_RPM_FILE_NAME RPM-DEFAULT)
include(CPack)
''')
    write_json(root/'target.json',target)
    subprocess.run(['cmake','-S',str(source),'-B',str(build)],check=True,capture_output=True)
    with environment(dict(TARGET_JSON=str(root/'target.json'),OUTPUT_DIR=str(out),SOURCE_VERSION='v2.1.0',PACKAGE_REVISION='122')):
        native_container.package(build)
    name=read_json(out/'outputs.json')['packages'][0]['file']
    info=package_metadata(out/name,fmt)
    encoded=versions('v2.1.0',122,fmt,target)
    assert info['version']==encoded['full']
    target['arch']=info['arch']
    manifest=dict(package='a',target=target['id'],version='2.1.0',revision=122,
        build_id='a~'+target['id']+'~2.1.0~r122',entry=target,files={name:file_hash(out/name)},
        source=dict(repository='SNodeC/snode.c',package='a',tag='v2.1.0',commit='a'*40),environment={})
    paths=publish.targets(manifest,out)
    assert list(paths)==[name] and Path(paths[name]).name==name, (name,paths)
    relative,repeated=publish.immutable(feed,manifest,list(paths.values()))
    ledger=feed/relative; ledger.parent.mkdir(parents=True); ledger.write_text(publish.ledger(manifest))
    destination=feed/paths[name]; destination.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(out/name,destination)
    assert name in ledger.read_text() and publish.immutable(feed,manifest,list(paths.values()))==(relative,True)
    conflict=copy.deepcopy(manifest); conflict['files'][name]='f'*64
    rejects(publish.immutable,feed,conflict,list(paths.values()),text='immutable')
    job=dict(name='build',id=1,run_id=2,run_attempt=1,html_url='https://github.com/Example/Recipes/actions/runs/2/job/1')
    values=dict(build_repo='Example/Recipes',build_run_id='2')
    settings=dict(url='https://feed.example/',repository='Example/Feed')
    with environment(dict(GITHUB_REPOSITORY='Example/Recipes',GITHUB_RUN_ID='3')), \
         replace(presentation,'api',lambda *args:dict(jobs=[job])), \
         replace(presentation,'metadata',lambda *args:dict(default_branch='main')):
        receipt=presentation.receipt(feed,manifest,values,settings,paths)
    assert read_json(feed/receipt)['packages'][0]['version']==encoded['full']
    presentation.render(feed)
    context=json.loads((feed/'status.json').read_text())
    project=next(item for item in context['projects'] if item['repository']=='SNodeC/snode.c')
    assert encoded['full'] in (feed/project['status_path']).read_text()
    print(distribution,suite,name,'build = publisher = receipt = Available:',encoded['full'])
    return None


def main():
    with tempfile.TemporaryDirectory() as directory:
        for distribution,suite,fmt in CASES:
            probe(distribution,suite,fmt,Path(directory)/(distribution+'-'+suite))
    for fmt in ('deb','rpm','ipk','apk'):
        target=dict(entry(fmt),suite='44' if fmt=='rpm' else 'trixie')
        encoded=versions('v2.1.0-rc.1+meta',123,fmt,target)
        assert 'meta' not in encoded['full']
        assert ('_pre0_p' in encoded['version']) if fmt=='apk' else ('~p' in encoded['version'])
        if fmt in ('ipk','apk'):
            assert encoded['release']=='r123'
    subprocess.run(['dpkg','--compare-versions','2.1.0-122~trixie','gt','2.1.0-121'],check=True)
    for new in ('2.1.0-122.fc44','2.1.0-122.el9'):
        compared=subprocess.check_output(['rpm','--eval','%{lua:print(rpm.vercmp("'+new+'","2.1.0-121"))}'],text=True).strip()
        assert compared=='1', compared
    assert versions('2.1.0',123,'deb',dict(entry(),suite='trixie'))['full']=='2.1.0-123~trixie'
    print('release formats: every native distribution, all four formats, prereleases, immutable replay/conflict and dpkg/rpm ordering passed')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
