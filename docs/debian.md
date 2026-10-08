# Debian

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

Supported releases: `trixie`, `forky`, `sid`. Match the release and package architecture installed on your device. Keep official repositories enabled for dependencies.

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

The matrix covers Trixie (stable), Forky (testing) and Sid (unstable). Use the installed suite’s name, not a moving `stable` or `testing` alias. For Sid, append `--suite sid` to the installer command; `/etc/os-release` may report a testing codename. Use `--suite forky` if Forky is not detected. This selects a repository; it does not upgrade the operating system.

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

## Manual repository setup

These commands configure the signed repository without installing SNode.C or MQTTSuite.

Select your suite below (`trixie` is the example), then run the block:

```sh
(
  set -eu
  suite=trixie
  case "$suite" in trixie|forky|sid) ;; *) echo "Unsupported suite"; exit 1;; esac
  arch=$(dpkg --print-architecture)
  case "$arch" in amd64|arm64|armhf|riscv64) ;; *) echo "Unsupported architecture"; exit 1;; esac
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl
  sudo install -d -m 755 /etc/apt/keyrings
  curl -fsSL https://raw.githubusercontent.com/SNodeC/Packages/main/keys/snodec-apt.asc |
    sudo tee /etc/apt/keyrings/snodec.asc >/dev/null
  sudo chmod 644 /etc/apt/keyrings/snodec.asc
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/snodec.asc] https://raw.githubusercontent.com/SNodeC/Packages/main/debian %s main\n' "$arch" "$suite" |
    sudo tee /etc/apt/sources.list.d/snodec.list
  sudo apt-get update
)
```

APT selects packages from the index for your native architecture. Package files for all architectures share the suite’s `pool/` directory.

Then [choose packages](#choose-packages) to install.

## Reference

<details>
<summary>Supported releases, package architectures and indexes</summary>

### trixie

[Package files for this suite](https://github.com/SNodeC/Packages/tree/main/debian/pool/trixie). APT selects the native architecture’s index.

| Release | Package architecture | Index | Browse |
| --- | --- | --- | --- |
| trixie | `amd64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/debian/dists/trixie/main/binary-amd64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/debian/dists/trixie/main/binary-amd64) |
| trixie | `arm64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/debian/dists/trixie/main/binary-arm64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/debian/dists/trixie/main/binary-arm64) |
| trixie | `armhf` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/debian/dists/trixie/main/binary-armhf/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/debian/dists/trixie/main/binary-armhf) |
| trixie | `riscv64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/debian/dists/trixie/main/binary-riscv64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/debian/dists/trixie/main/binary-riscv64) |

### forky

[Package files for this suite](https://github.com/SNodeC/Packages/tree/main/debian/pool/forky). APT selects the native architecture’s index.

| Release | Package architecture | Index | Browse |
| --- | --- | --- | --- |
| forky | `amd64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/debian/dists/forky/main/binary-amd64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/debian/dists/forky/main/binary-amd64) |
| forky | `arm64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/debian/dists/forky/main/binary-arm64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/debian/dists/forky/main/binary-arm64) |
| forky | `armhf` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/debian/dists/forky/main/binary-armhf/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/debian/dists/forky/main/binary-armhf) |
| forky | `riscv64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/debian/dists/forky/main/binary-riscv64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/debian/dists/forky/main/binary-riscv64) |

### sid

[Package files for this suite](https://github.com/SNodeC/Packages/tree/main/debian/pool/sid). APT selects the native architecture’s index.

| Release | Package architecture | Index | Browse |
| --- | --- | --- | --- |
| sid | `amd64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/debian/dists/sid/main/binary-amd64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/debian/dists/sid/main/binary-amd64) |
| sid | `arm64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/debian/dists/sid/main/binary-arm64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/debian/dists/sid/main/binary-arm64) |
| sid | `armhf` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/debian/dists/sid/main/binary-armhf/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/debian/dists/sid/main/binary-armhf) |
| sid | `riscv64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/debian/dists/sid/main/binary-riscv64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/debian/dists/sid/main/binary-riscv64) |

</details>

## Troubleshooting

See [common problems and fixes](troubleshooting.md) for download, signature, dependency and application errors.

| Symptom | What to check |
| --- | --- |
| Sid selects a testing suite | Pass `--suite sid` to the installer on an installed Sid system. |

<p align="center">
  <a href="#debian" title="Back to top"><img src="media/menu/back-to-top-124.svg" alt="Back to top" width="124" height="24"></a>
  <a href="../README.md#distributions" title="All distributions"><img src="media/menu/all-distributions-124.svg" alt="All distributions" width="124" height="24"></a>
  <a href="https://github.com/SNodeC/Packages/blob/main/docs/status.md#debian" title="Package status"><img src="media/menu/package-status-124.svg" alt="Package status" width="124" height="24"></a>
</p>
