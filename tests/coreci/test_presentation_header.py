"""Exact reference headers and unchanged content on baseline or captured feed data."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from golden import DATA, ROOT, prepare, without_header
from coreci import presentation as p

HEADERS = Path(__file__).parent/'data/headers'


def compare(feed, before, names, exists=None):
    paths=p.render(feed, exists=exists)
    assert paths and all(name.startswith('status/') and name.endswith('.md') for name in paths)
    for name in names:
        raw=(feed/name).read_bytes()
        assert without_header(raw,name)==without_header((before/name).read_bytes(),name), name
    for name in paths:
        raw=(feed/name).read_text()
        header=re.search(r'<!-- snodec:begin page-header -->.*?<!-- snodec:end page-header -->',raw,re.S).group()
        reference=(HEADERS/'docs.md').read_text().rstrip('\n')
        reference=reference.replace('../../media/nav/','../docs/media/nav/').replace('../../../README.md#banner','../README.md#banner')
        reference=reference.replace('banner-installation','banner-package-status').replace('Packages — Installation','Packages — Package status')
        overview=name=='status/README.md'
        reference=reference.replace('href="../README.md#banner" title="Up to Installation"',
            'href="'+('../README.md#banner' if overview else 'README.md#banner')+'" title="Up to Installation"')
        reference=reference.replace('up-installation-', 'up-packages-' if overview else 'up-package-status-')
        reference=reference.replace('Up to Installation','Up to Packages' if overview else 'Up to Package status')
        assert header==reference,name
    assert hashlib.sha256((HEADERS/'docs.md').read_bytes()).hexdigest()==\
        '7cacecf6668717ed37a80bdf5dc797a2b88a2dd605c2e23082a0d431150f05d1'
    print(f'{len(names)} files: README/badges byte-identical; status Markdown differs only by exact reference header')
    return None


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--feed',type=Path)
    parser.add_argument('--tree',type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)/'feed'
        if args.feed:
            shutil.copytree(args.feed,root)
            tree=json.loads(args.tree.read_text())['tree']['tree']
            files={item['path'] for item in tree if item['type']=='blob'}
            names=sorted(name for name in files if name=='README.md' or name.startswith('status/badges/')
                         or name.startswith('status/') and name.endswith('.md'))
            compare(root,args.feed,names,lambda name:name in files)
        else:
            prepare(root)
            names=[row['path'] for row in json.loads((DATA/'manifest.json').read_text())['files']
                   if row['path']=='README.md' or row['path'].startswith('status/badges/')
                   or row['path'].startswith('status/') and row['path'].endswith('.md')]
            compare(root,DATA/'files',names)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
