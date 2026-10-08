# SNode.C package catalog

Package names are shared by OpenWrt, Raspberry Pi OS, Debian, Ubuntu, Rocky Linux and Fedora. Architectures affect availability and binary contents, not names.

## Installation and build results

- [Install SNode.C, including repository setup](install-snodec.md)
- [Published versions and build results](https://github.com/SNodeC/Packages/blob/main/docs/status.md)
- [Return to the repository overview](../README.md)

## Packages: 67

Library `<version>` follows the published release; `<ABI>` identifies its binary interface. See [Package status](https://github.com/SNodeC/Packages/blob/main/docs/status.md) for current versions.

| Package | Payload / role |
| --- | --- |
| `snodec-common` | Shared configuration directory and system account/group setup |
| `snodec` | Metapackage: all 63 runtime modules, demonstration apps and control tool |
| `snodec-apps` | Demonstration applications and their plugins |
| `snodec-control` | `snodec-control` configuration tool; terminal UI where enabled |
| `snodec-logger` | `libsnodec-logger.so.<ABI>` + `.so.<version>` |
| `snodec-utils` | `libsnodec-utils.so.<ABI>` + `.so.<version>` |
| `snodec-core-mux-epoll` | `libsnodec-core-mux-epoll.so.<ABI>` + `.so.<version>` |
| `snodec-core-mux-poll` | `libsnodec-core-mux-poll.so.<ABI>` + `.so.<version>` |
| `snodec-core-mux-select` | `libsnodec-core-mux-select.so.<ABI>` + `.so.<version>` |
| `snodec-core` | `libsnodec-core.so.<ABI>` + `.so.<version>` |
| `snodec-core-socket` | `libsnodec-core-socket.so.<ABI>` + `.so.<version>` |
| `snodec-core-socket-stream` | `libsnodec-core-socket-stream.so.<ABI>` + `.so.<version>` |
| `snodec-core-socket-stream-legacy` | `libsnodec-core-socket-stream-legacy.so.<ABI>` + `.so.<version>` |
| `snodec-core-socket-stream-tls` | `libsnodec-core-socket-stream-tls.so.<ABI>` + `.so.<version>` |
| `snodec-db-mariadb` | `libsnodec-db-mariadb.so.<ABI>` + `.so.<version>` |
| `snodec-net` | `libsnodec-net.so.<ABI>` + `.so.<version>` |
| `snodec-net-in` | `libsnodec-net-in.so.<ABI>` + `.so.<version>` |
| `snodec-net-in-phy` | `libsnodec-net-in-phy.so.<ABI>` + `.so.<version>` |
| `snodec-net-in-phy-stream` | `libsnodec-net-in-phy-stream.so.<ABI>` + `.so.<version>` |
| `snodec-net-in-stream` | `libsnodec-net-in-stream.so.<ABI>` + `.so.<version>` |
| `snodec-net-in-stream-legacy` | `libsnodec-net-in-stream-legacy.so.<ABI>` + `.so.<version>` |
| `snodec-net-in-stream-tls` | `libsnodec-net-in-stream-tls.so.<ABI>` + `.so.<version>` |
| `snodec-net-in6` | `libsnodec-net-in6.so.<ABI>` + `.so.<version>` |
| `snodec-net-in6-phy` | `libsnodec-net-in6-phy.so.<ABI>` + `.so.<version>` |
| `snodec-net-in6-phy-stream` | `libsnodec-net-in6-phy-stream.so.<ABI>` + `.so.<version>` |
| `snodec-net-in6-stream` | `libsnodec-net-in6-stream.so.<ABI>` + `.so.<version>` |
| `snodec-net-in6-stream-legacy` | `libsnodec-net-in6-stream-legacy.so.<ABI>` + `.so.<version>` |
| `snodec-net-in6-stream-tls` | `libsnodec-net-in6-stream-tls.so.<ABI>` + `.so.<version>` |
| `snodec-net-l2` | `libsnodec-net-l2.so.<ABI>` + `.so.<version>` |
| `snodec-net-l2-phy` | `libsnodec-net-l2-phy.so.<ABI>` + `.so.<version>` |
| `snodec-net-l2-phy-stream` | `libsnodec-net-l2-phy-stream.so.<ABI>` + `.so.<version>` |
| `snodec-net-l2-stream` | `libsnodec-net-l2-stream.so.<ABI>` + `.so.<version>` |
| `snodec-net-l2-stream-legacy` | `libsnodec-net-l2-stream-legacy.so.<ABI>` + `.so.<version>` |
| `snodec-net-l2-stream-tls` | `libsnodec-net-l2-stream-tls.so.<ABI>` + `.so.<version>` |
| `snodec-net-rc` | `libsnodec-net-rc.so.<ABI>` + `.so.<version>` |
| `snodec-net-rc-phy` | `libsnodec-net-rc-phy.so.<ABI>` + `.so.<version>` |
| `snodec-net-rc-phy-stream` | `libsnodec-net-rc-phy-stream.so.<ABI>` + `.so.<version>` |
| `snodec-net-rc-stream` | `libsnodec-net-rc-stream.so.<ABI>` + `.so.<version>` |
| `snodec-net-rc-stream-legacy` | `libsnodec-net-rc-stream-legacy.so.<ABI>` + `.so.<version>` |
| `snodec-net-rc-stream-tls` | `libsnodec-net-rc-stream-tls.so.<ABI>` + `.so.<version>` |
| `snodec-net-un` | `libsnodec-net-un.so.<ABI>` + `.so.<version>` |
| `snodec-net-un-phy` | `libsnodec-net-un-phy.so.<ABI>` + `.so.<version>` |
| `snodec-net-un-phy-stream` | `libsnodec-net-un-phy-stream.so.<ABI>` + `.so.<version>` |
| `snodec-net-un-stream` | `libsnodec-net-un-stream.so.<ABI>` + `.so.<version>` |
| `snodec-net-un-stream-legacy` | `libsnodec-net-un-stream-legacy.so.<ABI>` + `.so.<version>` |
| `snodec-net-un-stream-tls` | `libsnodec-net-un-stream-tls.so.<ABI>` + `.so.<version>` |
| `snodec-net-un-dgram` | `libsnodec-net-un-dgram.so.<ABI>` + `.so.<version>` |
| `snodec-http` | `libsnodec-http.so.<ABI>` + `.so.<version>` |
| `snodec-http-server` | `libsnodec-http-server.so.<ABI>` + `.so.<version>` |
| `snodec-http-client` | `libsnodec-http-client.so.<ABI>` + `.so.<version>` |
| `snodec-http-server-express` | `libsnodec-http-server-express.so.<ABI>` + `.so.<version>` |
| `snodec-http-server-express-legacy-in` | `libsnodec-http-server-express-legacy-in.so.<ABI>` + `.so.<version>` |
| `snodec-http-server-express-legacy-in6` | `libsnodec-http-server-express-legacy-in6.so.<ABI>` + `.so.<version>` |
| `snodec-http-server-express-legacy-rc` | `libsnodec-http-server-express-legacy-rc.so.<ABI>` + `.so.<version>` |
| `snodec-http-server-express-legacy-un` | `libsnodec-http-server-express-legacy-un.so.<ABI>` + `.so.<version>` |
| `snodec-http-server-express-tls-in` | `libsnodec-http-server-express-tls-in.so.<ABI>` + `.so.<version>` |
| `snodec-http-server-express-tls-in6` | `libsnodec-http-server-express-tls-in6.so.<ABI>` + `.so.<version>` |
| `snodec-http-server-express-tls-rc` | `libsnodec-http-server-express-tls-rc.so.<ABI>` + `.so.<version>` |
| `snodec-http-server-express-tls-un` | `libsnodec-http-server-express-tls-un.so.<ABI>` + `.so.<version>` |
| `snodec-websocket` | `libsnodec-websocket.so.<ABI>` + `.so.<version>` |
| `snodec-websocket-server` | `libsnodec-websocket-server.so.<ABI>` + `.so.<version>` |
| `snodec-websocket-client` | `libsnodec-websocket-client.so.<ABI>` + `.so.<version>` |
| `snodec-mqtt` | `libsnodec-mqtt.so.<ABI>` + `.so.<version>` |
| `snodec-mqtt-server` | `libsnodec-mqtt-server.so.<ABI>` + `.so.<version>` |
| `snodec-mqtt-client` | `libsnodec-mqtt-client.so.<ABI>` + `.so.<version>` |
| `snodec-mqtt-server-websocket` | `libsnodec-mqtt-server-websocket.so.<ABI>` + `.so.<version>` |
| `snodec-mqtt-client-websocket` | `libsnodec-mqtt-client-websocket.so.<ABI>` + `.so.<version>` |

The `net-l2-*` rows are L2CAP; the `net-rc-*` rows are RFCOMM. Selecting their upper layers selects their own lower layers and BlueZ automatically. Express supports RFCOMM; upstream does not provide an Express/L2CAP module to package.

## Distribution details

- `snodec-common` owns `/etc/snode.c/` and supplies the shared `snodec` system account and group. OpenWrt permits a custom account/group name in its build configuration.
- DEB/RPM library components also contain their headers and CMake development files. OpenWrt binary packages contain the runtime libraries; development files remain in the build SDK.
- Library directories follow the distribution's layout, including multiarch directories where applicable. The filenames above identify the libraries independently of their installation directory.
- Existing application configuration is not replaced by sample files. Log and PID directories are created by the framework when needed.
