"""All 178 current units retain their complete target definition through the catalog."""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from coreci.common import select
from coreci.contract import canonical

root = Path(__file__).resolve().parents[2]
count = 0
for path in sorted((root / "tests/coreci/fixtures/catalog").glob("*.json")):
    doc = json.loads(path.read_bytes())
    reduced = dict(doc, matrix=[{key: value for key, value in entry.items() if key in ("id", "feed")}
                                for entry in doc["matrix"]])
    for entry in doc["matrix"]:
        assert canonical(select(doc, entry["id"])).encode() == canonical(entry).encode()
        assert canonical(select(reduced, entry["id"])).encode() == canonical(entry).encode()
        count += 1
assert count == 178
assert select({"matrix": [{"id": "debian-trixie-amd64", "feed": "other"}]}, "debian-trixie-amd64")["feed"] == "other"
for entries in [[{"id": "unknown"}], [{"id": "debian-trixie-amd64"}] * 2]:
    rejected = False
    try:
        select({"matrix": entries}, entries[0]["id"])
    except ValueError:
        rejected = True
    assert rejected
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "catalog.json"
    path.write_text('{"targets":[{"id":"a"},{"id":"a"}]}')
    with patch("coreci.common.registry", lambda: {"targets": str(path.name)}), patch("coreci.common.Path", lambda _: path):
        rejected = False
        try:
            select({"matrix": [{"id": "a"}]}, "a")
        except ValueError:
            rejected = True
        assert rejected
print("178/178 catalog targets byte-identical in canonical JSON; transition and invalid catalog cases passed")
