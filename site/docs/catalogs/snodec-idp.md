<!-- snodec:begin page-header -->
<a id="banner"></a><a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="../media/nav/banner-catalogs-compact.svg"><img src="../media/nav/banner-catalogs.svg" alt="Packages — Catalogs" width="100%"></picture></p>
<p><a href="README.md#banner" title="Up to Catalogs"><picture><source media="(prefers-color-scheme: dark)" srcset="../media/nav/up-catalogs-dark.svg"><img src="../media/nav/up-catalogs-light.svg" alt="Up to Catalogs" title="Up to Catalogs" width="160" height="28"></picture></a><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/account-dark.svg"><img align="right" src="../media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/organization-dark.svg"><img align="right" src="../media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../../README.md#banner" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/repository-dark.svg"><img align="right" src="../media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# SNode.C IDP packages

SNode.C IDP provides password and Google sign-in, TOTP MFA, OAuth authorization-code/PKCE flows, and reusable authentication middleware for SNode.C applications. The maintained implementation originates from Jan Eberwein’s identity provider.

| Package | Purpose |
| --- | --- |
| `snodec-idp` | Standalone IDP and explicit HTTPS deployment helper |
| `snodec-idp-client-dev` | Application-side authentication library and headers |
| `snodec-idp-server-dev` | Embeddable IDP middleware library |
| `snodec-idp-example` | Optional styled browser application |

Packages are selected independently. Installing the server does not start it, create certificates or erase existing accounts. Deployment is a separate operator action, with Nginx/Certbot for HTTPS and persistent signing/TOTP keys.

See [current package availability](../../status/snodec-idp.md#banner) before installing. IDP builds target native Linux and Raspberry Pi OS; no IDP OpenWrt package is defined. A catalog entry alone does not establish that a release has been published.

Configure the signed package repository using the [installation guide](../installation/README.md#banner), then install `snodec-idp` and optionally `snodec-idp-example` through APT or DNF. Development consumers use `find_package(snodec-auth 2 REQUIRED)` and link `snodec-auth::auth-client`.

Follow the source repository’s [package deployment guide](https://github.com/SNodeC/snode.c-idp/blob/main/docs/package-deployment.md#banner) for configuration, Google credentials, mail delivery, Let's Encrypt issuance/renewal, HTTP-to-HTTPS redirects, upgrades and recovery. The [styled client example](https://github.com/SNodeC/snode.c-idp/blob/main/examples/minimal-mfa-app/README.md#banner) shows the application-side middleware.
