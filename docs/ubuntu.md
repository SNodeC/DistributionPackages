# Ubuntu

[← All distributions](../README.md#distributions)

[Requirements](#requirements) · [Quick install](#quick-install) · [Choose packages](#choose-packages) · [Configure and run](#configure-and-run) · [Updates](#updates) · [Manual repository setup](#manual-repository-setup) · [Reference](#reference) · [Troubleshooting](#troubleshooting)

## Requirements

Supported releases: `noble`, `resolute`. Match the release and package architecture installed on your device. Keep official repositories enabled for dependencies.

Use an account with `sudo`, or run administrative commands directly as root.
Install `curl` and CA certificates before downloading the installer.

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

```sh
curl -fsSL https://raw.githubusercontent.com/SNodeC/DistributionPackages/main/install/install.sh \
  -o /tmp/snodec-install-feed.sh &&
sudo sh /tmp/snodec-install-feed.sh
```

The installer detects the distribution, release and package architecture, checks
that an index exists, installs the signing key, configures the repository
and installs the complete package set. Configure applications before starting them.
Prefer manual setup? Use [Manual repository setup](#manual-repository-setup).

## Choose packages

Prepare the repository without installing packages:

```sh
curl -fsSL https://raw.githubusercontent.com/SNodeC/DistributionPackages/main/install/install.sh \
  -o /tmp/snodec-install-feed.sh &&
sudo sh /tmp/snodec-install-feed.sh --prepare
```

For only the broker and command-line client:

```sh
sudo apt-get install mqttsuite-broker mqttsuite-cli
```

Dependencies are installed automatically. For the full selection after manual
preparation, install the complete-project packages listed below.

| Package | Contents |
| --- | --- |
| `snodec` | All framework components, headers, examples and configuration tool |
| `snodec-apps` | Demonstration applications |
| `snodec-unspecified` | Component containing `snodec-control` |
| `mqttsuite` | All five applications and both mapping plugins |
| `mqttsuite-broker` | MQTT broker |
| `mqttsuite-cli` | Publish/subscribe command-line client |

See the [DEB/RPM component catalog](linux.md#component-packages) for all common choices.

```sh
sudo apt-get install snodec mqttsuite
```

## Configure and run

Inspect `mqttbroker --help`, `mqttcli --help` and `snodec-control --help`. Configure
listeners, credentials and TLS certificates before starting services. The store
requires a configured database. Consult the [application documentation](https://github.com/SNodeC/mqttsuite#readme)
and [framework documentation](https://github.com/SNodeC/snode.c#readme) for options.

Executables are installed in `/usr/bin`. Administrative configuration lives in
`/etc/snode.c`; non-root processes use their per-user configuration directories.
Installation creates the `snodec` system group but does not start network services.
To start a foreground broker:

```sh
mqttbroker --daemonize=false
```

For persistent operation, configure a systemd service with the desired user and
arguments; these packages do not supply systemd service units.

## Updates

```sh
sudo apt-get update
sudo apt-get install snodec mqttsuite
```

For selective installations, name the installed components rather than adding
the complete metapackages. After a distribution upgrade, configure the repository
for its new supported release and refresh metadata.

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

APT selects packages from the index for your native architecture. Package files
for all architectures share the suite’s `pool/` directory.

Then [choose packages](#choose-packages) to install.

## Reference

<details>
<summary>Supported releases, package architectures and indexes</summary>

### noble

[Package files for this suite](https://github.com/SNodeC/Packages/tree/main/ubuntu/pool/noble). APT selects the native architecture’s index.

| Release | Package architecture | Index | Browse |
| --- | --- | --- | --- |
| noble | `amd64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/ubuntu/dists/noble/main/binary-amd64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/ubuntu/dists/noble/main/binary-amd64) |
| noble | `arm64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/ubuntu/dists/noble/main/binary-arm64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/ubuntu/dists/noble/main/binary-arm64) |

### resolute

[Package files for this suite](https://github.com/SNodeC/Packages/tree/main/ubuntu/pool/resolute). APT selects the native architecture’s index.

| Release | Package architecture | Index | Browse |
| --- | --- | --- | --- |
| resolute | `amd64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/ubuntu/dists/resolute/main/binary-amd64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/ubuntu/dists/resolute/main/binary-amd64) |
| resolute | `arm64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/ubuntu/dists/resolute/main/binary-arm64/Packages.gz) | [Browse](https://github.com/SNodeC/Packages/tree/main/ubuntu/dists/resolute/main/binary-arm64) |

</details>

## Troubleshooting

See [common problems and fixes](troubleshooting.md) for download, signature,
dependency and application errors.

| Symptom | What to check |
| --- | --- |
| Installed suite is not listed | Use a supported Ubuntu suite; do not substitute Debian repositories or another Ubuntu release. |

[Back to top](#ubuntu) · [All distributions](../README.md#distributions) · [Package status](https://github.com/SNodeC/Packages/blob/main/README.md#ubuntu)
