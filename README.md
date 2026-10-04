# SNode.C and MQTTSuite packages

Signed binary packages for OpenWrt, Raspberry Pi OS, Debian, Ubuntu, Rocky Linux and Fedora.

[Quick start](#quick-start) · [Distributions](#distributions) · [Packages](#packages) · [Package status](https://github.com/SNodeC/Packages/blob/main/docs/status.md) · [Help](#help)

## What's inside

[SNode.C](https://github.com/SNodeC/snode.c) provides a C++ networking framework,
runtime libraries and tools. [MQTTSuite](https://github.com/SNodeC/mqttsuite)
provides an MQTT broker, bridge, integrator, command-line client, store and mapping
plugins. Install binaries with your package manager; no compilation is needed.

## Quick start

### Installation

Check your [distribution guide](#distributions) for prerequisites, especially
CRB/EPEL on Rocky Linux. Keep official repositories enabled for dependencies.

**Linux — Raspberry Pi OS, Debian, Ubuntu, Rocky Linux or Fedora:**

```sh
# Download the installer; curl and CA certificates must be installed.
curl -fsSL https://raw.githubusercontent.com/SNodeC/Packages/main/install/install.sh \
  -o /tmp/snodec-install-feed.sh &&
sudo sh /tmp/snodec-install-feed.sh
# For preparation only, replace the last command with:
# sudo sh /tmp/snodec-install-feed.sh --prepare
```

**OpenWrt — run as root:**

```sh
# Download the installer with HTTPS-capable wget.
wget -O /tmp/snodec-install-feed.sh \
  https://raw.githubusercontent.com/SNodeC/Packages/main/install/install.sh &&
sh /tmp/snodec-install-feed.sh
# For preparation only, replace the last command with:
# sh /tmp/snodec-install-feed.sh --prepare
```

The installer checks the target, configures its signed package source and installs
both complete project sets; `--prepare` only configures the source and refreshes indexes.
Prefer manual setup? See your distribution guide.

## Distributions

| Distribution | Releases | Architectures | Install guide | Package status |
| --- | --- | --- | --- | --- |
| OpenWrt | 24.10, 25.12 | 25 package architectures per release | [Install](docs/openwrt.md) | [Status](https://github.com/SNodeC/Packages/blob/main/docs/status.md#openwrt) |
| Raspberry Pi OS | bookworm, trixie | arm64; Pi 3, 4, 5 | [Install](docs/raspberrypi.md) | [Status](https://github.com/SNodeC/Packages/blob/main/docs/status.md#raspberry-pi-os) |
| Debian | trixie, forky, sid | amd64, arm64, armhf, riscv64 | [Install](docs/debian.md) | [Status](https://github.com/SNodeC/Packages/blob/main/docs/status.md#debian) |
| Ubuntu | noble, resolute | amd64, arm64 | [Install](docs/ubuntu.md) | [Status](https://github.com/SNodeC/Packages/blob/main/docs/status.md#ubuntu) |
| Rocky Linux | 9, 10 | aarch64, x86_64 | [Install](docs/rocky.md) | [Status](https://github.com/SNodeC/Packages/blob/main/docs/status.md#rocky-linux) |
| Fedora | 43, 44 | aarch64, x86_64 | [Install](docs/fedora.md) | [Status](https://github.com/SNodeC/Packages/blob/main/docs/status.md#fedora) |

## Packages

The default install includes all framework components offered by the distribution,
demonstration applications, the configuration tool, all five MQTT applications and
both mapping plugins. Configure listeners, credentials and TLS before starting services.

| OpenWrt name | DEB/RPM name | Contents |
| --- | --- | --- |
| `snode.c-full` | `snodec` | Framework runtime modules; DEB/RPM also includes headers, examples and tools |
| `snode.c-apps` | `snodec-apps` | Demonstration applications |
| `snode.c-control` | `snodec-unspecified` | The `snodec-control` executable |
| `mqttsuite-full` | `mqttsuite` | All five applications and both mapping plugins |

Full catalogs: [SNode.C for OpenWrt](docs/snodec-package-options.md),
[MQTTSuite for OpenWrt](docs/mqttsuite-package-options.md),
and [DEB/RPM components](docs/linux.md#component-packages).
Find available versions and per-target results on [Package status](https://github.com/SNodeC/Packages/blob/main/docs/status.md).

## Signing keys

| Format | Public-key fingerprint |
| --- | --- |
| opkg / usign | `f6fd78dca70698e8` |
| apk / SHA-256 of DER public key | `293fb661ae75b821a15fa14f1399cd432d2f444bec138ba0e9ac397c81dbe645` |
| APT / OpenPGP | `8BBFD49E3C826FDB1416C79E60046744B15B0E05` |
| RPM / OpenPGP | `8BBFD49E3C826FDB1416C79E60046744B15B0E05` |

[Download public keys](https://github.com/SNodeC/Packages/tree/main/keys).
APT and RPM use the same key. Keep signature verification enabled.

## Help

### Repository troubleshooting

See [Troubleshooting](docs/troubleshooting.md) for common errors and packaging
terms, or [open an issue](https://github.com/SNodeC/Packages/issues).

---

[How this repository works](docs/maintainers.md) · [SNode.C](https://github.com/SNodeC/snode.c) · [MQTTSuite](https://github.com/SNodeC/mqttsuite)
