# DEB and RPM component packages

[← All distributions](../README.md#distributions)

## Component packages

The `snodec` and `mqttsuite` metapackages install their respective complete
component sets. Selective application installs pull required framework modules
automatically. OpenWrt uses different names; see the [name map](../README.md#packages).

### SNode.C

| Package | Contents |
| --- | --- |
| `snodec` | All framework components, headers, examples and configuration tool |
| `snodec-core` | Core networking framework |
| `snodec-http-server` | HTTP server library |
| `snodec-mqtt-server` | MQTT server library |
| `snodec-apps` | Demonstration applications |
| `snodec-unspecified` | Component containing the `snodec-control` executable |

List all available framework component packages:

```sh
# APT distributions
apt-cache pkgnames snodec- | sort
```

```sh
# RPM distributions
dnf list --available 'snodec-*'
```

### MQTTSuite

| Package | Contents |
| --- | --- |
| `mqttsuite` | All five applications and both mapping plugins |
| `mqttsuite-broker` | Broker, library, WebSocket plugin and web assets |
| `mqttsuite-bridge` | Bridge, library, WebSocket plugin and web assets |
| `mqttsuite-integrator` | Integrator, library and WebSocket plugin |
| `mqttsuite-cli` | Command-line client, library and WebSocket plugin |
| `mqttsuite-store` | Store, library and WebSocket plugin; requires a configured database |
| `mqttsuite-mapping-double` | Double mapping plugin |
| `mqttsuite-mapping-storage` | Storage mapping plugin |

## Installation guides

- [Raspberry Pi OS](raspberrypi.md)
- [Debian](debian.md)
- [Ubuntu](ubuntu.md)
- [Rocky Linux](rocky.md)
- [Fedora](fedora.md)

For OpenWrt, use the [SNode.C](snodec-package-options.md) and
[MQTTSuite](mqttsuite-package-options.md) catalogs.
See [Package status](https://github.com/SNodeC/Packages/blob/main/docs/status.md)
for the available versions and [Signing keys](../README.md#signing-keys) for fingerprints.
