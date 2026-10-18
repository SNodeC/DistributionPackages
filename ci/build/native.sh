#!/usr/bin/env bash
# Runs inside the target distribution, natively or under QEMU.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
cd /work
export PYTHONPATH=/work/feed
case "${DISTRIBUTION:-raspberrypios}" in
    raspberrypios|debian|ubuntu)
        format=DEB
        libdir=lib
        apt-get update
        apt-get install -y build-essential cmake ninja-build pkg-config git ca-certificates adduser passwd util-linux libbluetooth-dev \
            libmagic-dev libmariadb-dev libssl-dev libncurses-dev nlohmann-json3-dev libsqlite3-dev file python3
        ;;
    rocky|fedora)
        format=RPM
        libdir=lib64
        if [ "$DISTRIBUTION" = rocky ]; then
            dnf install -y dnf-plugins-core epel-release
            dnf config-manager --set-enabled crb
        fi
        dnf install -y gcc gcc-c++ cmake ninja-build make pkgconf-pkg-config git ca-certificates \
            bluez-libs-devel file-devel mariadb-connector-c-devel openssl-devel ncurses-devel \
            json-devel sqlite-devel file python3 rpm-build shadow-utils util-linux
        if [ "$DISTRIBUTION:$SUITE" = rocky:9 ]; then
            dnf install -y gcc-toolset-14-gcc-c++
            source /opt/rh/gcc-toolset-14/enable
        fi
        ;;
esac
mkdir -p sources packages
for project in "$BUILD_PROJECT"; do
    mkdir "sources/$project"
    tar -xzf bundle/"$project"-*.tar.gz --strip-components=1 -C "sources/$project"
done
package() {
    local build=$1 version
    version=$(sed -n 's/^set(CPACK_PACKAGE_VERSION "\([^" ]*\)")/\1/p' "$build/CPackConfig.cmake")
    local distribution=${DISTRIBUTION:-raspberrypios}
    version=$(python3 /work/feed/ci/repository.py package-version "$distribution" "$SUITE" "$version" "$PACKAGE_RELEASE")
    local options=(-D "CPACK_PACKAGE_VERSION=$version")
    [ "$format" = DEB ] || options=(-D "CPACK_RPM_PACKAGE_RELEASE=${version#*-}")
    (cd "$build" && cpack -G "$format" "${options[@]}")
    cp "$build"/_packages/*."${format,,}" "$build"/_packages/*.packages packages/
}
if [ "$BUILD_PROJECT" != snode.c ]; then
    cp dependencies/* packages/
else
    cmake -S sources/snode.c -B build-snodec -G Ninja \
        -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
        -DCMAKE_INSTALL_LIBDIR="$libdir" -DCMAKE_INSTALL_SYSCONFDIR=/etc \
        -DSNODEC_BUILD_TESTS=ON -DSNODEC_BUILD_APPS=ON \
        -DSPDLOG_SYSTEM_INCLUDES=ON
    cmake --build build-snodec --parallel 4
    package build-snodec
fi
# Retained sibling artifacts belong in the feed, not in this build's dependencies.
readarray -t framework_packages < <(python3 - <<'PACKAGES'
from pathlib import Path
from ci.repository import project_file
for path in sorted(Path('/work/packages').iterdir()):
    if project_file(path.name, 'snode.c'):
        print(path)
PACKAGES
)
if [ "$format" = DEB ]; then
    apt-get install -y "${framework_packages[@]}"
else
    dnf install -y "${framework_packages[@]}"
fi
ldconfig
useradd --system --user-group --create-home snodec-test
if [ "$BUILD_PROJECT" = snode.c ]; then
    chown -R snodec-test:snodec-test build-snodec
    runuser -u snodec-test -- ctest --test-dir build-snodec --output-on-failure
    find dependencies -maxdepth 1 -type f -exec cp -t packages {} +
    exit 0
fi
options=()
if [ "$BUILD_PROJECT" = snode.c-idp ]; then
    options=(-DAUTH_BUILD_EXAMPLE=ON -DCMAKE_CXX_FLAGS=-Werror)
    revision=$(python3 -c 'import json; refs=json.load(open("bundle/sources.json"))["snode.c-idp"]; print(next((v for k,v in refs.items() if k.endswith("^{}")), next(iter(refs.values()))))')
    options+=("-DAUTH_REVISION=$revision")
fi
cmake -S "sources/$BUILD_PROJECT" -B build-product -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_INSTALL_LIBDIR="$libdir" -DCMAKE_INSTALL_SYSCONFDIR=/etc "${options[@]}"
cmake --build build-product --parallel 4
if [ "$BUILD_PROJECT" = snode.c-idp ]; then
    chown -R snodec-test:snodec-test build-product
    runuser -u snodec-test -- ctest --test-dir build-product --output-on-failure
fi
package build-product
if [ "$BUILD_PROJECT" = snode.c-idp ]; then
    if [ "$format" = DEB ]; then
        printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
        chmod +x /usr/sbin/policy-rc.d
        apt-get install -y /work/packages/snodec-idp*.deb
    else
        dnf install -y /work/packages/snodec-idp*.rpm
    fi
    cmake -S sources/snode.c-idp/tests/live -B build-consumer -G Ninja
    cmake --build build-consumer --parallel 4
    cmake -S sources/snode.c-idp -B build-client -G Ninja -DAUTH_CLIENT_ONLY=ON -DCMAKE_CXX_FLAGS=-Werror
    cmake --build build-client --parallel 4
fi
