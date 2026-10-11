<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->
<a id="page-overview"></a>

[![Packages](media/page-banner.svg)](../README.md#project-overview)

# OpenWrt

<p>
<a href="#requirements"><img src="media/menu/requirements.svg" alt="Requirements"></a>
<a href="#quick-install"><img src="media/menu/install.svg" alt="Install"></a>
<a href="#manual-repository-setup"><img src="media/menu/manual.svg" alt="Manual setup"></a>
<a href="#updates"><img src="media/menu/updates.svg" alt="Updates"></a>
<a href="../status/README.md#page-overview"><img src="media/menu/status.svg" alt="Status"></a>
<a href="#troubleshooting"><img src="media/menu/troubleshoot.svg" alt="Troubleshoot"></a>
</p>

## Requirements

Supported releases: `24.10`, `25.12`. Match the release and package architecture installed on your device. Keep official feeds enabled for dependencies.

Use official OpenWrt and log in as `root`. A matching CPU does not establish compatibility with a manufacturer’s modified firmware. Install CA certificates and provide HTTPS-capable `wget` (or `curl` for the installer’s downloads).

```sh
cat /etc/openwrt_release
. /etc/openwrt_release
printf 'OpenWrt: %s\nPackage architecture: %s\n' "$DISTRIB_RELEASE" "$DISTRIB_ARCH"
```

Use `DISTRIB_ARCH`, not `uname -m`. Several devices can share a package architecture. OpenWrt 24.10 uses `opkg`/IPK; 25.12 uses `apk`/APK.

## Quick install

```sh
wget -O /tmp/snodec-install-feed.sh \
  https://raw.githubusercontent.com/SNodeC/Packages/main/install/install.sh &&
sh /tmp/snodec-install-feed.sh
```

The installer detects the distribution, release and package architecture, checks that an index exists, installs the signing key, configures the feed and installs the complete package set. Configure applications before starting them. Prefer manual setup? Use [Manual repository setup](#manual-repository-setup).

## Choose packages

See the [SNode.C catalog](snodec-package-options.md#page-overview) and [MQTTSuite catalog](mqttsuite-package-options.md#page-overview) for package roles and after-install configuration.

Prepare the feed without installing packages:

```sh
wget -O /tmp/snodec-install-feed.sh \
  https://raw.githubusercontent.com/SNodeC/Packages/main/install/install.sh &&
sh /tmp/snodec-install-feed.sh --prepare
```

For only the broker and command-line client:

```sh
# OpenWrt 24.10
opkg install mqttsuite-broker mqttsuite-cli
```

```sh
# OpenWrt 25.12
apk add mqttsuite-broker mqttsuite-cli
```

Dependencies are installed automatically. For the full selection after manual preparation, install the complete-project packages in the project catalogs.

Full catalogs: [SNode.C](snodec-package-options.md#page-overview) and [MQTTSuite](mqttsuite-package-options.md#page-overview).

```sh
# OpenWrt 24.10: full selection
opkg install snodec mqttsuite
```

```sh
# OpenWrt 25.12: full selection
apk add snodec mqttsuite
```

## Updates

```sh
# OpenWrt 24.10
opkg update
opkg list-upgradable
```

```sh
# OpenWrt 25.12
apk update
apk list --upgradable
```

Update selected packages with `opkg upgrade <package> ...` or `apk upgrade <package> ...`. Review related library and application updates together. This does not upgrade firmware. After changing OpenWrt release series, configure the matching feed again.

## Manual repository setup

Run the block for your release as `root`. These commands only configure the feed and refresh its index; package installation is a separate step. Existing feeds are preserved. The public keys can also be inspected in [keys](../keys).

### OpenWrt 24.10: opkg

```sh
(
  set -eu
  . /etc/openwrt_release
  case "$DISTRIB_RELEASE" in 24.10.*) ;; *) echo 'Requires OpenWrt 24.10'; exit 1 ;; esac
  base=https://raw.githubusercontent.com/SNodeC/Packages/main
  feed="$base/openwrt/24.10/$DISTRIB_ARCH"
  # Check that this exact feed exists; set -e stops setup if the download fails.
  wget -O /tmp/snodec-feed-build.json "$feed/build.json"
  wget -O /tmp/snodec-usign.pub "$base/keys/snodec-usign.pub"
  opkg-key add /tmp/snodec-usign.pub
  touch /etc/opkg/customfeeds.conf
  sed -i '/^src\/gz snodec /d' /etc/opkg/customfeeds.conf
  printf 'src/gz snodec %s\n' "$feed" >> /etc/opkg/customfeeds.conf
  opkg update
)
```

### OpenWrt 25.12: apk

```sh
(
  set -eu
  . /etc/openwrt_release
  case "$DISTRIB_RELEASE" in 25.12.*) ;; *) echo 'Requires OpenWrt 25.12'; exit 1 ;; esac
  base=https://raw.githubusercontent.com/SNodeC/Packages/main
  feed="$base/openwrt/25.12/$DISTRIB_ARCH"
  # Check that this exact feed exists; set -e stops setup if the download fails.
  wget -O /tmp/snodec-feed-build.json "$feed/build.json"
  wget -O /tmp/snodec-apk.pem "$base/keys/snodec-apk.pem"
  mkdir -p /etc/apk/keys /etc/apk/repositories.d
  cp /tmp/snodec-apk.pem /etc/apk/keys/snodec-apk.pem
  printf '%s/packages.adb\n' "$feed" > /etc/apk/repositories.d/snodec.list
  apk update
)
```

### Example: GL.iNet GL-MT3000 running official OpenWrt

This device uses `aarch64_cortex-a53`.

On **24.10**, the entry in `/etc/opkg/customfeeds.conf` is:

```text
src/gz snodec https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/aarch64_cortex-a53
```

On **25.12**, `/etc/apk/repositories.d/snodec.list` contains:

```text
https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/aarch64_cortex-a53/packages.adb
```

Import the corresponding signing key as shown above. For other devices, use their `DISTRIB_ARCH`; each architecture has its own directory. After an OpenWrt release-series upgrade, reconfigure this feed for the new series.

Then [choose packages](#choose-packages) to install.

## Source records

Source recipes: [SNode.C](https://github.com/SNodeC/snode.c/tree/master/supplement/openwrt) and [MQTTSuite](https://github.com/SNodeC/mqttsuite/tree/master/misc/openwrt).

Both releases support the same platform variants. RISC-V is named `riscv64_riscv64` on 24.10 and `riscv64_generic` on 25.12.

See [per-project availability and source records](../status/README.md#page-overview) for every release and architecture.

## Troubleshooting

See [common problems and fixes](troubleshooting.md#page-overview) for download, signature, dependency and application errors.

| Symptom | What to check |
| --- | --- |
| Architecture looks right but packages fail on vendor firmware | Use official OpenWrt with the matching release and `DISTRIB_ARCH`; matching CPU names alone are insufficient. |
| Service does not start | Inspect `logread -e mqttbroker` and the application configuration before enabling its procd service. |
