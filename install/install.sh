#!/bin/sh
# Run explicitly on the installation device; CI does not configure owned devices.
set -eu
usage() {
    echo "Usage: $0 [--prepare] [--suite SUITE]"
    echo 'Default: configure the signed repository and install all components.'
    echo '--prepare: configure the repository and refresh indexes only.'
    echo '--suite: explicitly select the installed release (e.g. Debian sid).'
}
prepare=false
suite=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prepare) prepare=true ;;
        --suite) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; suite=$2; shift ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
    shift
done
[ "$(id -u)" = 0 ] || { echo 'Run as root (or with sudo).' >&2; exit 1; }
if [ -f /etc/openwrt_release ]; then
    . /etc/openwrt_release
    distribution=openwrt
    suite=${suite:-$DISTRIB_RELEASE}
    arch=$DISTRIB_ARCH
    case "$suite" in
        24.10|24.10.*|24.10-*) suite=24.10; manager=opkg ;;
        25.12|25.12.*|25.12-*) suite=25.12; manager=apk ;;
        *) echo "Unsupported OpenWrt release: $suite" >&2; exit 1 ;;
    esac
else
    . /etc/os-release
    distribution=$ID
    # Official 64-bit Raspberry Pi OS identifies as Debian in os-release.
    if [ -f /etc/rpi-issue ]; then distribution=raspberrypios; fi
    case "$distribution" in
        debian|ubuntu|raspberrypios)
            manager=apt
            suite=${suite:-${VERSION_CODENAME:-}}
            arch=$(dpkg --print-architecture)
            ;;
        rocky|fedora)
            manager=dnf
            suite=${suite:-${VERSION_ID%%.*}}
            arch=$(rpm --eval '%{_arch}')
            ;;
        *) echo "Unsupported distribution: $distribution" >&2; exit 1 ;;
    esac
fi
case "$suite" in ''|*[!a-zA-Z0-9._-]*) echo 'Cannot determine release; use --suite for the installed release.' >&2; exit 1 ;; esac
case "$arch" in ''|*[!a-zA-Z0-9_-]*) echo 'Invalid package architecture' >&2; exit 1 ;; esac
base=https://raw.githubusercontent.com/SNodeC/Packages/main
url=$base/$distribution
case "$manager" in
    apt) metadata=$url/dists/$suite/main/binary-$arch/Packages.gz; key=snodec-apt.asc ;;
    dnf) url=$url/$suite/$arch; metadata=$url/repodata/repomd.xml; key=snodec-apt.asc ;;
    opkg) url=$url/$suite/$arch; metadata=$url/Packages.gz; key=snodec-usign.pub ;;
    apk) url=$url/$suite/$arch; metadata=$url/packages.adb; key=snodec-apk.pem ;;
esac
fetch() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$1" -o "$2"
    else
        wget -q -O "$2" "$1"
    fi
}
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM
# Verify this exact release/architecture exists before changing configuration.
fetch "$metadata" "$temporary/index"
fetch "$base/keys/$key" "$temporary/key"
printf 'Configuring %s %s (%s)\n' "$distribution" "$suite" "$arch"
case "$manager" in
    apt)
        install -d -m 755 /etc/apt/keyrings /etc/apt/sources.list.d
        install -m 644 "$temporary/key" /etc/apt/keyrings/snodec.asc
        printf 'deb [arch=%s signed-by=/etc/apt/keyrings/snodec.asc] %s %s main\n' "$arch" "$url" "$suite" > /etc/apt/sources.list.d/snodec.list
        apt-get update
        ;;
    dnf)
        install -d -m 755 /etc/pki/rpm-gpg /etc/yum.repos.d
        install -m 644 "$temporary/key" /etc/pki/rpm-gpg/RPM-GPG-KEY-snodec
        rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-snodec
        cat > /etc/yum.repos.d/snodec.repo <<REPO
[snodec]
name=SNode.C and MQTTSuite
baseurl=$url/
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-snodec
REPO
        dnf makecache
        ;;
    opkg)
        opkg-key add "$temporary/key"
        touch /etc/opkg/customfeeds.conf
        sed -i '/^src\/gz snodec /d' /etc/opkg/customfeeds.conf
        printf 'src/gz snodec %s\n' "$url" >> /etc/opkg/customfeeds.conf
        opkg update
        ;;
    apk)
        mkdir -p /etc/apk/keys /etc/apk/repositories.d
        cp "$temporary/key" /etc/apk/keys/snodec-apk.pem
        printf '%s/packages.adb\n' "$url" > /etc/apk/repositories.d/snodec.list
        apk update
        ;;
esac
[ "$prepare" = false ] || exit 0
case "$manager" in
    apt) apt-get install -y snodec mqttsuite ;;
    dnf) dnf install -y snodec mqttsuite ;;
    opkg) opkg install mqttsuite-full snode.c-full snode.c-apps snode.c-control ;;
    apk) apk add mqttsuite-full snode.c-full snode.c-apps snode.c-control ;;
esac
