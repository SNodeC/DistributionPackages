<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->

<!-- snodec:begin page-header -->
<a id="banner"></a><a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="../media/nav/banner-catalogs-compact.svg"><img src="../media/nav/banner-catalogs.svg" alt="Packages — Catalogs" width="100%"></picture></p>
<p><a href="README.md#banner" title="Up to Catalogs"><picture><source media="(prefers-color-scheme: dark)" srcset="../media/nav/up-catalogs-dark.svg"><img src="../media/nav/up-catalogs-light.svg" alt="Up to Catalogs" title="Up to Catalogs" width="160" height="28"></picture></a><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/account-dark.svg"><img align="right" src="../media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/organization-dark.svg"><img align="right" src="../media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../../README.md#banner" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/repository-dark.svg"><img align="right" src="../media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# MQTTSuite package catalog

<!-- snodec:begin menu -->
[![Install](../media/menu/install.svg)](../../README.md#install) [![Status](../media/menu/status.svg)](../../status/mqttsuite.md#banner) [![Catalog](../media/menu/catalog.svg)](#package-catalog) [![Details](../media/menu/details.svg)](#distribution-details) [![Query](../media/menu/query.svg)](#query-available-packages) [![Use](../media/menu/use.svg)](#after-installation)
<!-- snodec:end menu -->

Package names are shared by OpenWrt, Raspberry Pi OS, Debian, Ubuntu, Rocky Linux and Fedora. Architectures affect availability and binary contents, not names.

## Package catalog

Library `<version>` follows the published release; `<ABI>` identifies its binary interface. See [Package status](../../status/mqttsuite.md#banner) for current versions.

| Package | Payload / role |
| --- | --- |
| `mqttsuite-broker` | mqttbroker, `libmqtt-broker.so.<ABI>`, optional server plugin, web assets |
| `mqttsuite-integrator` | mqttintegrator, `libmqtt-integrator.so.<ABI>`, optional client plugin |
| `mqttsuite-bridge` | mqttbridge, `libmqtt-bridge.so.<ABI>`, optional client plugin, web assets |
| `mqttsuite-cli` | mqttcli, `libmqtt-cli.so.<ABI>`, optional client plugin |
| `mqttsuite-store` | mqttstore, `libmqtt-store.so.<ABI>`, optional client plugin; requires MariaDB support |
| `mqttsuite-mapping-double` | libmqtt-mapping-plugin-double.so |
| `mqttsuite-mapping-storage` | libmqtt-mapping-plugin-storage.so |
| `mqttsuite` | Metapackage: all five applications and both mapping plugins |

Application libraries also include the real `.so.<version>` file. Each enabled MQTT WebSocket plugin contains its `.so.<ABI>` ABI symlink and `.so.<version>` real file.

Install the application you need, such as `mqttsuite-broker`; its published dependencies select the framework components. The `mqttsuite` metapackage instead selects the full suite.

## Distribution details

- OpenWrt's broker, bridge and integrator packages include procd service scripts. DEB/RPM packages currently do not ship systemd units.
- Library directories follow the distribution's layout. WebSocket plugins are included when their transport is enabled in the build.
- Applications use SNode.C's configuration and account setup through their framework dependencies; no separate `mqttsuite-common` package is needed.

## Query available packages

Patterns include the bare metapackage and its components. APT lists known names (including virtual or unavailable entries); consult `apt-cache policy <package>` before choosing a version. The remaining commands query repository metadata.

```sh
# APT distributions
apt-cache pkgnames mqttsuite | sort
# RPM distributions
dnf list --available 'mqttsuite*'
```

```sh
# OpenWrt 24.10 (opkg)
opkg list 'mqttsuite*'
# OpenWrt 25.12 (APK)
apk search 'mqttsuite*'
```

## After installation

Inspect `mqttbroker --help` and `mqttcli --help`. Configure listeners, credentials and TLS certificates before starting services. MQTTStore needs a configured database. Before exposing management interfaces, review the deployment guide.

Before exposing a service, [deploy safely](https://github.com/SNodeC/mqttsuite/blob/HEAD/docs/guides/deployment.md#page-overview).

### Native Linux

Executables are installed in `/usr/bin`. Administrative configuration lives in `/etc/snode.c`; non-root processes use their per-user configuration directories. Installation creates the `snodec` system group but does not start network services. Run a foreground broker with:

```sh
mqttbroker --daemonize=false
```

For persistent operation, configure a service with the desired account and arguments. DEB/RPM packages currently do not supply systemd service units.

### OpenWrt services

Configure `/etc/snode.c/mqttbroker.conf` before enabling the broker:

```sh
/etc/init.d/mqttbroker enable
/etc/init.d/mqttbroker start
pidof mqttbroker
logread -e mqttbroker
```

After configuration changes, run `/etc/init.d/mqttbroker restart`. The bridge and integrator provide `mqttbridge` and `mqttintegrator` services; configure each before enabling it.
