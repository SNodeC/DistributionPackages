<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->
<a id="page-overview"></a>

[![Packages](media/page-banner.svg)](../README.md#project-overview)

# Troubleshooting

## Common problems

| Symptom | What to check |
| --- | --- |
| Feed or repository returns 404 | Match the distribution, release and package architecture to the [distribution guide](../README.md#install). Use **Files** links on project status pages for directories; raw URLs serve individual files, not directory listings. |
| Signature verification fails | Check the system clock, repository URL and installed [signing key](../README.md#signing-keys). Keep signature verification enabled. |
| Dependencies cannot be installed | Keep the official repositories enabled for the installed release. Do not mix distributions, releases or package architectures. Check the guide for additional dependency repositories. |
| Download fails just after publication | Refresh package indexes and retry after GitHub's raw-content caches update. |
| A newer package is unavailable | Check the target's version and badge on [Package status](../status/README.md#page-overview). A successful compilation alone does not mean publication succeeded. |
| The latest rebuild failed | The previous published packages remain available. Check the status badge for the failing job. |
| An application does not start | Inspect its `--help` output, configuration and logs. Verify installation completed and configure listeners, credentials, certificates and any required database before starting it. |
| A package cannot be downloaded from a browser | Open **Files** on the project status page to find its filename. Package managers use signed repository indexes, not GitHub directory views. |

## Distribution-specific help

- [OpenWrt](openwrt.md#troubleshooting)
- [Raspberry Pi OS](raspberrypi.md#troubleshooting)
- [Debian](debian.md#troubleshooting)
- [Ubuntu](ubuntu.md#troubleshooting)
- [Rocky Linux](rocky.md#troubleshooting)
- [Fedora](fedora.md#troubleshooting)

If the problem remains, [open an issue](https://github.com/SNodeC/Packages/issues). Include the distribution, release, package architecture, package name and error message. Remove passwords and other credentials from logs.

## Terms

- **Feed:** an OpenWrt package source with signed indexes.
- **Repository:** a package source used by APT or DNF.
- **Release:** the installed distribution release. APT calls its repository selection a **suite**, such as `trixie` or `sid`.
- **Package architecture:** the name reported by the package manager; it may differ from a board or CPU name.
- **Metapackage:** a package that selects a group of component packages through dependencies.
- **Index:** the file the package manager reads to find packages and verify their metadata.
- **Browse:** a GitHub directory view for people; it is not an index URL.
