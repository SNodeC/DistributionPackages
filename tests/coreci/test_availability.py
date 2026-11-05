from pathlib import Path
import tempfile
from support import replace, rejects
from coreci import publish


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        (root/'Packages').write_bytes(b'new index')
        calls=[]
        def download(url,target,*args):
            calls.append(url)
            Path(target).write_bytes(b'stale cache' if len(calls)==1 else b'new index')
        with replace(publish,'download',download),replace(publish.time,'sleep',lambda _:None):
            publish.availability({'url':'https://feed.example/'},['Packages'],root)
        assert calls==['https://feed.example/Packages']*2
        ticks=iter([0,901])
        with replace(publish.time,'monotonic',lambda:next(ticks)):
            rejects(publish.availability,{'url':'https://feed.example/'},['Packages'],root,text='timeout')
    print('availability: stale content waits for exact index hash; deadline reports failure passed')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
