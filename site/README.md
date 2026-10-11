<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->
<a id="project-overview"></a>

![Packages](docs/media/banner.svg)

# SNodeC Packages

Signed packages for the SNode.C ecosystem. Choose a project and distribution, install using its signed package source, and inspect availability separately from ongoing builds.

<p>
<a href="#quick-start"><img src="docs/media/menu/start.svg" alt="Start"></a>
<a href="#install"><img src="docs/media/menu/install.svg" alt="Install"></a>
<a href="status/README.md#page-overview"><img src="docs/media/menu/status.svg" alt="Status"></a>
<a href="docs/troubleshooting.md#page-overview"><img src="docs/media/menu/troubleshoot.svg" alt="Troubleshoot"></a>
<a href="docs/architecture.md#page-overview"><img src="docs/media/menu/architecture.svg" alt="Architecture"></a>
<a href="#contributing"><img src="docs/media/menu/contribute.svg" alt="Contribute"></a>
</p>
<a id="installation"></a>

## Quick start

Check your [distribution guide](#install) first for prerequisites, especially CRB/EPEL on Rocky Linux. Keep official repositories enabled for dependencies.

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

The installer checks the target, configures its signed package source and installs the configured complete sets; `--prepare` only configures the source and refreshes indexes. Prefer manual setup? See your distribution guide.


<a id="packages"></a>

## Projects

Available targets refer to published packages, not the success of a replacement build. Open the [project directory](status/README.md#page-overview) for package catalogs and per-project status.

<!-- packages:begin projects -->
<!-- packages:end projects -->

## Platforms

The supported release and architecture matrix is generated from the publisher's target definitions. Availability is reported per project and target.

<!-- packages:begin platforms -->
<!-- packages:end platforms -->

<a id="distributions"></a>

## Install

<p>
<a href="docs/openwrt.md#page-overview"><img src="docs/media/menu/openwrt.svg" alt="OpenWrt"></a>
<a href="docs/raspberrypi.md#page-overview"><img src="docs/media/menu/raspberrypi.svg" alt="Raspberry Pi OS"></a>
<a href="docs/debian.md#page-overview"><img src="docs/media/menu/debian.svg" alt="Debian"></a>
<a href="docs/ubuntu.md#page-overview"><img src="docs/media/menu/ubuntu.svg" alt="Ubuntu"></a>
<a href="docs/rocky.md#page-overview"><img src="docs/media/menu/rocky.svg" alt="Rocky Linux"></a>
<a href="docs/fedora.md#page-overview"><img src="docs/media/menu/fedora.svg" alt="Fedora"></a>
</p>
Select the guide matching your installed distribution, release and package architecture. Each guide covers requirements, quick installation, manual repository setup and updates. To install selected components rather than the complete sets, use the [project catalogs](#projects).

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

<a id="help"></a>

## Troubleshooting

Read [installation troubleshooting](docs/troubleshooting.md#page-overview) for repository, key and dependency problems. For an ongoing build or an older version still available, open [project status](status/README.md#page-overview).

## How publication works

[Publication architecture](docs/architecture.md#page-overview) explains signing, revisions, status semantics and documentation ownership. Maintainer operations live in DistributionPackages.

## Contributing

Report installation issues in [Packages](https://github.com/SNodeC/Packages/issues). Documentation and publisher changes belong to [DistributionPackages](https://github.com/SNodeC/DistributionPackages#project-overview). Do not edit generated feeds, keys or status pages by hand.

## Ecosystem

[SNodeC organization](https://github.com/SNodeC) · [SNode.C](https://github.com/SNodeC/snode.c#project-overview) · [MQTTSuite](https://github.com/SNodeC/mqttsuite#project-overview)

[Contributing](https://github.com/SNodeC/.github/blob/HEAD/CONTRIBUTING.md) · [Security](https://github.com/SNodeC/.github/blob/HEAD/SECURITY.md)
