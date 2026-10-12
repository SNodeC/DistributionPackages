<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->

<!-- snodec:begin page-header -->
<a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="../media/nav/banner-catalogs-compact.svg"><img src="../media/nav/banner-catalogs.svg" alt="Packages — Catalogs" width="100%"></picture></p>
<p><a href="README.md#page-overview" title="Up to Catalogs"><picture><source media="(prefers-color-scheme: dark)" srcset="../media/nav/up-catalogs-dark.svg"><img src="../media/nav/up-catalogs-light.svg" alt="Up to Catalogs" title="Up to Catalogs" width="160" height="28"></picture></a><a href="https://github.com/SNodeC" title="SNodeC organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/organization-dark.svg"><img align="right" src="../media/nav/organization-light.svg" alt="SNodeC organization" title="SNodeC organization"></picture></a><a href="../../README.md#project-overview" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/repository-dark.svg"><img align="right" src="../media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# SNode.C package catalog

<!-- snodec:begin menu -->
[![Install](../media/menu/install.svg)](../../README.md#install) [![Status](../media/menu/status.svg)](../../status/snodec.md#page-overview) [![Catalog](../media/menu/catalog.svg)](#package-catalog) [![Details](../media/menu/details.svg)](#distribution-details) [![Query](../media/menu/query.svg)](#query-available-packages) [![Use](../media/menu/use.svg)](#after-installation)
<!-- snodec:end menu -->

Package names are shared by OpenWrt, Raspberry Pi OS, Debian, Ubuntu, Rocky Linux and Fedora. Architectures affect availability and binary contents, not names.

## Package catalog

Each library package installs `lib<package>.so.<ABI>` and its real `.so.<version>` file; `<ABI>` identifies the binary interface and `<version>` follows the source release. [Package status](../../status/snodec.md#page-overview) shows current versions.

| Package | Payload / role |
| --- | --- |
| `snodec-common` | Shared configuration directory and system account/group setup |
| `snodec` | Metapackage: all runtime modules, demonstration apps and control tool |
| `snodec-apps` | Demonstration applications and their plugins |
| `snodec-control` | `snodec-control` configuration tool; terminal UI where enabled |

### Libraries by layer

**Support**

`snodec-logger`, `snodec-utils`.

**Core**

`snodec-core-mux-epoll`, `snodec-core-mux-poll`, `snodec-core-mux-select`, `snodec-core`, `snodec-core-socket`, `snodec-core-socket-stream`, `snodec-core-socket-stream-legacy`, `snodec-core-socket-stream-tls`.

**Database**

`snodec-db-mariadb`.

**Transports**

`snodec-net`, `snodec-net-in`, `snodec-net-in-phy`, `snodec-net-in-phy-stream`, `snodec-net-in-stream`, `snodec-net-in-stream-legacy`, `snodec-net-in-stream-tls`, `snodec-net-in6`, `snodec-net-in6-phy`, `snodec-net-in6-phy-stream`, `snodec-net-in6-stream`, `snodec-net-in6-stream-legacy`, `snodec-net-in6-stream-tls`, `snodec-net-l2`, `snodec-net-l2-phy`, `snodec-net-l2-phy-stream`, `snodec-net-l2-stream`, `snodec-net-l2-stream-legacy`, `snodec-net-l2-stream-tls`, `snodec-net-rc`, `snodec-net-rc-phy`, `snodec-net-rc-phy-stream`, `snodec-net-rc-stream`, `snodec-net-rc-stream-legacy`, `snodec-net-rc-stream-tls`, `snodec-net-un`, `snodec-net-un-phy`, `snodec-net-un-phy-stream`, `snodec-net-un-stream`, `snodec-net-un-stream-legacy`, `snodec-net-un-stream-tls`, `snodec-net-un-dgram`.

**HTTP / Express**

`snodec-http`, `snodec-http-server`, `snodec-http-client`, `snodec-http-server-express`, `snodec-http-server-express-legacy-in`, `snodec-http-server-express-legacy-in6`, `snodec-http-server-express-legacy-rc`, `snodec-http-server-express-legacy-un`, `snodec-http-server-express-tls-in`, `snodec-http-server-express-tls-in6`, `snodec-http-server-express-tls-rc`, `snodec-http-server-express-tls-un`.

**WebSocket**

`snodec-websocket`, `snodec-websocket-server`, `snodec-websocket-client`.

**MQTT**

`snodec-mqtt`, `snodec-mqtt-server`, `snodec-mqtt-client`, `snodec-mqtt-server-websocket`, `snodec-mqtt-client-websocket`.

The `net-l2-*` packages are L2CAP; the `net-rc-*` rows are RFCOMM. Selecting their upper layers selects their own lower layers and BlueZ automatically. Express supports RFCOMM; upstream does not provide an Express/L2CAP module to package.

Choose the module your application uses; its package dependencies select the required lower layers. For example, published `snodec-core-socket-stream-tls` records require `snodec-core-socket-stream`. Inspect dependency metadata for your own distribution rather than installing every module.

## Distribution details

- `snodec-common` owns `/etc/snode.c/` and supplies the shared `snodec` system account and group. OpenWrt permits a custom account/group name in its build configuration.
- DEB/RPM library components also contain their headers and CMake development files. OpenWrt binary packages contain the runtime libraries; development files remain in the build SDK.
- Library directories follow the distribution's layout, including multiarch directories where applicable. The shared filename pattern identifies libraries independently of their installation directory.
- Existing application configuration is not replaced by sample files. Log and PID directories are created by the framework when needed.

## Query available packages

Patterns include the bare metapackage and its components. APT lists known names (including virtual or unavailable entries); consult `apt-cache policy <package>` before choosing a version. The remaining commands query repository metadata.

```sh
# APT distributions
apt-cache pkgnames snodec | sort
# RPM distributions
dnf list --available 'snodec*'
```

```sh
# OpenWrt 24.10 (opkg)
opkg list 'snodec*'
# OpenWrt 25.12 (APK)
apk search 'snodec*'
```

## After installation

Use `snodec-control --help` to inspect framework configuration. Runtime modules, development files and demonstration programs are different components; installing packages does not configure a network service. Continue with the [framework documentation](https://github.com/SNodeC/snode.c#project-overview).
