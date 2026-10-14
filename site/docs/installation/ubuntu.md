<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->

<!-- snodec:begin page-header -->
<a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="../media/nav/banner-installation-compact.svg"><img src="../media/nav/banner-installation.svg" alt="Packages — Installation" width="100%"></picture></p>
<p><a href="README.md#page-overview" title="Up to Installation"><picture><source media="(prefers-color-scheme: dark)" srcset="../media/nav/up-installation-dark.svg"><img src="../media/nav/up-installation-light.svg" alt="Up to Installation" title="Up to Installation" width="160" height="28"></picture></a><a href="https://github.com/SNodeC" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/organization-dark.svg"><img align="right" src="../media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../../README.md#project-overview" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/repository-dark.svg"><img align="right" src="../media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# Ubuntu

<!-- snodec:begin menu -->
<p>
<a href="#requirements"><img src="../media/menu/requirements.svg" alt="Requirements"></a>
<a href="#quick-install"><img src="../media/menu/menu-quick-install.svg" alt="Quick install"></a>
<a href="#choose-packages"><img src="../media/menu/menu-custom-install.svg" alt="Custom install"></a>
<a href="#manual-repository-setup"><img src="../media/menu/manual.svg" alt="Manual setup"></a>
<a href="#updates"><img src="../media/menu/updates.svg" alt="Updates"></a>
<a href="../../status/README.md#page-overview"><img src="../media/menu/status.svg" alt="Status"></a>
<a href="#troubleshooting"><img src="../media/menu/troubleshoot.svg" alt="Troubleshoot"></a>
</p>
<!-- snodec:end menu -->

## Requirements

Supported releases: `noble`, `resolute`. Match the release and package architecture installed on your device. Keep official repositories enabled for dependencies.

Use an account with `sudo`, or run administrative commands directly as root. Install `curl` and CA certificates before downloading the installer.

```sh
. /etc/os-release
printf 'Distribution: %s\nRelease: %s\n' "$ID" "$VERSION_ID"
dpkg --print-architecture
```

```sh
sudo apt-get update
sudo apt-get install ca-certificates curl
```

Noble is Ubuntu 24.04 LTS; Resolute is Ubuntu 26.04 LTS.

## Quick install

Install the complete package sets:

```sh
(
  set -eu
  tmp=$(mktemp -d /tmp/snodec.XXXXXX)
  trap 'rm -rf "$tmp"' EXIT HUP INT TERM
  base=https://raw.githubusercontent.com/SNodeC/Packages/main
  curl -fsSL "$base/install/install.sh" -o "$tmp/install.sh"
  sudo sh "$tmp/install.sh"
)
```

