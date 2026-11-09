import subprocess
import contextlib
import io
from support import replace
from coreci import lease
import contract
import publish


def main():
    for remote,expected in [('b'*40,'conflict'),('c'*40,'confirmed'),('a'*40,'error')]:
        calls=[]
        def failed(*args, **kwargs):
            assert kwargs == {"timeout":600,"progress":True}
            raise subprocess.CalledProcessError(1,['git','push'])
        def output(args):
            return remote if args[-1]=='FETCH_HEAD' else 'c'*40
        with replace(lease,'checked_push',failed),replace(lease,'output',output), \
             replace(lease.subprocess,'run',lambda *args,**kwargs:calls.append(args)):
            outcome=None
            try:
                outcome=lease.push('scratch','main','unit-test-only','a'*40)
            except lease.LeaseConflict:
                outcome='conflict'
            except subprocess.CalledProcessError:
                outcome='error'
            assert outcome==('c'*40 if expected=='confirmed' else expected)
        assert len(calls)==1, 'an ambiguous push must be inspected, never blindly repeated'
    for remote,expected in [('a'*40,'conflict'),('b'*40,'conflict'),('c'*40,'c'*40)]:
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(['git','push'],600)
        def resolved(args):
            return remote if args[-1]=='FETCH_HEAD' else 'c'*40
        with replace(lease,'checked_push',timeout),replace(lease,'output',resolved), \
             replace(lease.subprocess,'run',lambda *args,**kwargs:None):
            outcome=None
            try:
                outcome=lease.push('scratch','main','unit-test-only','a'*40)
            except lease.LeaseConflict:
                outcome='conflict'
            assert outcome==expected
    calls=[]
    def timed_out():
        calls.append(1)
        raise subprocess.TimeoutExpired(['git','push'],120)
    uncertain=False
    try:
        lease.retry('scratch',timed_out)
    except subprocess.TimeoutExpired:
        uncertain=True
    assert uncertain and len(calls)==1, 'an unclassified timeout must not be retried'
    calls=[]
    restored=[]
    sleeps=[]
    def operation():
        calls.append(1)
        if len(calls)<3:
            raise lease.LeaseConflict('confirmed')
        return 'published'
    with replace(lease.time,'sleep',lambda n:sleeps.append(n)):
        assert lease.retry('scratch',operation,lambda root:restored.append(root))=='published'
    assert len(calls)==3 and restored==['scratch','scratch'] and all(5<=s<=30 for s in sleeps)
    calls=[]
    def exhausted():
        calls.append(1)
        raise lease.LeaseConflict('confirmed')
    caught=False
    with replace(lease.time,'sleep',lambda _:None):
        try:
            lease.retry('scratch',exhausted,lambda _:None)
        except lease.LeaseConflict:
            caught=True
    assert caught and len(calls)==5
    recorded=[]
    with replace(publish,'run',lambda args,**kwargs:recorded.append((args,kwargs))), \
         replace(publish,'output',lambda args:'c'*40):
        publish.checked_push('scratch','main','unit-test-only','a'*40)
        publish.checked_push('scratch','main','unit-test-only','a'*40,timeout=600,progress=True)
    assert recorded[0][1]['timeout']==120 and '--progress' not in recorded[0][0]
    assert recorded[1][1]['timeout']==600 and '--progress' in recorded[1][0]
    with replace(contract.subprocess,'run',lambda args,**kwargs:recorded.append((args,kwargs))):
        contract.run(['other'])
        contract.run(['feed-push'],timeout=600)
    assert recorded[-2][1]['timeout']==120 and recorded[-1][1]['timeout']==600
    log=io.StringIO()
    with replace(lease,'checked_push',lambda *args,**kwargs:'c'*40),contextlib.redirect_stdout(log):
        assert lease.push('scratch','main','unit-test-only','a'*40)=='c'*40
    lines=log.getvalue().splitlines()
    assert lines[0].startswith('push start ') and lines[1].startswith('push end ')
    assert lines[1].endswith(' success') and float(lines[1].split()[-2])>=0
    print('lease: confirmed conflict retry, ambiguous success resolution, unknown error preservation and five-attempt ceiling passed')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
