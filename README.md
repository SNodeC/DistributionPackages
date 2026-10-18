<a id="banner"></a>
<a id="project-overview"></a>

<p><picture><source media="(max-width: 600px)" srcset="docs/media/hero-mobile.svg"><img src="docs/media/banner.svg" alt="DistributionPackages — Package tooling and publication." width="100%"></picture></p>

<!-- snodec:begin organization -->
<p><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="docs/media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="docs/media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="docs/media/nav/account-dark.svg"><img align="right" src="docs/media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="docs/media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="docs/media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="docs/media/nav/organization-dark.svg"><img align="right" src="docs/media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="#banner" title="DistributionPackages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="docs/media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="docs/media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="docs/media/nav/repository-dark.svg"><img align="right" src="docs/media/nav/repository-light.svg" alt="DistributionPackages repository" title="DistributionPackages repository"></picture></a><br clear="all"></p>
<!-- snodec:end organization -->

# DistributionPackages

Build recipes, authenticated handoffs, signing and publication for SNode.C distribution packages. This is the maintainer control repository; [Packages](https://github.com/SNodeC/Packages#banner) is the public installation and availability hub.

## Operations

This repository captures notified release commits, allocates package revisions and schedules the dependency graph in [`ci/projects.json`](ci/projects.json). Source repositories build unsigned packages through shared workflows; this coordinator authenticates, signs and publishes each target before scheduling its dependents. The manual documentation workflow remains separate. See [CI orchestration](docs/ci-orchestration.md#banner) for the trigger contracts, retries and migration order.

- [Documentation](docs/README.md#banner)
- [CI orchestration](docs/ci-orchestration.md#banner)
- [Publication and maintenance](docs/maintainers.md#banner)
- [CI setup](docs/setup.md#banner)
- [Authored Packages documentation](site/README.md#banner) (source template; navigation is resolved in the published Packages snapshot)
- [Target definitions](ci/targets/)

## Interfaces

Product workflows call the reusable notification and build workflows here. The JSON registry is the project and dependency authority; signing accepts only registered projects and verified coordinator captures and source run identities. Public documentation lives under `site/`; generated status is rendered from Packages records by `ci/publish/publication.py`. Catalogue changes do not grant signing rights.

## Local verification

```sh
python3 -m unittest discover -s tests -v
```

Tests use temporary repositories and fixtures; they do not dispatch CI or publish packages.
