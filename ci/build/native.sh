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
        apt-get install -y build-essential cmake ninja-build pkg-config git ca-certificates adduser passwd util-linux file python3
        ;;
    rocky|fedora)
        format=RPM
        libdir=lib64
        if [ "$DISTRIBUTION" = rocky ]; then
            dnf install -y dnf-plugins-core epel-release
            dnf config-manager --set-enabled crb
        fi
        dnf install -y gcc gcc-c++ cmake ninja-build make pkgconf-pkg-config git ca-certificates file python3 rpm-build shadow-utils util-linux
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
    local build=$1 version expected
    version=$(sed -n 's/^set(CPACK_PACKAGE_VERSION "\([^" ]*\)")/\1/p' "$build/CPackConfig.cmake")
    expected=$(python3 -c 'import json, os; print(json.load(open("bundle/context.json"))["versions"][os.environ["BUILD_PROJECT"]])')
    [ "$version" = "$expected" ] || { echo "Package version $version differs from captured release $expected" >&2; exit 1; }
    local distribution=${DISTRIBUTION:-raspberrypios}
    version=$(python3 /work/feed/ci/repository.py package-version "$distribution" "$SUITE" "$version" "$PACKAGE_RELEASE")
    local options=(-D "CPACK_PACKAGE_VERSION=$version")
    [ "$format" = DEB ] || options=(-D "CPACK_RPM_PACKAGE_RELEASE=${version#*-}")
    (cd "$build" && cpack -G "$format" "${options[@]}")
    cp "$build"/_packages/*."${format,,}" "$build"/_packages/*.packages packages/
}
# reuse() already verified and selected these prerequisite bytes.
mapfile -t prerequisite_packages < <(find /work/dependencies -maxdepth 1 -type f \( -name '*.deb' -o -name '*.rpm' \) | sort)
install_packages() {
    if [ "$format" = DEB ]; then
        apt-get install -y "$@"
    else
        dnf install -y "$@"
    fi
    ldconfig
    return 0
}
if [ "${#prerequisite_packages[@]}" != 0 ]; then
    install_packages "${prerequisite_packages[@]}"
fi
ldconfig
useradd --system --user-group --create-home snodec-test
source "sources/$BUILD_PROJECT/$(python3 -c 'import os; from ci.repository import PROJECTS; print(PROJECTS[os.environ["BUILD_PROJECT"]]["build"]["native"])')"
find dependencies -maxdepth 1 -type f -exec cp -t packages {} +
