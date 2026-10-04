# MQTTSuite package catalog

These package names apply to **OpenWrt**.

## Installation and build results

- [Install MQTTSuite, including repository setup](install-mqttsuite.md)
- [DEB and RPM component packages](linux.md#mqttsuite)
- [Published versions and build results](https://github.com/SNodeC/Packages/blob/main/README.md#openwrt)
- [Return to the repository overview](../README.md)

## Packages: 9

Library `<version>` follows the published release; `<ABI>` identifies its binary
interface. See [Package status](https://github.com/SNodeC/Packages/blob/main/README.md)
for current versions.

| Package | Payload / role |
| --- | --- |
| `mqttsuite` | Empty configuration anchor |
| `mqttsuite-broker` | mqttbroker, `libmqtt-broker.so.<ABI>`, optional server plugin, web assets, procd service |
| `mqttsuite-integrator` | mqttintegrator, `libmqtt-integrator.so.<ABI>`, optional client plugin, procd service |
| `mqttsuite-bridge` | mqttbridge, `libmqtt-bridge.so.<ABI>`, optional client plugin, web assets, procd service |
| `mqttsuite-cli` | mqttcli, `libmqtt-cli.so.<ABI>`, optional client plugin |
| `mqttsuite-store` | mqttstore, `libmqtt-store.so.<ABI>`, optional client plugin; requires MariaDB support |
| `mqttsuite-mapping-double` | /usr/lib/libmqtt-mapping-plugin-double.so |
| `mqttsuite-mapping-storage` | /usr/lib/libmqtt-mapping-plugin-storage.so |
| `mqttsuite-full` | Metapackage: all five applications and both mapping plugins |

Application libraries also include the real `.so.<version>` file. Each enabled
MQTT WebSocket plugin contains its `.so.<ABI>` ABI symlink and `.so.<version>` real file.
