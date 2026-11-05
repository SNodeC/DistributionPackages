import os
from pathlib import Path
import subprocess
import tempfile
from support import entry, environment, replace
from coreci import common
from native_container import package
from contract import package_metadata, read_json, versions


def probe(fmt):
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        source=root/'source'
        build=root/'build'
        out=root/'out'
        source.mkdir()
        out.mkdir()
        (source/'payload').write_text('test payload\n')
        (source/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
project(coreci_package_probe NONE)
install(FILES payload DESTINATION share/a)
set(CPACK_PACKAGE_NAME a)
set(CPACK_PACKAGE_VERSION 1.0.0)
include(CPack)
''')
        target=root/'target.json'
        common.write_json(target,entry(fmt))
        subprocess.run(['cmake','-S',str(source),'-B',str(build)],check=True,capture_output=True)
        with environment(dict(TARGET_JSON=str(target),OUTPUT_DIR=str(out),SOURCE_VERSION='v1.0.0-alpha+build',PACKAGE_REVISION='7')):
            package(build)
        outputs=read_json(out/'outputs.json')
        assert len(outputs['packages'])==1
        file=out/outputs['packages'][0]['file']
        data=package_metadata(file,fmt)
        assert data['name']=='a' and data['version']==versions('v1.0.0-alpha+build',7,fmt)['full']
        assert outputs['packages'][0]['component']=='a'
    return 0


def main():
    probe('deb')
    probe('rpm')
    print('package: unchanged native CPack helper produced and inspected real unsigned deb and rpm packages at the requested revision')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
