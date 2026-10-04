#!/usr/bin/env bash
# Build and run upstream tests in the official image filesystem.
set -euo pipefail
suite=$1
work=$(pwd)
root=$(mktemp -d)
enter=(sudo unshare --mount --pid --fork --kill-child --mount-proc="$root/proc" chroot "$root")
mkdir -p "$root" pi-image output logs
readarray -t image < <(python3 - "$suite" <<'PY'
import json, sys
row = json.load(open('feed/ci/targets/raspberrypi.json'))[sys.argv[1]]
print(row['url'])
print(row['sha256'])
PY
)
curl --fail --location --retry 3 "${image[0]}" -o pi.img.xz
printf '%s  pi.img.xz\n' "${image[1]}" | sha256sum -c -
xz -d pi.img.xz
loop=$(sudo losetup --find --show --partscan pi.img)
cleanup() {
    sudo umount -R "$root/dev" 2>/dev/null || true
    for mount in sys work; do sudo umount "$root/$mount" 2>/dev/null || true; done
    sudo umount pi-image 2>/dev/null || true
    sudo losetup -d "$loop" 2>/dev/null || true
}
trap cleanup EXIT
sudo mount -o ro "${loop}p2" pi-image
sudo cp -a pi-image/. "$root/"
sudo rm -f "$root/etc/resolv.conf"
sudo cp /etc/resolv.conf "$root/etc/resolv.conf"
sudo mkdir -p "$root/work"
sudo mount --bind "$work" "$root/work"
sudo mount -t sysfs sysfs "$root/sys"
sudo mount --rbind /dev "$root/dev"
sudo mount --make-rslave "$root/dev"
printf '#!/bin/sh\nexit 101\n' | sudo tee "$root/usr/sbin/policy-rc.d" >/dev/null
sudo chmod +x "$root/usr/sbin/policy-rc.d"
"${enter[@]}" sh -c '. /etc/os-release; test "$VERSION_CODENAME" = "$1"; test "$(dpkg --print-architecture)" = arm64' sh "$suite"
"${enter[@]}" env PACKAGE_RELEASE="$PACKAGE_RELEASE" SUITE="$suite" BUILD_PROJECT="${BUILD_PROJECT:-}" \
    bash /work/feed/ci/build/native.sh 2>&1 | tee logs/build.log
python3 -m ci.publish.apt stage "$suite" packages bundle output
sudo umount -R "$root/dev"
for mount in sys work; do sudo umount "$root/$mount"; done
sudo rm -rf "$root"

sudo chown -R "$(id -u):$(id -g)" output logs