The installer detects the distribution, release and package architecture, checks that an index exists, installs the signing key, configures the repository and installs the complete package set. Configure applications before starting them. For manual configuration, use [Manual repository setup](#manual-repository-setup).

**Check**

```sh
dpkg-query -W -f='${Package} ${Version} ${Status}\n' snodec mqttsuite
```

The requested packages show versions and `install ok installed`. Missing or incomplete entries are not a successful installation. Next: [SNode.C configuration](../catalogs/snodec.md#after-installation) or [MQTTSuite configuration and deployment](../catalogs/mqttsuite.md#after-installation).

<a id="choose-packages"></a>

## Custom install

Prepare the repository without installing packages, then install only what you need:

```sh
(
  set -eu
  tmp=$(mktemp -d /tmp/snodec.XXXXXX)
  trap 'rm -rf "$tmp"' EXIT HUP INT TERM
  base=https://raw.githubusercontent.com/SNodeC/Packages/main
  curl -fsSL "$base/install/install.sh" -o "$tmp/install.sh"
  sudo sh "$tmp/install.sh" --prepare
)
```

For only the broker and command-line client:

<a id="install-selected-components"></a>

```sh
sudo apt-get install mqttsuite-broker mqttsuite-cli
```

Dependencies are installed automatically.

**Check**

```sh
dpkg-query -W -f='${Package} ${Version} ${Status}\n' mqttsuite-broker mqttsuite-cli
```

The requested packages show versions and `install ok installed`. Missing or incomplete entries are not a successful installation. Next: [SNode.C configuration](../catalogs/snodec.md#after-installation) or [MQTTSuite configuration and deployment](../catalogs/mqttsuite.md#after-installation).

See the [SNode.C catalog](../catalogs/snodec.md#page-overview) and [MQTTSuite catalog](../catalogs/mqttsuite.md#page-overview) for package roles and after-install configuration.

## Manual repository setup

These commands configure the signed repository without installing SNode.C or MQTTSuite.

Select your suite below (`noble` is the example), then run the block:

```sh
(
  set -eu
  . /etc/os-release
  [ "$ID" = ubuntu ] || { echo "Requires ubuntu"; exit 1; }
  suite=noble
  case "$suite" in
    noble|resolute) ;;
    *) echo "Unsupported suite"; exit 1 ;;
  esac
  arch=$(dpkg --print-architecture)
  case "$arch" in
    amd64|arm64) ;;
    *) echo "Unsupported architecture"; exit 1 ;;
  esac
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl
  tmp=$(mktemp -d /tmp/snodec.XXXXXX)
  trap 'rm -rf "$tmp"' EXIT HUP INT TERM
  base=https://raw.githubusercontent.com/SNodeC/Packages/main
  url="$base/ubuntu"
  curl -fsSL "$url/dists/$suite/main/binary-$arch/Packages.gz" -o "$tmp/index"
  curl -fsSL "$base/keys/snodec-apt.asc" -o "$tmp/key"
  sudo install -d -m 755 /etc/apt/keyrings /etc/apt/sources.list.d
  sudo install -m 644 "$tmp/key" /etc/apt/keyrings/snodec.asc
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/snodec.asc] %s %s main\n' \
    "$arch" "$url" "$suite" | sudo tee /etc/apt/sources.list.d/snodec.list
  sudo apt-get update
)
```

APT selects packages from the index for your native architecture. Package files for all architectures share the suite’s `pool/` directory.

Verify the [installed signing key](../../keys/README.md#installed-keys) before installing packages.

Install the complete sets after manual setup:

```sh
sudo apt-get install snodec mqttsuite
```

**Check**

```sh
dpkg-query -W -f='${Package} ${Version} ${Status}\n' snodec mqttsuite
```

The requested packages show versions and `install ok installed`. Missing or incomplete entries are not a successful installation. Next: [SNode.C configuration](../catalogs/snodec.md#after-installation) or [MQTTSuite configuration and deployment](../catalogs/mqttsuite.md#after-installation).

The repository is ready; [install only the selected components](#install-selected-components) you need.

## Updates

```sh
sudo apt-get update
sudo apt-get install snodec mqttsuite
```

For selective installations, name the installed components rather than adding the complete metapackages. After a distribution upgrade, configure the repository for its new supported release and refresh metadata.

When moving from older combined packages to component packages, explicitly install the metapackages (or the components you need): `apt-get upgrade` does not install new dependencies. Published MQTTSuite component metadata declares versioned Breaks/Replaces against older combined packages.

## Source records

In [source records](../../ubuntu/dists/), `<suite>/build.json` aggregates the suite’s architectures. **Packages** opens the shared package pool, not this record directory.

`build.json` records source tags and commits, package versions, checksums and publication context. On the [project status pages](../../status/README.md#page-overview), **Build log** opens the recorded build job or release run. See [column semantics](../publication.md#latest-release-available-and-in-build) for missing historical records.

Native package definitions: [SNode.C CPack](https://github.com/SNodeC/snode.c/blob/HEAD/cmake/Packing.cmake) and [MQTTSuite CPack](https://github.com/SNodeC/mqttsuite/blob/HEAD/cmake/Packing.cmake).

## Troubleshooting

See [common problems and fixes](../troubleshooting.md#page-overview) for download, signature, dependency and application errors.

| Symptom | What to check |
| --- | --- |
| Installed suite is not listed | Use a supported Ubuntu suite; do not substitute Debian repositories or another Ubuntu release. |
