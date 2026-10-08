# SNode.C and MQTTSuite packages

Signed binary packages for OpenWrt, Raspberry Pi OS, Debian, Ubuntu, Rocky Linux and Fedora.

<p>
  <a href="#quick-start" title="Quick start"><img src="docs/media/menu/quick-start-120.svg" alt="Quick start" width="120" height="24"></a>
  <a href="#distributions" title="Distributions"><img src="docs/media/menu/distributions-120.svg" alt="Distributions" width="120" height="24"></a>
  <a href="#packages" title="Packages"><img src="docs/media/menu/packages-120.svg" alt="Packages" width="120" height="24"></a>
  <a href="https://github.com/SNodeC/Packages/blob/main/docs/status.md" title="Package status"><img src="docs/media/menu/package-status-120.svg" alt="Package status" width="120" height="24"></a>
  <a href="#help" title="Help"><img src="docs/media/menu/help-120.svg" alt="Help" width="120" height="24"></a>
</p>

## What's inside

[SNode.C](https://github.com/SNodeC/snode.c#project-overview) provides a C++ networking framework, runtime libraries and tools. [MQTTSuite](https://github.com/SNodeC/mqttsuite#project-overview) provides an MQTT broker, bridge, integrator, command-line client, store and mapping plugins. Install binaries with your package manager; no compilation is needed.

## Quick start

### Installation

Check your [distribution guide](#distributions) for prerequisites, especially CRB/EPEL on Rocky Linux. Keep official repositories enabled for dependencies.

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

The installer checks the target, configures its signed package source and installs both complete project sets; `--prepare` only configures the source and refreshes indexes. Prefer manual setup? See your distribution guide.

## Distributions

| Distribution | Releases | Architectures | Guide | Status |
| --- | --- | --- | --- | --- |
| OpenWrt | 24.10, 25.12 | 25 architectures | [Install](docs/openwrt.md) | [Status](https://github.com/SNodeC/Packages/blob/main/docs/status.md#openwrt) |
| Raspberry Pi OS | bookworm, trixie | arm64 | [Install](docs/raspberrypi.md) | [Status](https://github.com/SNodeC/Packages/blob/main/docs/status.md#raspberry-pi-os) |
| Debian | trixie, forky, sid | amd64, arm64, armhf, riscv64 | [Install](docs/debian.md) | [Status](https://github.com/SNodeC/Packages/blob/main/docs/status.md#debian) |
| Ubuntu | noble, resolute | amd64, arm64 | [Install](docs/ubuntu.md) | [Status](https://github.com/SNodeC/Packages/blob/main/docs/status.md#ubuntu) |
| Rocky Linux | 9, 10 | aarch64, x86_64 | [Install](docs/rocky.md) | [Status](https://github.com/SNodeC/Packages/blob/main/docs/status.md#rocky-linux) |
| Fedora | 43, 44 | aarch64, x86_64 | [Install](docs/fedora.md) | [Status](https://github.com/SNodeC/Packages/blob/main/docs/status.md#fedora) |

OpenWrt supports 25 package architectures per release. Raspberry Pi OS supports Pi 3, 4 and 5.

## Packages

The default install includes all framework components offered by the distribution, demonstration applications, the configuration tool, all five MQTT applications and both mapping plugins. Configure listeners, credentials and TLS before starting services.

| Package | Contents |
| --- | --- |
| `snodec` | Runtime modules, demo apps and control tool |
| `snodec-apps` | Demonstration applications |
| `snodec-control` | Configuration tool |
| `mqttsuite` | Five applications and two mapping plugins |

DEB/RPM packages also include development files.

Full catalogs: [SNode.C](docs/snodec-package-options.md) and [MQTTSuite](docs/mqttsuite-package-options.md), with shared package names across distributions. Find available versions and per-target results on [Package status](https://github.com/SNodeC/Packages/blob/main/docs/status.md).

## Signing keys

### opkg / usign

```text
f6fd78dca70698e8
```

### apk / SHA-256 of DER public key

```text
293fb661ae75b821a15fa14f1399cd432d2f444bec138ba0e9ac397c81dbe645
```

### APT and RPM / OpenPGP

```text
8BBFD49E3C826FDB1416C79E60046744B15B0E05
```

[Download public keys](https://github.com/SNodeC/Packages/tree/main/keys). APT and RPM use the same key. Keep signature verification enabled.

## Help

### Repository troubleshooting

See [Troubleshooting](docs/troubleshooting.md) for common errors and packaging terms, or [open an issue](https://github.com/SNodeC/Packages/issues).

---

<p>
  <a href="docs/maintainers.md" title="How this repository works"><img src="docs/media/menu/how-this-repository-works-188.svg" alt="How this repository works" width="188" height="24"></a>
  <a href="https://github.com/SNodeC/snode.c#project-overview" title="SNode.C"><img src="docs/media/menu/snode-c-188.svg" alt="SNode.C" width="188" height="24"></a>
  <a href="https://github.com/SNodeC/mqttsuite#project-overview" title="MQTTSuite"><img src="docs/media/menu/mqttsuite-188.svg" alt="MQTTSuite" width="188" height="24"></a>
</p>
