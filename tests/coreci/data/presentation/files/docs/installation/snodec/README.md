<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->

<!-- snodec:begin page-header -->
<a id="banner"></a><a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="../../media/nav/banner-installation-compact.svg"><img src="../../media/nav/banner-installation.svg" alt="Packages — Installation" width="100%"></picture></p>
<p><a href="../README.md#banner" title="Up to Installation"><picture><source media="(prefers-color-scheme: dark)" srcset="../../media/nav/up-installation-dark.svg"><img src="../../media/nav/up-installation-light.svg" alt="Up to Installation" title="Up to Installation" width="160" height="28"></picture></a><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../../media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="../../media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../../media/nav/account-dark.svg"><img align="right" src="../../media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../../media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="../../media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../../media/nav/organization-dark.svg"><img align="right" src="../../media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../../../README.md#banner" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../../media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="../../media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../../media/nav/repository-dark.svg"><img align="right" src="../../media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# Install SNode.C

Choose your distribution, then the application or library components you need.

## Distributions

- [Debian](debian.md#banner)
- [Ubuntu](ubuntu.md#banner)
- [Raspberry Pi OS](raspberry-pi-os.md#banner)
- [Fedora](fedora.md#banner)
- [Rocky Linux](rocky-linux.md#banner)
- [OpenWrt](openwrt.md#banner)

## Installation choices

- HTTP server with TLS (`--component http-server-express-tls-in`)
- MQTT client (`--component mqtt-client`)
- WebSocket client (`--component websocket-client`)
- Framework control tool (`--component control`)
- Complete framework (`--component all`)

[SNode.C package catalog](../../catalogs/snodec.md#banner) · [Package availability](../../../status/snodec.md#banner)

Project installers use the shared `install.sh` engine downloaded beside them as shown in each guide. Use `--help` for choices; the shared installer without a selection shows help and installs nothing.
