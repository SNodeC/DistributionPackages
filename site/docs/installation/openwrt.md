<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->

<!-- snodec:begin page-header -->
<a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="../media/nav/banner-installation-compact.svg"><img src="../media/nav/banner-installation.svg" alt="Packages — Installation" width="100%"></picture></p>
<p><a href="README.md#page-overview" title="Up to Installation"><picture><source media="(prefers-color-scheme: dark)" srcset="../media/nav/up-installation-dark.svg"><img src="../media/nav/up-installation-light.svg" alt="Up to Installation" title="Up to Installation" width="160" height="28"></picture></a><a href="https://github.com/SNodeC" title="SNodeC organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/organization-dark.svg"><img align="right" src="../media/nav/organization-light.svg" alt="SNodeC organization" title="SNodeC organization"></picture></a><a href="../../README.md#project-overview" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/repository-dark.svg"><img align="right" src="../media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# OpenWrt

<!-- snodec:begin menu -->
<p>
<a href="#requirements"><img src="../media/menu/requirements.svg" alt="Requirements"></a>
<a href="#quick-install"><img src="../media/menu/menu-quick-install.svg" alt="Quick install"></a>
<a href="#choose-packages"><img src="../media/menu/menu-custom-install.svg" alt="Custom install"></a>
<a href="#manual-repository-setup"><img src="../media/menu/manual.svg" alt="Manual setup"></a>
<a href="#updates"><img src="../media/menu/updates.svg" alt="Updates"></a>
<a href="../../status/README.md#page-overview"><img src="../media/menu/status.svg" alt="Status"></a>
<a href="#troubleshooting"><img src="../media/menu/troubleshoot.svg" alt="Troubleshoot"></a>
</p>
<!-- snodec:end menu -->

## Requirements

Supported releases: `24.10`, `25.12`. Match the release and package architecture installed on your device. Keep official feeds enabled for dependencies.

Use official OpenWrt and log in as `root`. For commands shown for both release series, run only the block for your installed series. A matching CPU does not establish compatibility with a manufacturer’s modified firmware. Install CA certificates and provide HTTPS-capable `wget` (or `curl` for the installer’s downloads).

```sh
cat /etc/openwrt_release
. /etc/openwrt_release
printf 'OpenWrt: %s\nPackage architecture: %s\n' "$DISTRIB_RELEASE" "$DISTRIB_ARCH"
```

RISC-V is named `riscv64_riscv64` on 24.10 and `riscv64_generic` on 25.12; read the name for your installed release.

Use `DISTRIB_ARCH`, not `uname -m`. Several devices can share a package architecture. OpenWrt 24.10 uses `opkg`/IPK; 25.12 uses `apk`/APK.

## Quick install

Install the complete package sets:

```sh
(
  set -eu
  tmp=$(mktemp -d /tmp/snodec.XXXXXX)
  trap 'rm -rf "$tmp"' EXIT HUP INT TERM
  base=https://raw.githubusercontent.com/SNodeC/Packages/main
  wget -O "$tmp/install.sh" "$base/install/install.sh"
  sh "$tmp/install.sh"
)
```

