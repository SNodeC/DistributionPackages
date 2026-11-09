import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
from support import replace, rejects
from coreci import build, common
from coreci.contract import file_hash


def main():
    with tempfile.TemporaryDirectory() as temporary:
        work=Path(temporary)
        archive=work/'original.tar.gz'
        sdk={'file':'openwrt-sdk-test.tar.zst','sha256':'1'*64}
        with tarfile.open(archive,'w:gz') as stream:
            for name,data in [('coreci-sdk.json',json.dumps(sdk).encode()),('include/a.h',b'header')]:
                info=tarfile.TarInfo(name)
                info.size=len(data)
                stream.addfile(info,io.BytesIO(data))
        sums=file_hash(archive)+'  a_1.0.0-r3.tar.gz\n'
        target={'id':'t1','build':{'format':'ipk'}}
        environment={'sdk':{'url':'https://sdk.example/openwrt-sdk-test.tar.zst','sha256':'1'*64}}
        calls=[]
        def download(url,path,*args):
            if url.endswith('SHA256SUMS.asc'):
                Path(path).write_bytes(b'signature')
            elif url.endswith('SHA256SUMS'):
                Path(path).write_text(sums)
            else:
                Path(path).write_bytes(archive.read_bytes())
        def command(args,**kwargs):
            calls.append(args)
            if args[0]=='gpg':
                assert args[args.index('--output')+1].endswith('trusted.gpg')
                Path(args[args.index('--output')+1]).write_bytes(b'keyring')
            else:
                assert args[0]=='gpgv' and 'SHA256SUMS.asc' in args[-2]
            return subprocess.CompletedProcess(args,0)
        destination=work/'good'
        destination.mkdir()
        with replace(common,'download',download),replace(build.subprocess,'run',command):
            build.export_dependency({'url':'https://feed.example/'},'a','1.0.0',3,target,environment,destination,work/'public.asc')
            assert (destination/'development/include/a.h').read_bytes()==b'header'
            assert not (destination/'development/coreci-sdk.json').exists()
            wrong=work/'wrong'
            wrong.mkdir()
            rejects(build.export_dependency,{'url':'https://feed.example/'},'a','1.0.0',3,target,
                    {'sdk':dict(environment['sdk'],sha256='2'*64)},wrong,work/'public.asc',text='SDK mismatch')
        assert [args[0] for args in calls]==['gpg','gpgv','gpg','gpgv']
    print('export: detached signature verification, exact checksum and SDK identity before staging passed')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
