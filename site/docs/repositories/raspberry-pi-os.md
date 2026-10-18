<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->

<!-- snodec:begin page-header -->
<a id="banner"></a><a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="../media/nav/banner-installation-compact.svg"><img src="../media/nav/banner-installation.svg" alt="Packages — Installation" width="100%"></picture></p>
<p><a href="README.md#banner" title="Up to Installation"><picture><source media="(prefers-color-scheme: dark)" srcset="../media/nav/up-installation-dark.svg"><img src="../media/nav/up-installation-light.svg" alt="Up to Installation" title="Up to Installation" width="160" height="28"></picture></a><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/account-dark.svg"><img align="right" src="../media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/organization-dark.svg"><img align="right" src="../media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../../README.md#banner" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/repository-dark.svg"><img align="right" src="../media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# Raspberry Pi OS: signed repository setup

This page configures the package source only. Choose your project in the [Raspberry Pi OS installation overview](../installation/raspberry-pi-os.md#banner).

## Requirements

Supported releases: `bookworm`, `trixie`. Match the release and package architecture installed on your device. Keep official repositories enabled for dependencies.

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

Use **Raspberry Pi 3, 4 or 5 with 64-bit Raspberry Pi OS** (`arm64`). The [official Lite images](https://www.raspberrypi.com/software/operating-systems/) are supported. 32-bit installations are not covered. The installer recognises Raspberry Pi OS through `/etc/rpi-issue`, even when `/etc/os-release` says Debian.

## Configure the repository


Run these commands on the Pi. Keep the official Raspberry Pi OS repositories configured: they supply system dependencies. This repository supplies individual component packages. The `snodec` and `mqttsuite` metapackages install all components of their respective projects.

```sh
(
  set -eu
  . /etc/os-release
  [ -f /etc/rpi-issue ] || { echo "Requires Raspberry Pi OS"; exit 1; }
  suite=${VERSION_CODENAME:-}
  case "$suite" in
    bookworm|trixie) ;;
    *) echo "Unsupported suite"; exit 1 ;;
  esac
  arch=$(dpkg --print-architecture)
  [ "$arch" = arm64 ] || { echo "64-bit Raspberry Pi OS required"; exit 1; }
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl
  tmp=$(mktemp -d /tmp/snodec.XXXXXX)
  trap 'rm -rf "$tmp"' EXIT HUP INT TERM
  base=https://raw.githubusercontent.com/SNodeC/Packages/main
  url="$base/raspberrypios"
  curl -fsSL "$url/dists/$suite/main/binary-$arch/Packages.gz" -o "$tmp/index"
  curl -fsSL "$base/keys/snodec-apt.asc" -o "$tmp/key"
  sudo install -d -m 755 /etc/apt/keyrings /etc/apt/sources.list.d
  sudo install -m 644 "$tmp/key" /etc/apt/keyrings/snodec.asc
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/snodec.asc] %s %s main\n' \
    "$arch" "$url" "$suite" | sudo tee /etc/apt/sources.list.d/snodec.list
  sudo apt-get update
)
```

Verify the [installed signing key](../../keys/README.md#installed-keys) before installing packages.

The repository is ready. Return to the [project choices](../installation/raspberry-pi-os.md#banner) to install the packages you need.

## Source records

In [source records](../../raspberrypios/dists/), `<suite>/build.json` aggregates the suite’s architectures. **Packages** opens the shared package pool, not this record directory.

`build.json` records source tags and commits, package versions, checksums and publication context. On the [project status pages](../../status/README.md#banner), **Build log** opens the recorded build job or release run. See [column semantics](../publication.md#latest-release-available-and-in-build) for missing historical records.

Native package definitions: [SNode.C CPack](https://github.com/SNodeC/snode.c/blob/HEAD/cmake/Packing.cmake) and [MQTTSuite CPack](https://github.com/SNodeC/mqttsuite/blob/HEAD/cmake/Packing.cmake).

## Troubleshooting

See [common problems and fixes](../troubleshooting.md#banner) for download, signature, dependency and application errors.

| Symptom | What to check |
| --- | --- |
| Installer identifies the Pi as Debian | Check `/etc/rpi-issue`; the installer uses it to identify Raspberry Pi OS. Use the Pi repository only on Raspberry Pi OS. |
| Architecture is `armhf` | This repository supports 64-bit Raspberry Pi OS (`arm64`) only. |
