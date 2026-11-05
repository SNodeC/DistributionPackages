# Phase 4b workers

The new entry points are `python3 -m coreci.build resolve|run` and
`python3 -m coreci.publish check-run|resolve|run`. Scheduling, dependency choices
and revision allocation remain in the controller. Registry policy is read from
`ci/registry.json` in the workflow run checkout. The staging registry is added on
a separate branch in Part 2; production registry preparation belongs to 4c.

No `core_ci/` module or old `core-ci-*.yml` workflow is changed. Public inputs
arrive through `INPUT_<UPPERCASE_WORKFLOW_INPUT>` variables. Checkout credentials
are not persisted; build containers receive only the hook environment of SPEC
7.2 and read-only source/recipe/tool mounts. Hooks run as uid/gid 1000. Native
prerequisites are installed before hooks; metadata is written per prerequisite.

## Publisher environment

The feed's environment supplies `GPG_PRIVATE_KEY` (ASCII armored), optional
`GPG_PASSPHRASE`, `USIGN_PRIVATE_KEY`, `APK_PRIVATE_KEY` and `FEED_PUSH_TOKEN`
(contents-write permission for this feed repository only). Public keys and their
trust anchors come from the registry. Private files are owner-readable temporary
files and are never mounted into consumer-validation containers. Only report
steps receive the organization secret `CORECI_CALLBACK_SECRET`.

A duplicate unsigned-file ledger is a no-op. Any ledger conflict or pre-existing
package/export without its ledger fails before signing or feed mutation. New
publications validate the prepared checkout, create an orphan-root commit, push
with the exact checkout lease, and wait for matching public index hashes. The
publisher waits briefly for a build run to finish if its final callback arrived
before GitHub marked it complete; provenance must still be successful.

## Local verification

```sh
cmake -S tests/coreci -B /tmp/codex/build/DistributionPackages/phase-4b
cmake --build /tmp/codex/build/DistributionPackages/phase-4b
ctest --test-dir /tmp/codex/build/DistributionPackages/phase-4b --output-on-failure
~/.local/bin/actionlint .github/workflows/coreci-build.yml .github/workflows/coreci-publish.yml
```

Tests use plain Python executables through CTest, without a test framework. They
exercise real unsigned deb/RPM generation via the unchanged CPack helper and real
OpenSSL callback signing. Docker and network/publication boundaries use scoped
replacements. No staging or production workflow is dispatched by these tests.
Full container and feed acceptance is the owner-gated Part 2 staging proof.

## Reuse and copy accounting

Unchanged imports include `contract.versions`, `package_metadata`, hashing,
bounded output, JSON/file validation and safe archive extraction;
`environment.native`/`sdk`, `sdk.prepare`, `native.TOOLS`;
`native_container.package`, `openwrt_container.outputs`;
`sign_native.signing_key`, `sign_file`, `apt_indexes`, `rpm_indexes`;
`sign_openwrt.indexes`; `publish.prepare_commit` and `checked_push`;
and GitHub REST/no-redirect helpers. No unchanged function is duplicated.

The following functions adapt existing internals because their assignment,
receipt or environment interfaces differ. For conservative accounting the entire
destination function, including rewritten lines, is counted as adapted/copied;
the table does not claim that every such line is verbatim. Shared import lines
and generic function guards are counted with new orchestration, not as copied
implementations.

| Destination | Source function(s) | Adapted physical lines |
| --- | --- | ---: |
| `coreci/build.py:install_lines` | `core_ci/native.py:build; core_ci/native_container.py:main` | 20 |
| `coreci/build.py:build` | `core_ci/native.py:build` | 70 |
| `coreci/container.py:inspect` | `core_ci/contract.py:validate_outputs` | 45 |
| `coreci/container.py:hook` | `core_ci/native_container.py:execute_hook; core_ci/openwrt_container.py:main` | 29 |
| `coreci/publish.py:publish` | `core_ci/sign_native.py:update; core_ci/sign_openwrt.py:update; core_ci/publish.py:main` | 89 |
| `coreci/publish.py:shlex_passphrase` | `core_ci/sign_native.py:update` | 7 |
| `coreci/publish.py:openwrt_indices` | `core_ci/sign_openwrt.py:signing_tools/update` | 30 |

Production: **1328** added physical lines: **290** conservatively
classified adapted/copy lines and **1038** new lines. This includes all
Python, workflow and action lines (comments and blanks included). The approved
ceiling is 2,600. Tests and this document are accounted separately.
