"""Validate the six source revisions qualified for the enrollment handover."""
import graphlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from coreci.common import declaration, document, registry, relative_path

refs = document(Path(sys.argv[1]).read_bytes())
assert set(refs) == set(registry()['repositories'])
definitions = {}
errors = []
for repo, sha in refs.items():
    try:
        assert len(sha) == 40 and all(character in '0123456789abcdef' for character in sha)
        doc = declaration(repo, sha)
        assert doc['schema'] == 1
        base = doc.get('revision_base', 0)
        assert type(base) is int and 0 <= base <= 1000000
        relative_path(doc['build']['native'])
        assert doc['package'] not in definitions
        definitions[doc['package']] = doc
        print(f"{repo}@{sha}: {doc['package']}, {len(doc['matrix'])} targets, revision_base={base}")
    except Exception as error:
        errors.append(f'{repo}@{sha}: {type(error).__name__}: {error}')
assert not errors, '\n'.join(errors)

graphlib.TopologicalSorter({name: set(doc['depends_on']) for name, doc in definitions.items()}).prepare()
allowed = {entry['id'] for entry in definitions['snodec-idp']['matrix']}
assert len(allowed) == 26
excluded = {'ubuntu-noble-amd64', 'ubuntu-noble-arm64', 'rocky-9-x86_64',
            'rocky-9-aarch64', 'raspberrypios-bookworm-arm64'}
for name in ('core-ci', 'aisuite', 'codexui'):
    doc = definitions[name]
    assert {entry['id'] for entry in doc['matrix']} == (allowed - excluded if name == 'codexui' else allowed)
    assert all(entry['family'] == 'native' and entry['distribution'] != 'openwrt' for entry in doc['matrix'])
    assert all(entry['build']['format'] in ('deb', 'rpm') for entry in doc['matrix'])
for name, doc in definitions.items():
    targets = {entry['id'] for entry in doc['matrix']}
    for prerequisite in doc['depends_on']:
        parent = definitions[prerequisite]
        assert targets <= {entry['id'] for entry in parent['matrix']}
        for fmt in {entry['build']['format'] for entry in doc['matrix'] if entry['family'] == 'native'}:
            assert parent['development_packages'][fmt]
print('PASS: six source declarations; acyclic graph, prerequisite target coverage and development exports; new targets exactly 26/26/21 with no OpenWrt')
