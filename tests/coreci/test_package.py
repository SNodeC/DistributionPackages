import os
from pathlib import Path
import subprocess
import tempfile
from support import entry, environment, replace
from coreci import common
from coreci.native_container import package
from coreci.contract import package_metadata, read_json
from coreci.versions import versions


def probe(fmt):
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        source=root/'source'
        build=root/'build'
        out=root/'out'
        source.mkdir()
        out.mkdir()
        (source/'payload').write_text('test payload\n')
        (source/'PackageConfig.cmake').write_text(
            'set(CPACK_DEBIAN_FULL_PACKAGE_DEPENDS "a-common (= ${CPACK_PACKAGE_VERSION})")\n'
            'set(CPACK_RPM_FULL_PACKAGE_REQUIRES "a-common = ${CPACK_PACKAGE_VERSION}-${CPACK_RPM_PACKAGE_RELEASE}")\n')
        (source/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
project(coreci_package_probe NONE)
install(FILES payload DESTINATION share/a COMPONENT common)
install(FILES payload DESTINATION share/a/full COMPONENT full)
set(CPACK_PACKAGE_NAME a)
set(CPACK_PACKAGE_VERSION 1.0.0)
set(CPACK_DEB_COMPONENT_INSTALL ON)
set(CPACK_RPM_COMPONENT_INSTALL ON)
set(CPACK_COMPONENTS_GROUPING IGNORE)
set(CPACK_DEBIAN_FULL_PACKAGE_NAME a)
set(CPACK_RPM_FULL_PACKAGE_NAME a)
set(CPACK_OUTPUT_FILE_PREFIX "${CMAKE_BINARY_DIR}/configured-output")
set(CPACK_PROJECT_CONFIG_FILE "${CMAKE_CURRENT_SOURCE_DIR}/PackageConfig.cmake")
include(CPack)
''')
        target=root/'target.json'
        common.write_json(target,entry(fmt))
        subprocess.run(['cmake','-S',str(source),'-B',str(build)],check=True,capture_output=True)
        with environment(dict(TARGET_JSON=str(target),OUTPUT_DIR=str(out),SOURCE_VERSION='v1.0.0-alpha+build',PACKAGE_REVISION='7')):
            package(build)
        outputs=read_json(out/'outputs.json')
        assert len(outputs['packages'])==2
        assert {item['component'] for item in outputs['packages']} == {'a', 'a-common'}
        for item in outputs['packages']:
            data=package_metadata(out/item['file'],fmt)
            encoded=versions('v1.0.0-alpha+build',7,fmt,entry(fmt))['full']
            assert data['name']==item['component'] and data['version']==encoded
            if data['name']=='a':
                assert encoded in str(data['dependencies']) and 'a-common' in str(data['dependencies'])
    return 0


def main():
    probe('deb')
    probe('rpm')
    print('package: native CPack helper produced and inspected real unsigned deb/rpm components with exact versioned component dependencies')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
