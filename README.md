<a id="project-overview"></a>

<p><picture><source media="(max-width: 600px)" srcset="docs/media/hero-mobile.svg"><img src="docs/media/banner.svg" alt="DistributionPackages" width="100%"></picture></p>

<!-- snodec:begin organization -->
<p><a href="https://github.com/SNodeC" title="SNodeC organization"><picture><source media="(prefers-color-scheme: dark)" srcset="site/docs/media/nav/organization-dark.svg"><img align="right" src="site/docs/media/nav/organization-light.svg" alt="SNodeC organization" width="160" height="28"></picture></a><br clear="all"></p>
<!-- snodec:end organization -->

# DistributionPackages

Build recipes, authenticated handoffs, signing and publication for SNodeC distribution packages. This is the maintainer control repository; [Packages](https://github.com/SNodeC/Packages#project-overview) is the public installation and availability hub.

## Operations

- [Documentation](docs/README.md#page-overview)
- [Publication and maintenance](docs/maintainers.md#page-overview)
- [CI setup](docs/setup.md#page-overview)
- [Authored Packages documentation](site/README.md) (source template; navigation is resolved in the published Packages snapshot)
- [Target definitions](ci/targets/)

## Interfaces

Product workflows call the captured scripts in `ci/`. Signing accepts only deliberately allow-listed projects and verified run identities. Public documentation lives under `site/`; generated status is rendered from Packages records by `ci/publish/publication.py`. Catalogue changes do not grant signing rights.

## Local verification

```sh
python3 -m unittest discover -s tests -v
```

Tests use temporary repositories and fixtures; they do not dispatch CI or publish packages.
