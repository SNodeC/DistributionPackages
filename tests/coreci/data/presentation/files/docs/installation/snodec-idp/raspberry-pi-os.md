<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->

<!-- snodec:begin page-header -->
<a id="banner"></a><a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="../../media/nav/banner-installation-compact.svg"><img src="../../media/nav/banner-installation.svg" alt="Packages — Installation" width="100%"></picture></p>
<p><a href="README.md#banner" title="Up to Installation"><picture><source media="(prefers-color-scheme: dark)" srcset="../../media/nav/up-installation-dark.svg"><img src="../../media/nav/up-installation-light.svg" alt="Up to Installation" title="Up to Installation" width="160" height="28"></picture></a><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../../media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="../../media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../../media/nav/account-dark.svg"><img align="right" src="../../media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../../media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="../../media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../../media/nav/organization-dark.svg"><img align="right" src="../../media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../../../README.md#banner" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../../media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="../../media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../../media/nav/repository-dark.svg"><img align="right" src="../../media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# SNode.C IDP on Raspberry Pi OS

[Requirements](#requirements) · [Quick install](#quick-install) · [Components](#components) · [Verify](#verify) · [Configure](#configure) · [Update](#update)

## Requirements

Supported releases: `bookworm`, `trixie`. Match the release and package architecture installed on your device. Keep official repositories enabled for dependencies.

Read [Raspberry Pi OS prerequisites](../../repositories/raspberry-pi-os.md#banner), including platform and repository requirements, before running the installer. Check [SNode.C IDP availability](../../../status/snodec-idp.md#banner) for your release and architecture; a supported target may still be building.

## Quick install

Install standalone identity provider. The installer prepares the signed repository and installs only this selection and its dependencies. It does not configure or start the application.

```sh
(
  set -eu
  tmp=$(mktemp -d /tmp/snodec.XXXXXX)
  trap 'rm -rf "$tmp"' EXIT HUP INT TERM
  base=https://raw.githubusercontent.com/SNodeC/Packages/main/install
  for script in install.sh snodec-idp.sh; do
    curl -fsSL "$base/$script" -o "$tmp/$script"
  done
  sudo sh "$tmp/snodec-idp.sh" --component server
)
```

For repository preparation only, use the shared `install.sh --prepare`; see [repository setup](../../repositories/raspberry-pi-os.md#banner).

## Components

Choose the roles you need. These package-manager commands assume repository setup is complete. Repeat `--component NAME` on the project installer to select the same roles.

### Standalone identity provider

Installer option: `--component server`.

```sh
sudo apt-get install snodec-idp
```

### Application authentication development

Installer option: `--component client-dev`.

```sh
sudo apt-get install snodec-idp-client-dev
```

### Embedded identity-provider development

Installer option: `--component server-dev`.

```sh
sudo apt-get install snodec-idp-server-dev
```

### Optional browser example

Installer option: `--component example`.

```sh
sudo apt-get install snodec-idp-example
```

See the [SNode.C IDP package catalog](../../catalogs/snodec-idp.md#banner) for package responsibilities and dependencies. Installing a component does not select the complete project metapackage.

## Verify

For the quick-install selection above:

```sh
dpkg-query -W -f='${Package} ${Version} ${Status}\n' snodec-idp
```

Every requested package must be installed. Substitute your chosen package names if you selected different components.

## Configure

The server does not start automatically. Follow the [IDP deployment guide](https://github.com/SNodeC/snode.c-idp/blob/main/docs/package-deployment.md#banner) for configuration, keys and HTTPS. Client and embedded-provider development have different roles; see the [IDP catalog](../../catalogs/snodec-idp.md#banner).

## Update

Update the packages you selected. For the quick-install selection:

```sh
sudo apt-get update
sudo apt-get install --only-upgrade snodec-idp
```

Use your installed component names for other selections. After a distribution release change, repeat the [matching repository setup](../../repositories/raspberry-pi-os.md#banner).

## Troubleshoot

Compare [SNode.C IDP package availability](../../../status/snodec-idp.md#banner) with your installed version, then follow [download, signature and dependency troubleshooting](../../troubleshooting.md#banner).
