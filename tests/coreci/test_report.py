import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
from urllib.parse import parse_qs
from support import ROOT


def main():
    action=(ROOT/'.github/actions/coreci-report/action.yml').read_text()
    assert "if: inputs.callback_url != ''" in action
    script=textwrap.dedent(action.split('      run: |\n',1)[1])
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        curl=root/'curl'
        curl.write_text('#!/usr/bin/python3\nimport os,sys,json\nopen(os.environ["CAPTURE"],"w").write(json.dumps(sys.argv[1:]))\n')
        curl.chmod(0o755)
        capture=root/'arguments'
        env=dict(os.environ,PATH=str(root)+os.pathsep+os.environ['PATH'],CAPTURE=str(capture),
                 CALLBACK_URL='https://callback.invalid/api/v1/builds/a%2Bb~t~1.0.0~r1/report',
                 CORECI_CALLBACK_SECRET='unit-test-only',REPORT_PHASE='build',REPORT_STATUS='failed',
                 REPORT_ARTIFACT='coreci-a+b~t~1.0.0~r1',REPORT_FEED_COMMIT='',
                 REPORT_REASON="quote' & plus+ newline\n"+'é'*1000,GITHUB_RUN_ID='123',GITHUB_RUN_ATTEMPT='2')
        subprocess.run(['bash','-c',script],env=env,check=True)
        args=json.loads(capture.read_text())
        assert args[-1]==env['CALLBACK_URL'], 'callback URL must be used verbatim'
        assert args[args.index('--retry')+1]=='5' and '--retry-all-errors' in args and '--fail' in args
        body=args[args.index('--data-raw')+1]
        headers=[args[i+1] for i,v in enumerate(args) if v=='--header']
        timestamp=next(v.split(': ',1)[1] for v in headers if v.startswith('X-CoreCI-Timestamp:'))
        signature=next(v.split('sha256=',1)[1] for v in headers if v.startswith('X-CoreCI-Signature-256:'))
        assert signature==hmac.new(b'unit-test-only',(timestamp+'.'+body).encode(),hashlib.sha256).hexdigest()
        fields=parse_qs(body,keep_blank_values=True)
        assert fields['run_id']==['123'] and fields['run_attempt']==['2']
        assert fields['artifact']==[env['REPORT_ARTIFACT']]
        assert len(fields['reason'][0].encode())<=1000 and fields['reason'][0].startswith("quote' & plus+ newline\n")
    print('report: real openssl HMAC, exact callback URL, form escaping and UTF-8 byte bound passed')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
