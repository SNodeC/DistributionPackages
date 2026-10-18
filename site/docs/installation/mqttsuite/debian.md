<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->

<!-- snodec:begin page-header -->
<a id="banner"></a><a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="../../media/nav/banner-installation-compact.svg"><img src="../../media/nav/banner-installation.svg" alt="Packages — Installation" width="100%"></picture></p>
<p><a href="README.md#banner" title="Up to Installation"><picture><source media="(prefers-color-scheme: dark)" srcset="../../media/nav/up-installation-dark.svg"><img src="../../media/nav/up-installation-light.svg" alt="Up to Installation" title="Up to Installation" width="160" height="28"></picture></a><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../../media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="../../media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../../media/nav/account-dark.svg"><img align="right" src="../../media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../../media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="../../media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../../media/nav/organization-dark.svg"><img align="right" src="../../media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../../../README.md#banner" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../../media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="../../media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../../media/nav/repository-dark.svg"><img align="right" src="../../media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# MQTTSuite on Debian

[Requirements](#requirements) · [Quick install](#quick-install) · [Components](#components) · [Verify](#verify) · [Configure](#configure) · [Update](#update)

## Requirements

Supported releases: `trixie`, `forky`, `sid`. Match the release and package architecture installed on your device. Keep official repositories enabled for dependencies.

Read [Debian prerequisites](../../repositories/debian.md#banner), including platform and repository requirements, before running the installer. Check [MQTTSuite availability](../../../status/mqttsuite.md#banner) for your release and architecture; a supported target may still be building.

## Quick install

Install the MQTT broker and command-line client. The installer prepares the signed repository and installs only this selection and its dependencies. It does not configure or start the application.

```sh
(
  set -eu
  tmp=$(mktemp -d /tmp/snodec.XXXXXX)
  trap 'rm -rf "$tmp"' EXIT HUP INT TERM
  base=https://raw.githubusercontent.com/SNodeC/Packages/main/install
  for script in install.sh mqttsuite.sh; do
    curl -fsSL "$base/$script" -o "$tmp/$script"
  done
  sudo sh "$tmp/mqttsuite.sh" --component broker --component cli
)
```

On Sid, append `--suite sid` to the installer invocation. Use `--suite forky` if a Forky installation is not detected correctly. This selects a repository; it does not upgrade Debian.

For repository preparation only, use the shared `install.sh --prepare`; see [repository setup](../../repositories/debian.md#banner).

## Components

Choose the roles you need. These package-manager commands assume repository setup is complete. Repeat `--component NAME` on the project installer to select the same roles.

### Broker

Installer option: `--component broker`.

```sh
sudo apt-get install mqttsuite-broker
```

### Command-line client

Installer option: `--component cli`.

```sh
sudo apt-get install mqttsuite-cli
```

### Bridge

Installer option: `--component bridge`.

```sh
sudo apt-get install mqttsuite-bridge
```

### Integrator

Installer option: `--component integrator`.

```sh
sudo apt-get install mqttsuite-integrator
```

### Database storage application

Installer option: `--component store`.

```sh
sudo apt-get install mqttsuite-store
```

### Double mapping plugin

Installer option: `--component mapping-double`.

```sh
sudo apt-get install mqttsuite-mapping-double
```

### Storage mapping plugin

Installer option: `--component mapping-storage`.

```sh
sudo apt-get install mqttsuite-mapping-storage
```

### Complete MQTTSuite

Installer option: `--component all`.

```sh
sudo apt-get install mqttsuite
```

See the [MQTTSuite package catalog](../../catalogs/mqttsuite.md#banner) for package responsibilities and dependencies. Installing a component does not select the complete project metapackage.

## Verify

For the quick-install selection above:

```sh
dpkg-query -W -f='${Package} ${Version} ${Status}\n' mqttsuite-broker mqttsuite-cli
```

Every requested package must be installed. Substitute your chosen package names if you selected different components.

## Configure

Follow the [MQTTSuite configuration instructions](../../catalogs/mqttsuite.md#after-installation) before starting applications or enabling services.

## Update

Update the packages you selected. For the quick-install selection:

```sh
sudo apt-get update
sudo apt-get install --only-upgrade mqttsuite-broker mqttsuite-cli
```

Use your installed component names for other selections. After a distribution release change, repeat the [matching repository setup](../../repositories/debian.md#banner).

## Troubleshoot

Compare [MQTTSuite package availability](../../../status/mqttsuite.md#banner) with your installed version, then follow [download, signature and dependency troubleshooting](../../troubleshooting.md#banner).
