<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->
<a id="page-overview"></a>

[![Packages](media/page-banner.svg)](../README.md#project-overview)

# Ubuntu

<p>
<a href="#requirements"><img src="media/menu/requirements.svg" alt="Requirements"></a>
<a href="#choose-packages"><img src="media/menu/choose-packages.svg" alt="Choose packages"></a>
<a href="#quick-install"><img src="media/menu/install.svg" alt="Install"></a>
<a href="#manual-repository-setup"><img src="media/menu/manual.svg" alt="Manual setup"></a>
<a href="#updates"><img src="media/menu/updates.svg" alt="Updates"></a>
<a href="../status/README.md#page-overview"><img src="media/menu/status.svg" alt="Status"></a>
<a href="#troubleshooting"><img src="media/menu/troubleshoot.svg" alt="Troubleshoot"></a>
</p>

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

## Choose packages

See the [SNode.C catalog](snodec-package-options.md#page-overview) and [MQTTSuite catalog](mqttsuite-package-options.md#page-overview) for package roles and after-install configuration.

<a href="#complete-sets"><img src="media/menu/complete-sets.svg" alt="Complete sets" align="absmiddle"></a> Install all components of the currently offered projects.

<a href="#selected-packages"><img src="media/menu/selected-packages.svg" alt="Selected packages" align="absmiddle"></a> Configure the signed source, then install only the components you need.

## Quick install

### Complete sets

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

The requested packages show versions and `install ok installed`. Missing or incomplete entries are not a successful installation. Next: [SNode.C configuration](snodec-package-options.md#after-installation) or [MQTTSuite configuration and deployment](mqttsuite-package-options.md#after-installation).

### Selected packages

Prepare the repository without installing packages:

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

The requested packages show versions and `install ok installed`. Missing or incomplete entries are not a successful installation. Next: [SNode.C configuration](snodec-package-options.md#after-installation) or [MQTTSuite configuration and deployment](mqttsuite-package-options.md#after-installation).

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

Verify the [installed signing key](../keys/README.md#installed-keys) before installing packages.

Install the complete sets after manual setup:

```sh
sudo apt-get install snodec mqttsuite
```

**Check**

```sh
dpkg-query -W -f='${Package} ${Version} ${Status}\n' snodec mqttsuite
```

The requested packages show versions and `install ok installed`. Missing or incomplete entries are not a successful installation. Next: [SNode.C configuration](snodec-package-options.md#after-installation) or [MQTTSuite configuration and deployment](mqttsuite-package-options.md#after-installation).

<a href="#install-selected-components"><img src="media/menu/selected-packages.svg" alt="Selected packages" align="absmiddle"></a> The repository is ready; name only the components you need.

## Updates

```sh
sudo apt-get update
sudo apt-get install snodec mqttsuite
```

For selective installations, name the installed components rather than adding the complete metapackages. After a distribution upgrade, configure the repository for its new supported release and refresh metadata.

When moving from older combined packages to component packages, explicitly install the metapackages (or the components you need): `apt-get upgrade` does not install new dependencies. Published MQTTSuite component metadata declares versioned Breaks/Replaces against older combined packages.

## Source records

In [source records](../ubuntu/dists/), `<suite>/build.json` aggregates the suite’s architectures. **Packages** opens the shared package pool, not this record directory.

`build.json` records source tags and commits, package versions, checksums and publication context. On the [project status pages](../status/README.md#page-overview), **Build log** opens the recorded build job or release run. See [column semantics](architecture.md#latest-release-available-and-in-build) for missing historical records.

Native package definitions: [SNode.C CPack](https://github.com/SNodeC/snode.c/blob/HEAD/cmake/Packing.cmake) and [MQTTSuite CPack](https://github.com/SNodeC/mqttsuite/blob/HEAD/cmake/Packing.cmake).

## Troubleshooting

See [common problems and fixes](troubleshooting.md#page-overview) for download, signature, dependency and application errors.

| Symptom | What to check |
| --- | --- |
| Installed suite is not listed | Use a supported Ubuntu suite; do not substitute Debian repositories or another Ubuntu release. |
