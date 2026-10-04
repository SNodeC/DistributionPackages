# SNode.C and MQTTSuite for GL-MT3000

The [SNode.C recipe](../net/snode.c/Makefile) and
[MQTTSuite recipe](../net/mqttsuite/Makefile) declare the default source releases.
For a release build, export `SNODEC_SOURCE_TAG=vX.Y.Z` and
`MQTTSUITE_SOURCE_TAG=vA.B.C` before running the SDK commands; each recipe derives
its package version from its selected release tag. CI selects and records these
versions automatically.

The recipes use the upstream build systems without source patches. See
[Package status](https://github.com/SNodeC/Packages/blob/main/README.md#openwrt)
for published versions. The SDK commands below are a recorded GL-MT3000 example.

The build uses the official OpenWrt 25.12.5 `mediatek/filogic` SDK with GCC
14.3.0 and musl, producing `aarch64_cortex-a53` APK packages. The release's
`glinet_gl-mt3000` profile identifies this target. These packages require the
matching OpenWrt userspace and, for Bluetooth dependencies, matching kernel
ABI. They are not a claim of compatibility with GL.iNet's vendor firmware or
with an older OpenWrt release using opkg/IPK.

SDK: <https://downloads.openwrt.org/releases/25.12.5/targets/mediatek/filogic/>

Archive: `openwrt-sdk-25.12.5-mediatek-filogic_gcc-14.3.0_musl.Linux-x86_64.tar.zst`

SHA256: `ff4a38a397caa2cfe1c39e18f84ddede14878221b3593c3f2c4cfe24e3ec4c25`

## Package selection

Build-time defaults are listed under [SNode.C](#snodec-build-defaults) and
[MQTTSuite](#mqttsuite-transport-defaults) below. They apply when compiling
packages from source, not when installing pre-built packages.

Use **Network / SNode.C** and **Network / MQTTSuite** in `make menuconfig`.
OpenWrt generates a `CONFIG_PACKAGE_<package>` tristate for each package in
these recipes. `m` builds an installable package; `y` also selects it for an
image build; `n` omits it unless a selected consumer requires it. Required
lower layers are selected automatically at the consumer's selection level.
No second set of module booleans overrides these package selectors.
The complete package tables are:
[SNode.C package catalog](snodec-package-options.md) and
[MQTTSuite package catalog](mqttsuite-package-options.md).

`snode.c-full` selects all 63 shared runtime modules. The demonstration
applications and `snodec-control` have separate packages. Static/internal
CMake targets have no separate runtime payload and therefore no empty module
packages. Both RFCOMM (`net-rc`) and L2CAP (`net-l2`) have six separate layers:
address/configuration, physical socket, physical stream, stream configuration,
legacy stream and TLS stream. RFCOMM also has legacy/TLS Express packages.

`mqttsuite-full` selects all five applications and both mapping plugins.
Each application has eight existing-style transport options, including the
new MQTTStore menu. TLS depends on its base socket family; WSS depends on WS
and an enabled TLS family. WS requires a socket family. If both IPv6 and Unix
sockets are disabled, IPv4 TCP is retained so the application remains usable.
Bridge/integrator retain their upstream unconditional IPv4 HTTP/HTTPS admin
servers, even when their MQTT TLS transport is disabled.

SNode.C compiles a shared set of library targets, then packages only the
selected modules. Demonstrations compile only when their package is selected.
MQTTSuite compiles only selected applications; application WebSocket plugins
compile and ship only when WS is enabled. The mapping plugins are selected
individually for packaging.

## Reproduce the build

Extract the SDK and run the following inside it. Replace `/path/to/DistributionPackages`
with this repository's absolute path. The SDK's default feed revisions are
retained.

```sh
./scripts/feeds update base packages
./scripts/feeds install nlohmannjson libopenssl libmagic bluez-libs libmariadb
mkdir -p package/local
ln -s /path/to/DistributionPackages/net/snode.c package/local/snode.c
ln -s /path/to/DistributionPackages/net/mqttsuite package/local/mqttsuite
cat > .config <<'EOF'
# CONFIG_ALL is not set
# CONFIG_ALL_NONSHARED is not set
# CONFIG_ALL_KMODS is not set
# CONFIG_SIGNED_PACKAGES is not set
# CONFIG_AUTOREMOVE is not set
CONFIG_PACKAGE_snode.c-full=m
CONFIG_PACKAGE_snode.c-apps=m
CONFIG_PACKAGE_snode.c-control=m
CONFIG_PACKAGE_mqttsuite-full=m
EOF
make defconfig
make -j16 package/local/mqttsuite/compile V=s
```

This selects all publication packages and uses the feature defaults from the
package Makefiles and `Config.in` files. In particular, MQTTSuite's Unix-socket
TLS options retain their default of disabled. The example creates unsigned
packages for local use.

MQTTSuite's build dependency builds and stages SNode.C first. MQTTSuite uses
a separate CMake build directory so its private `lib/Log.h` cannot shadow
SNode.C's public `Log.h` through a generated-header include path. spdlog 1.17.0 is
a checked OpenWrt download, supplied to FetchContent locally. No configure-time
network fetch is needed. Every recipe configuration option participates in
OpenWrt's reconfiguration stamp; SNode.C's derived CMake cache is reset when
configuring to avoid stale defaults.

## WebSocket loading and RPATH

The HTTP loader opens
`/usr/lib/snode.c/web/http/upgrade/libsnodec-websocket-{server,client}.so.<ABI>`.
The WebSocket subprotocol loader then opens the application-specific
`/usr/lib/snode.c/web/http/upgrade/websocket/mqtt<app>/libsnodec-websocket-mqtt-{server,client}.so.<ABI>`.
MQTTSuite's plugin SONAME follows SNode.C's ABI major, while the real plugin
filename follows MQTTSuite's release version. Both the real file and ABI symlink
are packaged. Ordinary MQTTSuite libraries use MQTTSuite's ABI major.

The plugin directory identifies the `dlopen` object; its dependencies still
need the correct ELF library search paths. Before OpenWrt runs `rstrip`, the
MQTTSuite recipe removes only the literal staging-directory prefix from each
RPATH/RUNPATH entry. It preserves target subdirectories, `$ORIGIN`, unrelated
entries, permissions, and the original tag type; patchelf errors fail the
build. It does not delete or shrink all RPATHs. OpenWrt may subsequently remove
ordinary system-directory entries; the packaged libraries retain the remaining
paths on each ELF file against that package's dependency closure.

## Services and device verification

The three existing services (`mqttbroker`, `mqttintegrator`, `mqttbridge`) run
in the foreground under procd and send logs to logd. They load SNode.C's
existing `/etc/snode.c/<application>.conf` configuration files. The recipe
preserves `/etc/snode.c/` across upgrades. The bridge service starts only once
`/etc/snode.c/mqttbridge.conf` exists; configure its `bridge.definition` with a
valid bridge JSON file. Its packaged web assets are supplied through
`bridge --html-dir /usr/var/www/mqttsuite/mqttbridge`. No site-specific remote
brokers are built into the service.

MQTTStore and the CLI are independent executable packages. Configure database
credentials/storage projections and MQTT endpoints before running MQTTStore.
TLS endpoints need suitable certificates, keys and trust settings.

On the matching router firmware, install the desired APKs with their
dependencies (`apk add --allow-untrusted ./<package>.apk` for these unsigned
local builds). Supply all referenced local SNode.C packages or a local feed;
installing a single meta-package alone cannot discover unpublished packages.
Then check application help/configuration, native MQTT, WS and WSS connections,
service restart/logging, bridge forwarding, integrator mappings, and MQTTStore
writes.

## SNode.C build defaults

For source builds, package selection uses `CONFIG_PACKAGE_<name>` with
ordinary n/m/y semantics and automatic dependency selection. Build defaults
do not replace package selectors.

Every symbol below has the `CONFIG_` prefix in `.config`. Defaults shown are
menu defaults. A choice uses exactly one of its alternative symbols. Values
are passed into the existing upstream CMake settings; they are runtime defaults
that the application's existing configuration system can override.

| Config.in symbol | Meaning | Default |
| --- | --- | --- |
| `SNODEC_GROUP_NAME` | Group name of unix group used for config/log/pid file management | `snodec` |
| `SNODEC_EPOLL` | epoll | `selected` |
| `SNODEC_POLL` | poll | `not selected` |
| `SNODEC_SELECT` | select | `not selected` |
| `SNODEC_READ_BLOCKSIZE` | Read block size in bytes | `16384` |
| `SNODEC_WRITE_BLOCKSIZE` | Write block size in bytes | `16384` |
| `SNODEC_READ_TIMEOUT` | Read inactivity timeout in seconds | `60` |
| `SNODEC_WRITE_TIMEOUT` | Write inactivity timeout in seconds | `60` |
| `SNODEC_MAXIMUM_WRITE_QUEUE_BYTES` | Maximum queued write bytes (0 = unlimited) | `0` |
| `SNODEC_WRITE_QUEUE_HIGH_WATERMARK` | Pipe write queue high watermark (0 = automatic) | `0` |
| `SNODEC_WRITE_QUEUE_LOW_WATERMARK` | Pipe write queue low watermark | `0` |
| `SNODEC_BACKLOG` | Listen backlog | `5` |
| `SNODEC_ACCEPTS_PER_TICK` | Accepts per tick | `1` |
| `SNODEC_ACCEPT_TIMEOUT` | Accept inactivity timeout in seconds | `0` |
| `SNODEC_CONNECT_TIMEOUT` | Connect timeout in seconds | `10` |
| `SNODEC_TERMINATE_TIMEOUT` | Shutdown timeout in seconds | `1` |
| `SNODEC_RECONNECT` | Reconnect after disconnect | `n` |
| `SNODEC_RECONNECT_TIME` | Reconnect time in seconds | `1` |
| `SNODEC_RETRY` | Retry listen and connect | `n` |
| `SNODEC_RETRY_ON_FATAL` | Retry also on fatal error | `n` |
| `SNODEC_RETRY_TIMEOUT` | Retry interval in seconds | `1` |
| `SNODEC_RETRY_TRIES` | Upper limit of retry tries | `0` |
| `SNODEC_RETRY_BASE` | Base of exponential increase | `"1.8"` |
| `SNODEC_RETRY_JITTER` | Jitter of retry timeout in percent | `0` |
| `SNODEC_RETRY_LIMIT` | Upper limit of retry timeout in seconds | `0` |
| `SNODEC_INV4_REUSE_ADDRESS` | Reuse address | `n` |
| `SNODEC_INV4_REUSE_PORT` | Reuse port | `n` |
| `SNODEC_INV4_DISABLE_NAGLE_ALGORITHM_TRUE` | true | `not selected` |
| `SNODEC_INV4_DISABLE_NAGLE_ALGORITHM_FALSE` | false | `not selected` |
| `SNODEC_INV4_DISABLE_NAGLE_ALGORITHM_DEFAULT` | default | `selected` |
| `SNODEC_IPV4_NUMERIC` | Accept numeric IPv4 hostnames only | `n` |
| `SNODEC_IPV4_NUMERIC_REVERSE` | Numeric IPv4 reverse lookup | `n` |
| `SNODEC_IN6_REUSE_ADDRESS` | Reuse address | `n` |
| `SNODEC_IN6_REUSE_PORT` | Reuse port | `n` |
| `SNODEC_INV6_DISABLE_NAGLE_ALGORITHM_TRUE` | true | `not selected` |
| `SNODEC_INV6_DISABLE_NAGLE_ALGORITHM_FALSE` | false | `not selected` |
| `SNODEC_INV6_DISABLE_NAGLE_ALGORITHM_DEFAULT` | default | `selected` |
| `SNODEC_IPV6_ONLY` | IPv6 only | `n` |
| `SNODEC_IPV4_MAPPED` | IPv4-mapped IPv6 addresses | `n` |
| `SNODEC_IPV6_NUMERIC` | Accept numeric IPv6 hostnames only | `n` |
| `SNODEC_IPV6_NUMERIC_REVERSE` | Numeric IPv6 reverse lookup | `n` |
| `SNODEC_TLS_INIT_TIMEOUT` | SSL/TLS initial handshake timeout in seconds | `10` |
| `SNODEC_TLS_SHUTDOWN_TIMEOUT` | SSL/TLS teardown timeout in seconds | `2` |
| `SNODEC_HTTP_REQUEST_PIPELINED` | Pipelined requests | `y` |

Read/write sizes, timeouts, retry/reconnect settings and write-queue limits
configure `snode.c-net`. IPv4/IPv6 stream flags configure their stream layers;
name-resolution flags configure their address layers. TLS defaults are shared
by TLS endpoints. HTTP pipelining configures the HTTP client. The I/O choice
controls the core's linked default multiplexer and its package dependency;
selecting extra multiplexer packages does not change that default.

All 44 SNode.C default/choice symbols and the demo selector participate in
recipe reconfiguration. Other module selectors govern package emission and
dependency closure; they do not prune the shared library compilation pass.

## MQTTSuite transport defaults

For source builds, package selection uses `CONFIG_PACKAGE_<name>` with
ordinary n/m/y semantics and automatic dependency selection. Build defaults
do not replace package selectors.

All rows have the `CONFIG_` prefix in `.config`. Enabling a row compiles that
application's endpoint support and selects the matching SNode.C packages.
WS/WSS select the appropriate client/server WebSocket MQTT modules. Both share
one application plugin; it is absent when WS is disabled.

| Config.in symbol | Default | Required options |
| --- | --- | --- |
| `MQTTSUITE_BROKER_TCP_IPV4` | `y` | None |
| `MQTTSUITE_BROKER_TLS_IPV4` | `y` | MQTTSUITE_BROKER_TCP_IPV4 |
| `MQTTSUITE_BROKER_TCP_IPV6` | `y` | None |
| `MQTTSUITE_BROKER_TLS_IPV6` | `y` | MQTTSUITE_BROKER_TCP_IPV6 |
| `MQTTSUITE_BROKER_UNIX` | `y` | None |
| `MQTTSUITE_BROKER_UNIX_TLS` | `n` | MQTTSUITE_BROKER_UNIX |
| `MQTTSUITE_BROKER_WS` | `y` | MQTTSUITE_BROKER_TCP_IPV4 or MQTTSUITE_BROKER_TCP_IPV6 or MQTTSUITE_BROKER_UNIX |
| `MQTTSUITE_BROKER_WSS` | `y` | MQTTSUITE_BROKER_WS; MQTTSUITE_BROKER_TLS_IPV4 or MQTTSUITE_BROKER_TLS_IPV6 or MQTTSUITE_BROKER_UNIX_TLS |
| `MQTTSUITE_INTEGRATOR_TCP_IPV4` | `y` | None |
| `MQTTSUITE_INTEGRATOR_TLS_IPV4` | `y` | MQTTSUITE_INTEGRATOR_TCP_IPV4 |
| `MQTTSUITE_INTEGRATOR_TCP_IPV6` | `y` | None |
| `MQTTSUITE_INTEGRATOR_TLS_IPV6` | `y` | MQTTSUITE_INTEGRATOR_TCP_IPV6 |
| `MQTTSUITE_INTEGRATOR_UNIX` | `y` | None |
| `MQTTSUITE_INTEGRATOR_UNIX_TLS` | `n` | MQTTSUITE_INTEGRATOR_UNIX |
| `MQTTSUITE_INTEGRATOR_WS` | `y` | MQTTSUITE_INTEGRATOR_TCP_IPV4 or MQTTSUITE_INTEGRATOR_TCP_IPV6 or MQTTSUITE_INTEGRATOR_UNIX |
| `MQTTSUITE_INTEGRATOR_WSS` | `y` | MQTTSUITE_INTEGRATOR_WS; MQTTSUITE_INTEGRATOR_TLS_IPV4 or MQTTSUITE_INTEGRATOR_TLS_IPV6 or MQTTSUITE_INTEGRATOR_UNIX_TLS |
| `MQTTSUITE_BRIDGE_TCP_IPV4` | `y` | None |
| `MQTTSUITE_BRIDGE_TLS_IPV4` | `y` | MQTTSUITE_BRIDGE_TCP_IPV4 |
| `MQTTSUITE_BRIDGE_TCP_IPV6` | `y` | None |
| `MQTTSUITE_BRIDGE_TLS_IPV6` | `y` | MQTTSUITE_BRIDGE_TCP_IPV6 |
| `MQTTSUITE_BRIDGE_UNIX` | `y` | None |
| `MQTTSUITE_BRIDGE_UNIX_TLS` | `n` | MQTTSUITE_BRIDGE_UNIX |
| `MQTTSUITE_BRIDGE_WS` | `y` | MQTTSUITE_BRIDGE_TCP_IPV4 or MQTTSUITE_BRIDGE_TCP_IPV6 or MQTTSUITE_BRIDGE_UNIX |
| `MQTTSUITE_BRIDGE_WSS` | `y` | MQTTSUITE_BRIDGE_WS; MQTTSUITE_BRIDGE_TLS_IPV4 or MQTTSUITE_BRIDGE_TLS_IPV6 or MQTTSUITE_BRIDGE_UNIX_TLS |
| `MQTTSUITE_CLI_TCP_IPV4` | `y` | None |
| `MQTTSUITE_CLI_TLS_IPV4` | `y` | MQTTSUITE_CLI_TCP_IPV4 |
| `MQTTSUITE_CLI_TCP_IPV6` | `y` | None |
| `MQTTSUITE_CLI_TLS_IPV6` | `y` | MQTTSUITE_CLI_TCP_IPV6 |
| `MQTTSUITE_CLI_UNIX` | `y` | None |
| `MQTTSUITE_CLI_UNIX_TLS` | `n` | MQTTSUITE_CLI_UNIX |
| `MQTTSUITE_CLI_WS` | `y` | MQTTSUITE_CLI_TCP_IPV4 or MQTTSUITE_CLI_TCP_IPV6 or MQTTSUITE_CLI_UNIX |
| `MQTTSUITE_CLI_WSS` | `y` | MQTTSUITE_CLI_WS; MQTTSUITE_CLI_TLS_IPV4 or MQTTSUITE_CLI_TLS_IPV6 or MQTTSUITE_CLI_UNIX_TLS |
| `MQTTSUITE_STORE_TCP_IPV4` | `y` | None |
| `MQTTSUITE_STORE_TLS_IPV4` | `y` | MQTTSUITE_STORE_TCP_IPV4 |
| `MQTTSUITE_STORE_TCP_IPV6` | `y` | None |
| `MQTTSUITE_STORE_TLS_IPV6` | `y` | MQTTSUITE_STORE_TCP_IPV6 |
| `MQTTSUITE_STORE_UNIX` | `y` | None |
| `MQTTSUITE_STORE_UNIX_TLS` | `n` | MQTTSUITE_STORE_UNIX |
| `MQTTSUITE_STORE_WS` | `y` | MQTTSUITE_STORE_TCP_IPV4 or MQTTSUITE_STORE_TCP_IPV6 or MQTTSUITE_STORE_UNIX |
| `MQTTSUITE_STORE_WSS` | `y` | MQTTSUITE_STORE_WS; MQTTSUITE_STORE_TLS_IPV4 or MQTTSUITE_STORE_TLS_IPV6 or MQTTSUITE_STORE_UNIX_TLS |

The IPv4 TCP switch is mandatory when both IPv6 TCP and Unix sockets are off.
Integrator and bridge have upstream unconditional IPv4 HTTP and HTTPS admin
servers, so disabling MQTT TLS does not remove their admin TLS dependency.

All 40 transport symbols and the five application selectors participate in
recipe reconfiguration. Mapping plugin selectors govern separate package
emission. SNode.C is a build/runtime dependency.
