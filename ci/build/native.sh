#!/usr/bin/env bash
# Runs inside the target distribution, natively or under QEMU.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
cd /work
case "${DISTRIBUTION:-raspberrypios}" in
    raspberrypios|debian|ubuntu)
        format=DEB
        libdir=lib
        apt-get update
        apt-get install -y build-essential cmake ninja-build pkg-config git ca-certificates adduser passwd util-linux libbluetooth-dev \
            libmagic-dev libmariadb-dev libssl-dev libncurses-dev nlohmann-json3-dev file
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
            json-devel file rpm-build shadow-utils util-linux
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
    local options=()
    if [ "$format" = DEB ]; then
        options=(-D "CPACK_PACKAGE_VERSION=$version-$PACKAGE_RELEASE~$SUITE")
    else
        local suffix=fc
        [ "$DISTRIBUTION" != rocky ] || suffix=el
        options=(-D "CPACK_RPM_PACKAGE_RELEASE=$PACKAGE_RELEASE.$suffix$SUITE")
    fi
    (cd "$build" && cpack -G "$format" "${options[@]}")
    cp "$build"/_packages/*."${format,,}" "$build"/_packages/*.packages packages/
}
if [ "$BUILD_PROJECT" = mqttsuite ]; then
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
if [ "$format" = DEB ]; then
    apt-get install -y /work/packages/*.deb
else
    dnf install -y /work/packages/*.rpm
fi
ldconfig
useradd --system --user-group --create-home snodec-test
if [ "$BUILD_PROJECT" = snode.c ]; then
    chown -R snodec-test:snodec-test build-snodec
    runuser -u snodec-test -- ctest --test-dir build-snodec --output-on-failure
    find dependencies -maxdepth 1 -type f -exec cp -t packages {} +
    exit 0
fi
cmake -S sources/mqttsuite -B build-mqttsuite -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_INSTALL_LIBDIR="$libdir" -DCMAKE_INSTALL_SYSCONFDIR=/etc
cmake --build build-mqttsuite --parallel 4
package build-mqttsuite
