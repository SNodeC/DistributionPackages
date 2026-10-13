<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->
<a id="project-overview"></a>

<p><picture><source media="(max-width: 600px)" srcset="docs/media/hero-mobile.svg"><img src="docs/media/banner.svg" alt="Packages — Signed packages for the SNode.C ecosystem." width="100%"></picture></p>

<!-- snodec:begin organization -->
<p><a href="https://github.com/SNodeC" title="SNodeC organization"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/media/nav/organization-dark.svg"><img align="right" src="docs/media/nav/organization-light.svg" alt="SNodeC organization" title="SNodeC organization" width="160" height="28"></picture></a><br clear="all"></p>
<!-- snodec:end organization -->

# SNodeC Packages

Signed packages for the SNode.C ecosystem. Choose a project and distribution, install using its signed package source, and inspect availability separately from ongoing builds.

<!-- snodec:begin menu -->
<p>
<a href="#quick-start"><img src="docs/media/menu/start.svg" alt="Start"></a>
<a href="#install"><img src="docs/media/menu/install.svg" alt="Install"></a>
<a href="status/README.md#page-overview"><img src="docs/media/menu/status.svg" alt="Status"></a>
<a href="docs/troubleshooting.md#page-overview"><img src="docs/media/menu/troubleshoot.svg" alt="Troubleshoot"></a>
<a href="docs/publication.md#page-overview"><img src="docs/media/menu/architecture.svg" alt="Architecture"></a>
<a href="#contributing"><img src="docs/media/menu/contribute.svg" alt="Contribute"></a>
</p>
<!-- snodec:end menu -->
<a id="packages"></a>

[Documentation index](docs/README.md#page-overview): installation guides, package catalogs, status meanings and troubleshooting.

## Projects

<!-- packages:begin projects -->
<!-- packages:end projects -->

<a id="installation"></a>

## Quick start

Start with your installed system, not an ongoing build: pick your distribution's guide under [Install](#install) and check its requirements. Use **Quick install** for the complete package sets or **Custom install** for selected packages, then follow the guide's Check and Next steps to confirm the installation and configure your applications. Status pages are optional: consult them to compare available packages with a replacement build.

<a id="distributions"></a>

## Install

Select the guide matching your installed distribution, release and package architecture. Each guide covers requirements, quick installation, manual repository setup and updates.

<a id="platforms"></a>

The supported releases and architectures are generated from the publisher's target definitions. Package availability per project, release and architecture is on the [status pages](status/README.md#page-overview).

<!-- packages:begin platforms -->
<!-- packages:end platforms -->

## Signing keys

Verify downloads with the [signing keys](keys/README.md#page-overview) for your package manager. Keys are shared across architectures; keep signature verification enabled.

<a id="help"></a>

## Troubleshooting

[Diagnose installation errors](docs/troubleshooting.md#page-overview), or compare available packages and replacement builds on [project status](status/README.md#page-overview).

## How publication works

Packages is the generated destination for signed feeds, installation guides and recorded build status; DistributionPackages owns publication. See the organization [workflow graph](https://github.com/SNodeC/.github/blob/main/docs/workflow-graph.md#page-overview) for the build, signing and dependent-build chain.

[Read the column meanings and publication model](docs/publication.md#page-overview). Maintainer operations belong to DistributionPackages.

## Contributing

Report installation issues in [Packages](https://github.com/SNodeC/Packages/issues). Documentation and publisher changes belong to [DistributionPackages](https://github.com/SNodeC/DistributionPackages#project-overview). Do not edit generated feeds, keys or status pages by hand.

## Ecosystem

[SNodeC organization](https://github.com/SNodeC) · [SNode.C](https://github.com/SNodeC/snode.c#project-overview) · [MQTTSuite](https://github.com/SNodeC/mqttsuite#project-overview)

[Contributing](https://github.com/SNodeC/.github/blob/HEAD/CONTRIBUTING.md) · [Security](https://github.com/SNodeC/.github/blob/HEAD/SECURITY.md)
