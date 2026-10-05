# DEB and RPM component packages

[← All distributions](../README.md#distributions)

## Component packages

The same package names apply across distributions. The complete inventories live
in the project catalogs; this page explains how to query DEB/RPM repositories.

### SNode.C

See the [SNode.C package catalog](snodec-package-options.md) for the complete
framework, shared setup, individual modules, applications and configuration tool.

List available framework packages:

```sh
# APT distributions
apt-cache pkgnames snodec- | sort
```

```sh
# RPM distributions
dnf list --available 'snodec-*'
```

### MQTTSuite

See the [MQTTSuite package catalog](mqttsuite-package-options.md) for the complete
suite, individual applications and mapping plugins.

## Installation guides

- [Raspberry Pi OS](raspberrypi.md)
- [Debian](debian.md)
- [Ubuntu](ubuntu.md)
- [Rocky Linux](rocky.md)
- [Fedora](fedora.md)

See [Package status](https://github.com/SNodeC/Packages/blob/main/docs/status.md)
for the available versions and [Signing keys](../README.md#signing-keys) for fingerprints.
