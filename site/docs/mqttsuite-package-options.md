<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->
<a id="page-overview"></a>

[![Packages](media/page-banner.svg)](../README.md#project-overview)

# MQTTSuite package catalog

[![Install](media/menu/install.svg)](../README.md#install) [![Status](media/menu/status.svg)](../status/mqttsuite.md#page-overview) [![Catalog](media/menu/catalog.svg)](#package-catalog) [![Details](media/menu/details.svg)](#distribution-details) [![Query](media/menu/query.svg)](#query-available-packages) [![Use](media/menu/use.svg)](#after-installation)
Package names are shared by OpenWrt, Raspberry Pi OS, Debian, Ubuntu, Rocky Linux and Fedora. Architectures affect availability and binary contents, not names.

## Package catalog

Library `<version>` follows the published release; `<ABI>` identifies its binary interface. See [Package status](../status/mqttsuite.md#page-overview) for current versions.

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

[![Deploy safely](media/menu/deploy.svg)](https://github.com/SNodeC/mqttsuite/blob/HEAD/docs/readme/deployment.md#page-overview)

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
