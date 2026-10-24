<a id="banner"></a>
<a id="project-overview"></a>

<p><picture><source media="(max-width: 600px)" srcset="docs/media/hero-mobile.svg"><img src="docs/media/banner.svg" alt="DistributionPackages — Package tooling and publication." width="100%"></picture></p>

<!-- snodec:begin organization -->
<p><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="docs/media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="docs/media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="docs/media/nav/account-dark.svg"><img align="right" src="docs/media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="docs/media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="docs/media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="docs/media/nav/organization-dark.svg"><img align="right" src="docs/media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="#banner" title="DistributionPackages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="docs/media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="docs/media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="docs/media/nav/repository-dark.svg"><img align="right" src="docs/media/nav/repository-light.svg" alt="DistributionPackages repository" title="DistributionPackages repository"></picture></a><br clear="all"></p>
<!-- snodec:end organization -->

# DistributionPackages

Repository-owned builds, authenticated handoffs, central signing and publication for SNode.C distribution packages. This is the maintainer control repository; [Packages](https://github.com/SNodeC/Packages#banner) is the public installation and availability hub.

## Operations

This repository captures notified release commits, allocates package revisions and records activation after a permitted repository sends its own valid tag notification. [`ci/projects.json`](ci/projects.json) is the allowlist. Each selected tag supplies its full matrix and dependency graph. Source repositories build unsigned packages through shared workflows; this coordinator authenticates, signs and publishes each target before scheduling its dependents. Cascades follow only highest-current prerequisite publications; overlapping roots wait for every selected arm and coalesce duplicate work. Direct request authority and supersession remain scoped to the version and target. The manual documentation workflow remains separate. See [CI orchestration](docs/ci-orchestration.md#banner) for the trigger contracts, retries and first-deployment order.

- [Documentation](docs/README.md#banner)
- [CI orchestration](docs/ci-orchestration.md#banner)
- [Repository registration and onboarding](docs/setup.md#add-a-repository)
- [Publication and maintenance](docs/maintainers.md#banner)
- [CI setup](docs/setup.md#banner)
- [Authored Packages documentation](site/README.md#banner) (source template; navigation is resolved in the published Packages snapshot)

## Interfaces

Product workflows call the reusable notification and build workflows here. The master JSON lists repositories and policy overrides; each source `ci/packages.json` owns its matrix, dependencies and build hooks; signing accepts only registered projects and verified coordinator captures and source run identities. The trusted publisher validates every package control against pinned ownership, version/revision and architecture before indexing/signing. Default-branch public keys are the deployed authority, with a captured family-key match required. Public documentation lives under `site/`; generated status is rendered from Packages records by `ci/publish/publication.py`. Catalogue changes do not grant signing rights.

## Local verification

```sh
mkdir -p /tmp/codex/build/snodec/package-ci
PYTHONPATH=tests:. TMPDIR=/tmp/codex/build/snodec/package-ci \
python3 tests/run_package_checks.py --actionlint /path/to/actionlint \
  /path/to/snode.c /path/to/mqttsuite /path/to/snode.c-idp
```

Tests use temporary repositories and fixtures; they do not dispatch CI or publish packages.
