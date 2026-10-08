# OpenWrt

<p>
  <a href="../README.md#distributions"><img src="media/menu/back-all-distributions.svg" alt="← All distributions" width="140" height="24"></a>
</p>

<p>
  <a href="#requirements" title="Requirements"><img src="media/menu/requirements-102.svg" alt="Requirements" width="102" height="24"></a>
  <a href="#quick-install" title="Quick install"><img src="media/menu/install-102.svg" alt="Quick install" width="102" height="24"></a>
  <a href="#choose-packages" title="Choose packages"><img src="media/menu/packages-102.svg" alt="Choose packages" width="102" height="24"></a>
  <a href="#configure-and-run" title="Configure and run"><img src="media/menu/configure-102.svg" alt="Configure and run" width="102" height="24"></a>
  <a href="#updates" title="Updates"><img src="media/menu/updates-102.svg" alt="Updates" width="102" height="24"></a>
  <a href="#manual-repository-setup" title="Manual repository setup"><img src="media/menu/manual-setup-102.svg" alt="Manual repository setup" width="102" height="24"></a>
  <a href="#reference" title="Reference"><img src="media/menu/reference-102.svg" alt="Reference" width="102" height="24"></a>
  <a href="#troubleshooting" title="Troubleshooting"><img src="media/menu/help-102.svg" alt="Troubleshooting" width="102" height="24"></a>
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

Dependencies are installed automatically. For the full selection after manual preparation, install the complete-project packages listed below.

| Package | Contents |
| --- | --- |
| `snodec` | All framework runtime modules, demonstration apps and control tool |
| `snodec-apps` | Demonstration applications |
| `snodec-control` | Configuration tool |
| `mqttsuite` | All five applications and both mapping plugins |
| `mqttsuite-broker` | MQTT broker |
| `mqttsuite-cli` | Publish/subscribe command-line client |

Full catalogs: [SNode.C](snodec-package-options.md) and [MQTTSuite](mqttsuite-package-options.md).

```sh
# OpenWrt 24.10: full selection
opkg install snodec mqttsuite
```

```sh
# OpenWrt 25.12: full selection
apk add snodec mqttsuite
```

## Configure and run

Inspect `mqttbroker --help`, `mqttcli --help` and `snodec-control --help`. Configure listeners, credentials and TLS certificates before starting services. The store requires a configured database. Consult the [application documentation](https://github.com/SNodeC/mqttsuite#project-overview) and [framework documentation](https://github.com/SNodeC/snode.c#project-overview) for options.

Configure `/etc/snode.c/mqttbroker.conf`, then enable and start the broker:

```sh
/etc/init.d/mqttbroker enable
/etc/init.d/mqttbroker start
pidof mqttbroker
logread -e mqttbroker
```

After configuration changes, run `/etc/init.d/mqttbroker restart`. The bridge and integrator provide `mqttbridge` and `mqttintegrator` services. Configure each before enabling it.

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

## Reference

Source recipes: [SNode.C](https://github.com/SNodeC/Packages/tree/main/net/snode.c) and [MQTTSuite](https://github.com/SNodeC/Packages/tree/main/net/mqttsuite).

Both releases support the same platform variants. RISC-V is named `riscv64_riscv64` on 24.10 and `riscv64_generic` on 25.12.

<details>
<summary>Supported releases, package architectures and indexes</summary>

### 24.10

| Release | Package architecture | Index | Browse |
| --- | --- | --- | --- |
| 24.10 | `aarch64_cortex-a53` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/aarch64_cortex-a53/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/aarch64_cortex-a53) |
| 24.10 | `aarch64_cortex-a72` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/aarch64_cortex-a72/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/aarch64_cortex-a72) |
| 24.10 | `aarch64_cortex-a76` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/aarch64_cortex-a76/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/aarch64_cortex-a76) |
| 24.10 | `aarch64_generic` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/aarch64_generic/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/aarch64_generic) |
| 24.10 | `arm_cortex-a15_neon-vfpv4` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/arm_cortex-a15_neon-vfpv4/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/arm_cortex-a15_neon-vfpv4) |
| 24.10 | `arm_cortex-a5_vfpv4` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/arm_cortex-a5_vfpv4/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/arm_cortex-a5_vfpv4) |
| 24.10 | `arm_cortex-a7` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/arm_cortex-a7/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/arm_cortex-a7) |
| 24.10 | `arm_cortex-a7_neon-vfpv4` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/arm_cortex-a7_neon-vfpv4/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/arm_cortex-a7_neon-vfpv4) |
| 24.10 | `arm_cortex-a7_vfpv4` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/arm_cortex-a7_vfpv4/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/arm_cortex-a7_vfpv4) |
| 24.10 | `arm_cortex-a8_vfpv3` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/arm_cortex-a8_vfpv3/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/arm_cortex-a8_vfpv3) |
| 24.10 | `arm_cortex-a9` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/arm_cortex-a9/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/arm_cortex-a9) |
| 24.10 | `arm_cortex-a9_neon` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/arm_cortex-a9_neon/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/arm_cortex-a9_neon) |
| 24.10 | `arm_cortex-a9_vfpv3-d16` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/arm_cortex-a9_vfpv3-d16/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/arm_cortex-a9_vfpv3-d16) |
| 24.10 | `i386_pentium-mmx` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/i386_pentium-mmx/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/i386_pentium-mmx) |
| 24.10 | `i386_pentium4` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/i386_pentium4/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/i386_pentium4) |
| 24.10 | `loongarch64_generic` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/loongarch64_generic/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/loongarch64_generic) |
| 24.10 | `mips64_octeonplus` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/mips64_octeonplus/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/mips64_octeonplus) |
| 24.10 | `mips_24kc` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/mips_24kc/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/mips_24kc) |
| 24.10 | `mipsel_24kc` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/mipsel_24kc/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/mipsel_24kc) |
| 24.10 | `mipsel_24kc_24kf` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/mipsel_24kc_24kf/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/mipsel_24kc_24kf) |
| 24.10 | `mipsel_74kc` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/mipsel_74kc/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/mipsel_74kc) |
| 24.10 | `powerpc_464fp` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/powerpc_464fp/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/powerpc_464fp) |
| 24.10 | `powerpc_8548` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/powerpc_8548/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/powerpc_8548) |
| 24.10 | `riscv64_riscv64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/riscv64_riscv64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/riscv64_riscv64) |
| 24.10 | `x86_64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/24.10/x86_64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/24.10/x86_64) |

