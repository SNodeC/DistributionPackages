#!/bin/sh
# Run explicitly on the installation device; CI does not configure owned devices.
set -eu
usage() {
    echo "Usage: $0 --project PROJECT [--component NAME ...] [--suite SUITE]"
    echo "       $0 --prepare [--suite SUITE]"
    echo 'Projects: snodec, mqttsuite, snodec-idp. No implicit ecosystem installation.'
    echo 'Components: package suffixes; all selects the snodec or mqttsuite metapackage.'
    echo 'IDP components: server, client-dev, server-dev, example.'
    echo 'Defaults: snodec/mqttsuite all; snodec-idp server.'
    echo '--prepare: configure the signed repository and refresh indexes only.'
    echo '--suite: explicitly select the installed release (e.g. Debian sid).'
}
prepare=false
suite=
project=
components=
[ "$#" -gt 0 ] || { usage; exit 0; }
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prepare) prepare=true ;;
        --project|--component|--suite)
            [ "$#" -ge 2 ] && [ -n "$2" ] || { usage >&2; exit 2; }
            case "$1" in
                --project) [ -z "$project" ] || { echo 'Select exactly one project.' >&2; exit 2; }; project=$2 ;;
                --component)
                    case "$2" in *[!a-z0-9-]*) echo 'Invalid component name.' >&2; exit 2 ;; esac
                    components="$components $2" ;;
                --suite) suite=$2 ;;
            esac
            shift ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
    shift
done
if [ "$prepare" = true ]; then
    [ -z "$project$components" ] || { echo '--prepare cannot select a project or components.' >&2; exit 2; }
else
    case "$project" in
        snodec|mqttsuite) components=${components:-all} ;;
        snodec-idp) components=${components:-server} ;;
        *) echo 'Select --project snodec, mqttsuite or snodec-idp.' >&2; exit 2 ;;
    esac
fi
set --
for component in $components; do
    case "$project:$component" in
        snodec:all|mqttsuite:all) set -- "$@" "$project" ;;
        snodec-idp:server) set -- "$@" snodec-idp ;;
        snodec-idp:client-dev|snodec-idp:server-dev|snodec-idp:example) set -- "$@" "$project-$component" ;;
        mqttsuite:broker|mqttsuite:cli|mqttsuite:bridge|mqttsuite:integrator|mqttsuite:store|mqttsuite:mapping-double|mqttsuite:mapping-storage)
            set -- "$@" "$project-$component" ;;
        snodec:apps|snodec:common|snodec:control|snodec:core|\
        snodec:core-mux-epoll|snodec:core-mux-poll|snodec:core-mux-select|snodec:core-socket|\
        snodec:core-socket-stream|snodec:core-socket-stream-legacy|snodec:core-socket-stream-tls|snodec:db-mariadb|\
        snodec:http|snodec:http-client|snodec:http-server|snodec:http-server-express|\
        snodec:http-server-express-legacy-in|snodec:http-server-express-legacy-in6|snodec:http-server-express-legacy-rc|snodec:http-server-express-legacy-un|\
        snodec:http-server-express-tls-in|snodec:http-server-express-tls-in6|snodec:http-server-express-tls-rc|snodec:http-server-express-tls-un|\
        snodec:logger|snodec:mqtt|snodec:mqtt-client|snodec:mqtt-client-websocket|\
        snodec:mqtt-server|snodec:mqtt-server-websocket|snodec:net|snodec:net-in|\
        snodec:net-in-phy|snodec:net-in-phy-stream|snodec:net-in-stream|snodec:net-in-stream-legacy|\
        snodec:net-in-stream-tls|snodec:net-in6|snodec:net-in6-phy|snodec:net-in6-phy-stream|\
        snodec:net-in6-stream|snodec:net-in6-stream-legacy|snodec:net-in6-stream-tls|snodec:net-l2|\
        snodec:net-l2-phy|snodec:net-l2-phy-stream|snodec:net-l2-stream|snodec:net-l2-stream-legacy|\
        snodec:net-l2-stream-tls|snodec:net-rc|snodec:net-rc-phy|snodec:net-rc-phy-stream|\
        snodec:net-rc-stream|snodec:net-rc-stream-legacy|snodec:net-rc-stream-tls|snodec:net-un|\
        snodec:net-un-dgram|snodec:net-un-phy|snodec:net-un-phy-stream|snodec:net-un-stream|\
        snodec:net-un-stream-legacy|snodec:net-un-stream-tls|snodec:utils|snodec:websocket|\
        snodec:websocket-client|snodec:websocket-server)
            set -- "$@" "$project-$component" ;;
        *) echo "Unsupported component for $project: $component" >&2; exit 2 ;;
    esac
done
[ "$(id -u)" = 0 ] || { echo 'Run as root (or with sudo).' >&2; exit 1; }
if [ -f /etc/openwrt_release ]; then
    . /etc/openwrt_release
    [ "$project" != snodec-idp ] || { echo 'SNode.C IDP packages are not available for OpenWrt.' >&2; exit 2; }
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
    opkg) url=$url/$suite/$arch; metadata=$url/Packages.gz; key=snodec-opkg.pub ;;
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
name=SNode.C Packages
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
    apt) apt-get install -y "$@" ;;
    dnf) dnf install -y "$@" ;;
    opkg) opkg install "$@" ;;
    apk) apk add "$@" ;;
esac
