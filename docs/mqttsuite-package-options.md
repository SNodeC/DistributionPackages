# MQTTSuite package catalog

Package names are shared by OpenWrt, Raspberry Pi OS, Debian, Ubuntu, Rocky Linux
and Fedora. Architectures affect availability and binary contents, not names.

## Installation and build results

- [Install MQTTSuite, including repository setup](install-mqttsuite.md)
- [Published versions and build results](https://github.com/SNodeC/Packages/blob/main/docs/status.md)
- [Return to the repository overview](../README.md)

## Packages: 8

Library `<version>` follows the published release; `<ABI>` identifies its binary
interface. See [Package status](https://github.com/SNodeC/Packages/blob/main/docs/status.md)
for current versions.

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

Application libraries also include the real `.so.<version>` file. Each enabled
MQTT WebSocket plugin contains its `.so.<ABI>` ABI symlink and `.so.<version>` real file.

## Distribution details

- OpenWrt's broker, bridge and integrator packages include procd service scripts. DEB/RPM packages currently do not ship systemd units.
- Library directories follow the distribution's layout. WebSocket plugins are included when their transport is enabled in the build.
- Applications use SNode.C's configuration and account setup through their framework dependencies; no separate `mqttsuite-common` package is needed.
