#!/usr/bin/env bash
# Build small signing utilities from audited source, never from upstream build artifacts.
set -euo pipefail
sudo apt-get update
sudo apt-get install -y apt-utils gnupg rpm createrepo-c cmake ninja-build meson gcc pkg-config libssl-dev zlib1g-dev
if [ "$1" != openwrt ]; then exit 0; fi
git clone https://git.openwrt.org/project/usign.git signing-usign
git -C signing-usign checkout c4c72b1b07945ee192361dc751291a7c98d6adcd
cmake -S signing-usign -B signing-usign/build
cmake --build signing-usign/build
sudo install signing-usign/build/usign /usr/local/bin/usign
git clone https://github.com/alpinelinux/apk-tools.git signing-apk
git -C signing-apk checkout b5a31c0d865342ad80be10d68f1bb3d3ad9b0866
meson setup signing-apk/build signing-apk -Ddefault_library=static -Ddocs=disabled -Dtests=disabled -Dpython=disabled -Dlua=disabled -Dzstd=disabled -Durl_backend=wget
meson compile -C signing-apk/build
sudo install signing-apk/build/src/apk /usr/local/bin/apk
