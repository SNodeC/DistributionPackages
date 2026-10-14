<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->

<!-- snodec:begin page-header -->
<a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="media/nav/banner-documentation-compact.svg"><img src="media/nav/banner-documentation.svg" alt="Packages — Documentation" width="100%"></picture></p>
<p><a href="README.md#page-overview" title="Up to Documentation"><picture><source media="(prefers-color-scheme: dark)" srcset="media/nav/up-documentation-dark.svg"><img src="media/nav/up-documentation-light.svg" alt="Up to Documentation" title="Up to Documentation" width="160" height="28"></picture></a><a href="https://github.com/SNodeC" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/organization-dark.svg"><img align="right" src="media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../README.md#project-overview" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/repository-dark.svg"><img align="right" src="media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# Troubleshooting

<!-- snodec:begin menu -->
[![Install](media/menu/install.svg)](../README.md#install) [![Status](media/menu/status.svg)](../status/README.md#page-overview) [![Terms](media/menu/terms.svg)](#terms)
<!-- snodec:end menu -->

## Common problems

| Symptom | What to check |
| --- | --- |
| Feed or repository returns 404 | Match the distribution, release and package architecture to the [distribution guide](../README.md#install). Use **Packages** links on project status pages for directories; raw URLs serve individual files, not directory listings. |
| Signature verification fails | Check the system clock, repository URL and installed [signing key](../keys/README.md#verify-identity). Keep signature verification enabled. |
| Dependencies cannot be installed | Keep the official repositories enabled for the installed release. Do not mix distributions, releases or package architectures. Check the guide for additional dependency repositories. |
| Download fails just after publication | Refresh package indexes and retry after GitHub's raw-content caches update. |
| A newer package is unavailable | Compare **Available** with **In build** on [Package status](../status/README.md#page-overview). A successful compilation alone does not mean publication succeeded. |
| The latest rebuild failed | The previous published packages remain available. Check **In build** and open **Build log** for the replacement attempt. A published replacement shows `—` in In build. |
| An application does not start | Inspect its `--help` output, configuration and logs. Verify installation completed and configure listeners, credentials, certificates and any required database before starting it. |
| A package cannot be downloaded from a browser | Open **Packages** on the project status page to find its filename. Package managers use signed repository indexes, not GitHub directory views. |

## Distribution-specific help

- [OpenWrt troubleshooting](installation/openwrt.md#troubleshooting)
- [Raspberry Pi OS troubleshooting](installation/raspberry-pi-os.md#troubleshooting)
- [Debian troubleshooting](installation/debian.md#troubleshooting)
- [Ubuntu troubleshooting](installation/ubuntu.md#troubleshooting)
- [Rocky Linux troubleshooting](installation/rocky-linux.md#troubleshooting)
- [Fedora troubleshooting](installation/fedora.md#troubleshooting)

If the guides do not resolve the problem, [report an issue](https://github.com/SNodeC/Packages/issues).

If the problem remains, include the distribution, release, package architecture, package name and error message. Remove passwords and other credentials from logs.

## Terms

- **Feed:** an OpenWrt package source with signed indexes.
- **Repository:** a package source used by APT or DNF.
- **Release:** the installed distribution release. APT calls its repository selection a **suite**, such as `trixie` or `sid`.
- **Package architecture:** the name reported by the package manager; it may differ from a board or CPU name.
- **Metapackage:** a package that selects a group of component packages through dependencies.
- **Index:** the file the package manager reads to find packages and verify their metadata.
