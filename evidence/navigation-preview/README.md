<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->
<a id="project-overview"></a>

![Packages](https://raw.githubusercontent.com/SNodeC/DistributionPackages/docs/navigation-step2/site/docs/media/banner.svg)

# SNodeC Packages

Signed packages for the SNode.C ecosystem. Choose a project and distribution, install using its signed package source, and inspect availability separately from ongoing builds.

<p>
<a href="#quick-start"><img src="https://raw.githubusercontent.com/SNodeC/DistributionPackages/docs/navigation-step2/site/docs/media/menu/start.svg" alt="Start"></a>
<a href="#install"><img src="https://raw.githubusercontent.com/SNodeC/DistributionPackages/docs/navigation-step2/site/docs/media/menu/install.svg" alt="Install"></a>
<a href="status/README.md#page-overview"><img src="https://raw.githubusercontent.com/SNodeC/DistributionPackages/docs/navigation-step2/site/docs/media/menu/status.svg" alt="Status"></a>
<a href="https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/troubleshooting.md#page-overview"><img src="https://raw.githubusercontent.com/SNodeC/DistributionPackages/docs/navigation-step2/site/docs/media/menu/troubleshoot.svg" alt="Troubleshoot"></a>
<a href="https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/publication.md#page-overview"><img src="https://raw.githubusercontent.com/SNodeC/DistributionPackages/docs/navigation-step2/site/docs/media/menu/architecture.svg" alt="Architecture"></a>
<a href="#contributing"><img src="https://raw.githubusercontent.com/SNodeC/DistributionPackages/docs/navigation-step2/site/docs/media/menu/contribute.svg" alt="Contribute"></a>
</p>
<a id="packages"></a>

## Projects

<!-- packages:begin projects -->
| Project | Latest release | Status |
| --- | --- | --- |
| [SNode.C](https://github.com/SNodeC/snode.c#project-overview) | 2.0.0 · r10 | [SNode.C status →](status/snodec.md#page-overview) |
| [MQTTSuite](https://github.com/SNodeC/mqttsuite#project-overview) | 1.0.2 · r10 | [MQTTSuite status →](status/mqttsuite.md#page-overview) |
<!-- packages:end projects -->

<a id="installation"></a>

## Quick start

Start with your installed system, not an ongoing build: use the [distribution chooser](#install), check the guide’s requirements, then choose **complete sets** or **selected packages**. Follow its Check and Next steps to confirm installation and configure your applications. Status pages are optional: consult them to compare available packages with a replacement build.

<a id="distributions"></a>

## Install

<p>
<a href="https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/installation/openwrt.md#page-overview"><img src="https://raw.githubusercontent.com/SNodeC/DistributionPackages/docs/navigation-step2/site/docs/media/menu/openwrt.svg" alt="OpenWrt"></a>
<a href="https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/installation/raspberry-pi-os.md#page-overview"><img src="https://raw.githubusercontent.com/SNodeC/DistributionPackages/docs/navigation-step2/site/docs/media/menu/raspberrypi.svg" alt="Raspberry Pi OS"></a>
<a href="https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/installation/debian.md#page-overview"><img src="https://raw.githubusercontent.com/SNodeC/DistributionPackages/docs/navigation-step2/site/docs/media/menu/debian.svg" alt="Debian"></a>
<a href="https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/installation/ubuntu.md#page-overview"><img src="https://raw.githubusercontent.com/SNodeC/DistributionPackages/docs/navigation-step2/site/docs/media/menu/ubuntu.svg" alt="Ubuntu"></a>
<a href="https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/installation/rocky-linux.md#page-overview"><img src="https://raw.githubusercontent.com/SNodeC/DistributionPackages/docs/navigation-step2/site/docs/media/menu/rocky.svg" alt="Rocky Linux"></a>
<a href="https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/installation/fedora.md#page-overview"><img src="https://raw.githubusercontent.com/SNodeC/DistributionPackages/docs/navigation-step2/site/docs/media/menu/fedora.svg" alt="Fedora"></a>
</p>

Select the guide matching your installed distribution, release and package architecture. Each guide covers requirements, quick installation, manual repository setup and updates.

## Platforms

The supported release and architecture matrix is generated from the publisher's target definitions. Availability is reported per project and target.

<!-- packages:begin platforms -->
| Distribution | Releases | Architectures |
| --- | --- | --- |
| [OpenWrt](https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/installation/openwrt.md#page-overview) | 24.10, 25.12 | 25 per release (names can differ) |
| [Raspberry Pi OS](https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/installation/raspberry-pi-os.md#page-overview) | bookworm, trixie | arm64 |
| [Debian](https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/installation/debian.md#page-overview) | forky, sid, trixie | amd64, arm64, armhf, riscv64 |
| [Ubuntu](https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/installation/ubuntu.md#page-overview) | noble, resolute | amd64, arm64 |
| [Rocky Linux](https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/installation/rocky-linux.md#page-overview) | 10, 9 | aarch64, x86_64 |
| [Fedora](https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/installation/fedora.md#page-overview) | 43, 44 | aarch64, x86_64 |
<!-- packages:end platforms -->

## Signing keys

[![Signing keys](https://raw.githubusercontent.com/SNodeC/DistributionPackages/docs/navigation-step2/site/docs/media/menu/keys.svg)](https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/keys/README.md#page-overview)

Identify and verify the key for your package manager. Keys are shared across architectures; keep signature verification enabled.

<a id="help"></a>

## Troubleshooting

[Diagnose installation errors](https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/troubleshooting.md#page-overview), or compare available packages and replacement builds on [project status](status/README.md#page-overview).

## How publication works

[Read the column meanings and publication model](https://github.com/SNodeC/DistributionPackages/blob/docs/navigation-step2/site/docs/publication.md#page-overview). Maintainer operations belong to DistributionPackages.

## Contributing

Report installation issues in [Packages](https://github.com/SNodeC/Packages/issues). Documentation and publisher changes belong to [DistributionPackages](https://github.com/SNodeC/DistributionPackages#project-overview). Do not edit generated feeds, keys or status pages by hand.

## Ecosystem

[SNodeC organization](https://github.com/SNodeC) · [SNode.C](https://github.com/SNodeC/snode.c#project-overview) · [MQTTSuite](https://github.com/SNodeC/mqttsuite#project-overview)

[Contributing](https://github.com/SNodeC/.github/blob/HEAD/CONTRIBUTING.md) · [Security](https://github.com/SNodeC/.github/blob/HEAD/SECURITY.md)
