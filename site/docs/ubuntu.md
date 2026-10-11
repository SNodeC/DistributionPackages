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

[![Complete sets](media/menu/complete-sets.svg)](#complete-sets) Install all components of the currently offered projects.

[![Selected packages](media/menu/selected-packages.svg)](#selected-packages) Configure the signed source, then install only the components you need.

## Quick install

### Complete sets

```sh
curl -fsSL https://raw.githubusercontent.com/SNodeC/Packages/main/install/install.sh \
  -o /tmp/snodec-install-feed.sh &&
sudo sh /tmp/snodec-install-feed.sh
```

The installer detects the distribution, release and package architecture, checks that an index exists, installs the signing key, configures the repository and installs the complete package set. Configure applications before starting them. For manual configuration, use the setup section below.

### Selected packages

Prepare the repository without installing packages:

```sh
curl -fsSL https://raw.githubusercontent.com/SNodeC/Packages/main/install/install.sh \
  -o /tmp/snodec-install-feed.sh &&
sudo sh /tmp/snodec-install-feed.sh --prepare
```

For only the broker and command-line client:

```sh
sudo apt-get install mqttsuite-broker mqttsuite-cli
```

Dependencies are installed automatically.

## Manual repository setup

These commands configure the signed repository without installing SNode.C or MQTTSuite.

Select your suite below (`noble` is the example), then run the block:

```sh
(
  set -eu
  suite=noble
  case "$suite" in noble|resolute) ;; *) echo "Unsupported suite"; exit 1;; esac
  arch=$(dpkg --print-architecture)
  case "$arch" in amd64|arm64) ;; *) echo "Unsupported architecture"; exit 1;; esac
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl
  sudo install -d -m 755 /etc/apt/keyrings
  curl -fsSL https://raw.githubusercontent.com/SNodeC/Packages/main/keys/snodec-apt.asc |
    sudo tee /etc/apt/keyrings/snodec.asc >/dev/null
  sudo chmod 644 /etc/apt/keyrings/snodec.asc
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/snodec.asc] https://raw.githubusercontent.com/SNodeC/Packages/main/ubuntu %s main\n' "$arch" "$suite" |
    sudo tee /etc/apt/sources.list.d/snodec.list
  sudo apt-get update
)
```

APT selects packages from the index for your native architecture. Package files for all architectures share the suite’s `pool/` directory.

Install the complete sets after manual setup:

```sh
sudo apt-get install snodec mqttsuite
```

[![Selected packages](media/menu/selected-packages.svg)](#selected-packages) Install individual components after manual setup.

## Updates

```sh
sudo apt-get update
sudo apt-get install snodec mqttsuite
```

For selective installations, name the installed components rather than adding the complete metapackages. After a distribution upgrade, configure the repository for its new supported release and refresh metadata.

## Source records

See [per-project availability and source records](../status/README.md#page-overview) for every release and architecture.

## Troubleshooting

See [common problems and fixes](troubleshooting.md#page-overview) for download, signature, dependency and application errors.

| Symptom | What to check |
| --- | --- |
| Installed suite is not listed | Use a supported Ubuntu suite; do not substitute Debian repositories or another Ubuntu release. |
