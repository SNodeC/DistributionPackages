Public golden inputs from SNodeC/Packages commit f1271dd923e48dcbee04fe5b0eefbf240fad53b0:
122 presentation files, their manifest, 18 receipts, and the complete Git tree metadata.
No package blobs or private keys are included. The filesystem G1 test creates regular
empty files for the receipt paths: the renderer only checks existence. The Git-tree
G1 test removes those files and answers existence from the reconstructed Git tree.

Declarations are the inventory copies from snode.c 76ca647, mqttsuite 35a4f78 and
snode.c-idp 0cfe819. status.json is the equivalent typed-status fixture, including
build-run identities and the explicit Blocked-to-Waiting mapping. identifier-map.json
records old execution IDs and their buildId-derived replacements. Immutable receipt
paths/URLs remain unchanged. G2 emits every replacement and every execution-array
ordering exception into the CTest build directory; other content must match exactly.
