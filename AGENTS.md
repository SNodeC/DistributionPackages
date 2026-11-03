# Trusted core-ci workers

MariaDB and the separate core-ci controller are the sole selection, revision and readiness authority. This repository validates frozen assignments and performs GitHub builds/signing/publication only. Do not add a coordinator, scheduler or dependency-selection implementation here.

Source repositories own their schema-1 definitions and hooks. Prepare dependencies in the disposable image before running source hooks as the existing isolated unprivileged user. Do not pass signing or feed-writing credentials to hooks. Source artifact access uses the read-only App; publication and status writers share the existing feed concurrency group.

Preserve exact artifact/run/job/assignment bindings, explicit public receipt confirmation and immutable workflow/tooling pins. Status rendering is presentation only and consumes the existing compact initial SSE snapshot. It never authorizes a build or package publication.

Preserve signing-key bytes and unrelated local work. Do not create or move source release tags or trigger the package chain until the owner's explicit build checkpoint approval. Python/shell/JSON/YAML apply here; controller C++ belongs in core-ci.