### 25.12

| Release | Package architecture | Index | Browse |
| --- | --- | --- | --- |
| 25.12 | `aarch64_cortex-a53` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/aarch64_cortex-a53/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/aarch64_cortex-a53) |
| 25.12 | `aarch64_cortex-a72` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/aarch64_cortex-a72/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/aarch64_cortex-a72) |
| 25.12 | `aarch64_cortex-a76` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/aarch64_cortex-a76/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/aarch64_cortex-a76) |
| 25.12 | `aarch64_generic` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/aarch64_generic/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/aarch64_generic) |
| 25.12 | `arm_cortex-a15_neon-vfpv4` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/arm_cortex-a15_neon-vfpv4/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/arm_cortex-a15_neon-vfpv4) |
| 25.12 | `arm_cortex-a5_vfpv4` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/arm_cortex-a5_vfpv4/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/arm_cortex-a5_vfpv4) |
| 25.12 | `arm_cortex-a7` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/arm_cortex-a7/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/arm_cortex-a7) |
| 25.12 | `arm_cortex-a7_neon-vfpv4` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/arm_cortex-a7_neon-vfpv4/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/arm_cortex-a7_neon-vfpv4) |
| 25.12 | `arm_cortex-a7_vfpv4` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/arm_cortex-a7_vfpv4/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/arm_cortex-a7_vfpv4) |
| 25.12 | `arm_cortex-a8_vfpv3` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/arm_cortex-a8_vfpv3/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/arm_cortex-a8_vfpv3) |
| 25.12 | `arm_cortex-a9` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/arm_cortex-a9/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/arm_cortex-a9) |
| 25.12 | `arm_cortex-a9_neon` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/arm_cortex-a9_neon/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/arm_cortex-a9_neon) |
| 25.12 | `arm_cortex-a9_vfpv3-d16` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/arm_cortex-a9_vfpv3-d16/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/arm_cortex-a9_vfpv3-d16) |
| 25.12 | `i386_pentium-mmx` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/i386_pentium-mmx/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/i386_pentium-mmx) |
| 25.12 | `i386_pentium4` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/i386_pentium4/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/i386_pentium4) |
| 25.12 | `loongarch64_generic` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/loongarch64_generic/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/loongarch64_generic) |
| 25.12 | `mips64_octeonplus` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/mips64_octeonplus/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/mips64_octeonplus) |
| 25.12 | `mips_24kc` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/mips_24kc/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/mips_24kc) |
| 25.12 | `mipsel_24kc` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/mipsel_24kc/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/mipsel_24kc) |
| 25.12 | `mipsel_24kc_24kf` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/mipsel_24kc_24kf/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/mipsel_24kc_24kf) |
| 25.12 | `mipsel_74kc` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/mipsel_74kc/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/mipsel_74kc) |
| 25.12 | `powerpc_464fp` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/powerpc_464fp/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/powerpc_464fp) |
| 25.12 | `powerpc_8548` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/powerpc_8548/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/powerpc_8548) |
| 25.12 | `riscv64_generic` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/riscv64_generic/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/riscv64_generic) |
| 25.12 | `x86_64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/openwrt/25.12/x86_64/packages.adb) | [Browse](https://github.com/SNodeC/Packages/tree/main/openwrt/25.12/x86_64) |

</details>

## Troubleshooting

See [common problems and fixes](troubleshooting.md) for download, signature, dependency and application errors.

| Symptom | What to check |
| --- | --- |
| Architecture looks right but packages fail on vendor firmware | Use official OpenWrt with the matching release and `DISTRIB_ARCH`; matching CPU names alone are insufficient. |
| Service does not start | Inspect `logread -e mqttbroker` and the application configuration before enabling its procd service. |

<p>
  <a href="#openwrt" title="Back to top"><img src="media/menu/back-to-top-124.svg" alt="Back to top" width="124" height="24"></a>
  <a href="../README.md#distributions" title="All distributions"><img src="media/menu/all-distributions-124.svg" alt="All distributions" width="124" height="24"></a>
  <a href="https://github.com/SNodeC/Packages/blob/main/docs/status.md#openwrt" title="Package status"><img src="media/menu/package-status-124.svg" alt="Package status" width="124" height="24"></a>
</p>