The installer detects the distribution, release and package architecture, checks that an index exists, installs the signing key, configures the feed and installs the complete package set. Configure applications before starting them. For manual configuration, use [Manual repository setup](#manual-repository-setup).

**Check**

```sh
# OpenWrt 24.10
opkg list-installed | grep -E '^(snodec|mqttsuite)( |-)'
```

```sh
# OpenWrt 25.12
apk info -e snodec mqttsuite
```

On 24.10, installed package names and versions are listed; on 25.12, both requested names are printed and the command succeeds. Next: [SNode.C configuration](../catalogs/snodec.md#after-installation) or [MQTTSuite configuration and deployment](../catalogs/mqttsuite.md#after-installation).

<a id="choose-packages"></a>

## Custom install

Prepare the repository without installing packages, then install only what you need:

```sh
(
  set -eu
  tmp=$(mktemp -d /tmp/snodec.XXXXXX)
  trap 'rm -rf "$tmp"' EXIT HUP INT TERM
  base=https://raw.githubusercontent.com/SNodeC/Packages/main
  wget -O "$tmp/install.sh" "$base/install/install.sh"
  sh "$tmp/install.sh" --prepare
)
```

For only the broker and command-line client:

<a id="install-selected-components"></a>

```sh
# OpenWrt 24.10
opkg install mqttsuite-broker mqttsuite-cli
```

```sh
# OpenWrt 25.12
apk add mqttsuite-broker mqttsuite-cli
```

Dependencies are installed automatically.

**Check**

```sh
# OpenWrt 24.10
opkg list-installed | grep -E '^mqttsuite-(broker|cli) '
```

```sh
# OpenWrt 25.12
apk info -e mqttsuite-broker mqttsuite-cli
```

On 24.10, installed package names and versions are listed; on 25.12, both requested names are printed and the command succeeds. Next: [SNode.C configuration](../catalogs/snodec.md#after-installation) or [MQTTSuite configuration and deployment](../catalogs/mqttsuite.md#after-installation).

See the [SNode.C catalog](../catalogs/snodec.md#page-overview) and [MQTTSuite catalog](../catalogs/mqttsuite.md#page-overview) for package roles and after-install configuration.

## Manual repository setup

Run the block for your release as `root`. These commands only configure the feed and refresh its index; package installation is a separate step. Existing feeds are preserved. The public keys can also be inspected in [keys](../../keys).

### OpenWrt 24.10: opkg

```sh
(
  set -eu
  . /etc/openwrt_release
  case "$DISTRIB_RELEASE" in
    24.10|24.10.*|24.10-*) ;;
    *) echo 'Requires OpenWrt 24.10'; exit 1 ;;
  esac
  tmp=$(mktemp -d /tmp/snodec.XXXXXX)
  trap 'rm -rf "$tmp"' EXIT HUP INT TERM
  base=https://raw.githubusercontent.com/SNodeC/Packages/main
  feed="$base/openwrt/24.10/$DISTRIB_ARCH"
  # Download both files successfully before writing configuration.
  wget -O "$tmp/index" "$feed/build.json"
  wget -O "$tmp/key" "$base/keys/snodec-opkg.pub"
  opkg-key add "$tmp/key"
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
  case "$DISTRIB_RELEASE" in
    25.12|25.12.*|25.12-*) ;;
    *) echo 'Requires OpenWrt 25.12'; exit 1 ;;
  esac
  tmp=$(mktemp -d /tmp/snodec.XXXXXX)
  trap 'rm -rf "$tmp"' EXIT HUP INT TERM
  base=https://raw.githubusercontent.com/SNodeC/Packages/main
  feed="$base/openwrt/25.12/$DISTRIB_ARCH"
  # Download both files successfully before writing configuration.
  wget -O "$tmp/index" "$feed/build.json"
  wget -O "$tmp/key" "$base/keys/snodec-apk.pem"
  mkdir -p /etc/apk/keys /etc/apk/repositories.d
  cp "$tmp/key" /etc/apk/keys/snodec-apk.pem
  printf '%s/packages.adb\n' "$feed" > /etc/apk/repositories.d/snodec.list
  apk update
)
```

### Example: GL.iNet GL-MT3000 running official OpenWrt

This device uses `aarch64_cortex-a53`.

The manual setup above writes `/etc/opkg/customfeeds.conf` on **24.10** and `/etc/apk/repositories.d/snodec.list` on **25.12**. To inspect the corresponding entries without changing either file:

```sh
base=https://raw.githubusercontent.com/SNodeC/Packages/main
arch=aarch64_cortex-a53
# OpenWrt 24.10: feed entry
printf 'src/gz snodec %s\n' "$base/openwrt/24.10/$arch"
# OpenWrt 25.12: repository entry
printf '%s/packages.adb\n' "$base/openwrt/25.12/$arch"
```

Import the corresponding signing key as shown above. For other devices, use their `DISTRIB_ARCH`; each architecture has its own directory. After an OpenWrt release-series upgrade, reconfigure this feed for the new series.

Verify the [installed signing key](../../keys/README.md#installed-keys) before installing packages.

Install the complete sets after manual setup:

```sh
# OpenWrt 24.10: full selection
opkg install snodec mqttsuite
```

```sh
# OpenWrt 25.12: full selection
apk add snodec mqttsuite
```

**Check**

```sh
# OpenWrt 24.10
opkg list-installed | grep -E '^(snodec|mqttsuite)( |-)'
```

```sh
# OpenWrt 25.12
apk info -e snodec mqttsuite
```

On 24.10, installed package names and versions are listed; on 25.12, both requested names are printed and the command succeeds. Next: [SNode.C configuration](../catalogs/snodec.md#after-installation) or [MQTTSuite configuration and deployment](../catalogs/mqttsuite.md#after-installation).

The repository is ready; [install only the selected components](#install-selected-components) you need.

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

## Source records

In [source records](../../openwrt/), `<series>/<architecture>/build.json` belongs to the feed directory opened by **Packages**.

`build.json` records source tags and commits, package versions, checksums and publication context. On the [project status pages](../../status/README.md#page-overview), **Build log** opens the recorded build job or release run. See [column semantics](../publication.md#latest-release-available-and-in-build) for missing historical records.

Source recipes: [SNode.C](https://github.com/SNodeC/snode.c/tree/HEAD/supplement/openwrt) and [MQTTSuite](https://github.com/SNodeC/mqttsuite/tree/HEAD/misc/openwrt).

## Troubleshooting

See [common problems and fixes](../troubleshooting.md#page-overview) for download, signature, dependency and application errors.

| Symptom | What to check |
| --- | --- |
| Architecture looks right but packages fail on vendor firmware | Use official OpenWrt with the matching release and `DISTRIB_ARCH`; matching CPU names alone are insufficient. |
| Service does not start | Inspect `logread -e mqttbroker` and the application configuration before enabling its procd service. |
