# Raspberry Pi OS

<p>
  <a href="../README.md#distributions"><img src="media/menu/back-all-distributions.svg" alt="← All distributions" width="140" height="24"></a>
</p>

<p align="center">
  <a href="#requirements" title="Requirements"><img src="media/menu/requirements-102.svg" alt="Requirements" width="102" height="24"></a>
  <a href="#quick-install" title="Quick install"><img src="media/menu/install-102.svg" alt="Quick install" width="102" height="24"></a>
  <a href="#choose-packages" title="Choose packages"><img src="media/menu/packages-102.svg" alt="Choose packages" width="102" height="24"></a>
  <a href="#configure-and-run" title="Configure and run"><img src="media/menu/configure-102.svg" alt="Configure and run" width="102" height="24"></a>
  <a href="#updates" title="Updates"><img src="media/menu/updates-102.svg" alt="Updates" width="102" height="24"></a>
  <a href="#manual-repository-setup" title="Manual repository setup"><img src="media/menu/manual-setup-102.svg" alt="Manual repository setup" width="102" height="24"></a>
  <a href="#reference" title="Reference"><img src="media/menu/reference-102.svg" alt="Reference" width="102" height="24"></a>
  <a href="#troubleshooting" title="Troubleshooting"><img src="media/menu/help-102.svg" alt="Troubleshooting" width="102" height="24"></a>
</p>

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

## Quick install

```sh
curl -fsSL https://raw.githubusercontent.com/SNodeC/Packages/main/install/install.sh \
  -o /tmp/snodec-install-feed.sh &&
sudo sh /tmp/snodec-install-feed.sh
```

The installer detects the distribution, release and package architecture, checks that an index exists, installs the signing key, configures the repository and installs the complete package set. Configure applications before starting them. Prefer manual setup? Use [Manual repository setup](#manual-repository-setup).

## Choose packages

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

Dependencies are installed automatically. For the full selection after manual preparation, install the complete-project packages listed below.

| Package | Contents |
| --- | --- |
| `snodec` | All framework components, headers, examples and configuration tool |
| `snodec-apps` | Demonstration applications |
| `snodec-control` | Component containing `snodec-control` |
| `mqttsuite` | All five applications and both mapping plugins |
| `mqttsuite-broker` | MQTT broker |
| `mqttsuite-cli` | Publish/subscribe command-line client |

See the complete [SNode.C](snodec-package-options.md) and [MQTTSuite](mqttsuite-package-options.md) package catalogs.

```sh
sudo apt-get install snodec mqttsuite
```

## Configure and run

Inspect `mqttbroker --help`, `mqttcli --help` and `snodec-control --help`. Configure listeners, credentials and TLS certificates before starting services. The store requires a configured database. Consult the [application documentation](https://github.com/SNodeC/mqttsuite#project-overview) and [framework documentation](https://github.com/SNodeC/snode.c#project-overview) for options.

Executables are installed in `/usr/bin`. Administrative configuration lives in `/etc/snode.c`; non-root processes use their per-user configuration directories. Installation creates the `snodec` system group but does not start network services. To start a foreground broker:

```sh
mqttbroker --daemonize=false
```

For persistent operation, configure a systemd service with the desired user and arguments; these packages do not supply systemd service units.

## Updates

```sh
sudo apt-get update
sudo apt-get install snodec mqttsuite
```

For selective installations, name the installed components rather than adding the complete metapackages. After a distribution upgrade, configure the repository for its new supported release and refresh metadata.

Installing the metapackages also upgrades older combined packages to component packages. `apt-get upgrade` alone can hold back that transition when new dependencies are needed. Component packages declare replacement of old files.

## Manual repository setup

Run these commands on the Pi. Keep the official Raspberry Pi OS repositories configured: they supply system dependencies. This repository supplies individual component packages. The `snodec` and `mqttsuite` metapackages install all components of their respective projects.

```sh
. /etc/os-release
case "$VERSION_CODENAME" in bookworm|trixie) ;; *) echo 'Unsupported OS release'; exit 1;; esac
[ "$(dpkg --print-architecture)" = arm64 ] || { echo '64-bit Raspberry Pi OS required'; exit 1; }
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -d -m 755 /etc/apt/keyrings
curl -fsSL https://raw.githubusercontent.com/SNodeC/Packages/main/keys/snodec-apt.asc |
    sudo tee /etc/apt/keyrings/snodec.asc >/dev/null
sudo chmod 644 /etc/apt/keyrings/snodec.asc
printf 'deb [arch=arm64 signed-by=/etc/apt/keyrings/snodec.asc] https://raw.githubusercontent.com/SNodeC/Packages/main/raspberrypios %s main\n' "$VERSION_CODENAME" |
    sudo tee /etc/apt/sources.list.d/snodec.list
sudo apt-get update
```

Then [choose packages](#choose-packages) to install.

## Reference

<details>
<summary>Supported releases, package architectures and indexes</summary>

### bookworm

[Package files for this suite](https://github.com/SNodeC/Packages/tree/main/raspberrypios/pool/bookworm). APT selects the native architecture’s index.

| Release | Package architecture | Index | Browse |
| --- | --- | --- | --- |
| bookworm | `arm64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/raspberrypios/dists/bookworm/main/binary-arm64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/raspberrypios/dists/bookworm/main/binary-arm64) |

### trixie

[Package files for this suite](https://github.com/SNodeC/Packages/tree/main/raspberrypios/pool/trixie). APT selects the native architecture’s index.

| Release | Package architecture | Index | Browse |
| --- | --- | --- | --- |
| trixie | `arm64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/raspberrypios/dists/trixie/main/binary-arm64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/raspberrypios/dists/trixie/main/binary-arm64) |

</details>

## Troubleshooting

See [common problems and fixes](troubleshooting.md) for download, signature, dependency and application errors.

| Symptom | What to check |
| --- | --- |
| Installer identifies the Pi as Debian | Check `/etc/rpi-issue`; the installer uses it to identify Raspberry Pi OS. Use the Pi repository only on Raspberry Pi OS. |
| Architecture is `armhf` | This repository supports 64-bit Raspberry Pi OS (`arm64`) only. |

<p align="center">
  <a href="#raspberry-pi-os" title="Back to top"><img src="media/menu/back-to-top-124.svg" alt="Back to top" width="124" height="24"></a>
  <a href="../README.md#distributions" title="All distributions"><img src="media/menu/all-distributions-124.svg" alt="All distributions" width="124" height="24"></a>
  <a href="https://github.com/SNodeC/Packages/blob/main/docs/status.md#raspberry-pi-os" title="Package status"><img src="media/menu/package-status-124.svg" alt="Package status" width="124" height="24"></a>
</p>
