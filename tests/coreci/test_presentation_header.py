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
        assert without_header(raw,name)==(before/name).read_bytes(), name
    for name in paths:
        raw=(feed/name).read_text()
        header=re.search(r'<!-- snodec:begin page-header -->.*?<!-- snodec:end page-header -->',raw,re.S).group()
        reference=(HEADERS/('README.md' if name=='status/README.md' else 'snodec.md')).read_text().rstrip('\n')
        assert header==reference.replace('<a id="page-overview">','<a id="banner"></a>\n<a id="page-overview">'),name
    assert hashlib.sha256((HEADERS/'snodec.md').read_text().rstrip('\n').encode()).hexdigest()==\
        'd5200a286f267741391717400d00cbd2ee13dc03e03238995b0c989da53f9341'
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
