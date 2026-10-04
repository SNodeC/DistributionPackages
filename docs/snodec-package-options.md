# SNode.C package catalog

These package names apply to **OpenWrt**.

## Installation and build results

- [Install SNode.C, including repository setup](install-snodec.md)
- [DEB and RPM component packages](linux.md#snodec)
- [Published versions and build results](https://github.com/SNodeC/Packages/blob/main/docs/status.md#openwrt)
- [Return to the repository overview](../README.md)

## Packages: 67

Library `<version>` follows the published release; `<ABI>` identifies its binary
interface. See [Package status](https://github.com/SNodeC/Packages/blob/main/docs/status.md)
for current versions.

| Package | Payload / role |
| --- | --- |
| `snode.c` | Configuration directory, account/group registration |
| `snode.c-full` | Meta-package: all 63 runtime modules |
| `snode.c-apps` | Demonstration executables and two echo WebSocket plugins |
| `snode.c-control` | `/usr/bin/snodec-control` (CLI) |
| `snode.c-logger` | `/usr/lib/libsnodec-logger.so.<ABI>` + `.so.<version>` |
| `snode.c-utils` | `/usr/lib/libsnodec-utils.so.<ABI>` + `.so.<version>` |
| `snode.c-core-mux-epoll` | `/usr/lib/libsnodec-core-mux-epoll.so.<ABI>` + `.so.<version>` |
| `snode.c-core-mux-poll` | `/usr/lib/libsnodec-core-mux-poll.so.<ABI>` + `.so.<version>` |
| `snode.c-core-mux-select` | `/usr/lib/libsnodec-core-mux-select.so.<ABI>` + `.so.<version>` |
| `snode.c-core` | `/usr/lib/libsnodec-core.so.<ABI>` + `.so.<version>` |
| `snode.c-core-socket` | `/usr/lib/libsnodec-core-socket.so.<ABI>` + `.so.<version>` |
| `snode.c-core-socket-stream` | `/usr/lib/libsnodec-core-socket-stream.so.<ABI>` + `.so.<version>` |
| `snode.c-core-socket-stream-legacy` | `/usr/lib/libsnodec-core-socket-stream-legacy.so.<ABI>` + `.so.<version>` |
| `snode.c-core-socket-stream-tls` | `/usr/lib/libsnodec-core-socket-stream-tls.so.<ABI>` + `.so.<version>` |
| `snode.c-db-mariadb` | `/usr/lib/libsnodec-db-mariadb.so.<ABI>` + `.so.<version>` |
| `snode.c-net` | `/usr/lib/libsnodec-net.so.<ABI>` + `.so.<version>` |
| `snode.c-net-in` | `/usr/lib/libsnodec-net-in.so.<ABI>` + `.so.<version>` |
| `snode.c-net-in-phy` | `/usr/lib/libsnodec-net-in-phy.so.<ABI>` + `.so.<version>` |
| `snode.c-net-in-phy-stream` | `/usr/lib/libsnodec-net-in-phy-stream.so.<ABI>` + `.so.<version>` |
| `snode.c-net-in-stream` | `/usr/lib/libsnodec-net-in-stream.so.<ABI>` + `.so.<version>` |
| `snode.c-net-in-stream-legacy` | `/usr/lib/libsnodec-net-in-stream-legacy.so.<ABI>` + `.so.<version>` |
| `snode.c-net-in-stream-tls` | `/usr/lib/libsnodec-net-in-stream-tls.so.<ABI>` + `.so.<version>` |
| `snode.c-net-in6` | `/usr/lib/libsnodec-net-in6.so.<ABI>` + `.so.<version>` |
| `snode.c-net-in6-phy` | `/usr/lib/libsnodec-net-in6-phy.so.<ABI>` + `.so.<version>` |
| `snode.c-net-in6-phy-stream` | `/usr/lib/libsnodec-net-in6-phy-stream.so.<ABI>` + `.so.<version>` |
| `snode.c-net-in6-stream` | `/usr/lib/libsnodec-net-in6-stream.so.<ABI>` + `.so.<version>` |
| `snode.c-net-in6-stream-legacy` | `/usr/lib/libsnodec-net-in6-stream-legacy.so.<ABI>` + `.so.<version>` |
| `snode.c-net-in6-stream-tls` | `/usr/lib/libsnodec-net-in6-stream-tls.so.<ABI>` + `.so.<version>` |
| `snode.c-net-l2` | `/usr/lib/libsnodec-net-l2.so.<ABI>` + `.so.<version>` |
| `snode.c-net-l2-phy` | `/usr/lib/libsnodec-net-l2-phy.so.<ABI>` + `.so.<version>` |
| `snode.c-net-l2-phy-stream` | `/usr/lib/libsnodec-net-l2-phy-stream.so.<ABI>` + `.so.<version>` |
| `snode.c-net-l2-stream` | `/usr/lib/libsnodec-net-l2-stream.so.<ABI>` + `.so.<version>` |
| `snode.c-net-l2-stream-legacy` | `/usr/lib/libsnodec-net-l2-stream-legacy.so.<ABI>` + `.so.<version>` |
| `snode.c-net-l2-stream-tls` | `/usr/lib/libsnodec-net-l2-stream-tls.so.<ABI>` + `.so.<version>` |
| `snode.c-net-rc` | `/usr/lib/libsnodec-net-rc.so.<ABI>` + `.so.<version>` |
| `snode.c-net-rc-phy` | `/usr/lib/libsnodec-net-rc-phy.so.<ABI>` + `.so.<version>` |
| `snode.c-net-rc-phy-stream` | `/usr/lib/libsnodec-net-rc-phy-stream.so.<ABI>` + `.so.<version>` |
| `snode.c-net-rc-stream` | `/usr/lib/libsnodec-net-rc-stream.so.<ABI>` + `.so.<version>` |
| `snode.c-net-rc-stream-legacy` | `/usr/lib/libsnodec-net-rc-stream-legacy.so.<ABI>` + `.so.<version>` |
| `snode.c-net-rc-stream-tls` | `/usr/lib/libsnodec-net-rc-stream-tls.so.<ABI>` + `.so.<version>` |
| `snode.c-net-un` | `/usr/lib/libsnodec-net-un.so.<ABI>` + `.so.<version>` |
| `snode.c-net-un-phy` | `/usr/lib/libsnodec-net-un-phy.so.<ABI>` + `.so.<version>` |
| `snode.c-net-un-phy-stream` | `/usr/lib/libsnodec-net-un-phy-stream.so.<ABI>` + `.so.<version>` |
| `snode.c-net-un-stream` | `/usr/lib/libsnodec-net-un-stream.so.<ABI>` + `.so.<version>` |
| `snode.c-net-un-stream-legacy` | `/usr/lib/libsnodec-net-un-stream-legacy.so.<ABI>` + `.so.<version>` |
| `snode.c-net-un-stream-tls` | `/usr/lib/libsnodec-net-un-stream-tls.so.<ABI>` + `.so.<version>` |
| `snode.c-net-un-dgram` | `/usr/lib/libsnodec-net-un-dgram.so.<ABI>` + `.so.<version>` |
| `snode.c-http` | `/usr/lib/snode.c/web/http/libsnodec-http.so.<ABI>` + `.so.<version>` |
| `snode.c-http-server` | `/usr/lib/snode.c/web/http/libsnodec-http-server.so.<ABI>` + `.so.<version>` |
| `snode.c-http-client` | `/usr/lib/snode.c/web/http/libsnodec-http-client.so.<ABI>` + `.so.<version>` |
| `snode.c-http-server-express` | `/usr/lib/snode.c/web/http/libsnodec-http-server-express.so.<ABI>` + `.so.<version>` |
| `snode.c-http-server-express-legacy-in` | `/usr/lib/snode.c/web/http/libsnodec-http-server-express-legacy-in.so.<ABI>` + `.so.<version>` |
| `snode.c-http-server-express-legacy-in6` | `/usr/lib/snode.c/web/http/libsnodec-http-server-express-legacy-in6.so.<ABI>` + `.so.<version>` |
| `snode.c-http-server-express-legacy-rc` | `/usr/lib/snode.c/web/http/libsnodec-http-server-express-legacy-rc.so.<ABI>` + `.so.<version>` |
| `snode.c-http-server-express-legacy-un` | `/usr/lib/snode.c/web/http/libsnodec-http-server-express-legacy-un.so.<ABI>` + `.so.<version>` |
| `snode.c-http-server-express-tls-in` | `/usr/lib/snode.c/web/http/libsnodec-http-server-express-tls-in.so.<ABI>` + `.so.<version>` |
| `snode.c-http-server-express-tls-in6` | `/usr/lib/snode.c/web/http/libsnodec-http-server-express-tls-in6.so.<ABI>` + `.so.<version>` |
| `snode.c-http-server-express-tls-rc` | `/usr/lib/snode.c/web/http/libsnodec-http-server-express-tls-rc.so.<ABI>` + `.so.<version>` |
| `snode.c-http-server-express-tls-un` | `/usr/lib/snode.c/web/http/libsnodec-http-server-express-tls-un.so.<ABI>` + `.so.<version>` |
| `snode.c-websocket` | `/usr/lib/snode.c/web/http/upgrade/libsnodec-websocket.so.<ABI>` + `.so.<version>` |
| `snode.c-websocket-server` | `/usr/lib/snode.c/web/http/upgrade/libsnodec-websocket-server.so.<ABI>` + `.so.<version>` |
| `snode.c-websocket-client` | `/usr/lib/snode.c/web/http/upgrade/libsnodec-websocket-client.so.<ABI>` + `.so.<version>` |
| `snode.c-mqtt` | `/usr/lib/snode.c/iot/mqtt/libsnodec-mqtt.so.<ABI>` + `.so.<version>` |
| `snode.c-mqtt-server` | `/usr/lib/snode.c/iot/mqtt/libsnodec-mqtt-server.so.<ABI>` + `.so.<version>` |
| `snode.c-mqtt-client` | `/usr/lib/snode.c/iot/mqtt/libsnodec-mqtt-client.so.<ABI>` + `.so.<version>` |
| `snode.c-mqtt-server-websocket` | `/usr/lib/snode.c/iot/mqtt/libsnodec-mqtt-server-websocket.so.<ABI>` + `.so.<version>` |
| `snode.c-mqtt-client-websocket` | `/usr/lib/snode.c/iot/mqtt/libsnodec-mqtt-client-websocket.so.<ABI>` + `.so.<version>` |

The `net-l2-*` rows are L2CAP; the `net-rc-*` rows are RFCOMM. Selecting their
upper layers selects their own lower layers and BlueZ automatically. Express
supports RFCOMM; upstream does not provide an Express/L2CAP module to package.
