import subprocess
from support import replace
from coreci import lease


def main():
    for remote,expected in [('b'*40,'conflict'),('c'*40,'confirmed'),('a'*40,'error')]:
        calls=[]
        def failed(*args):
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
    print('lease: confirmed conflict retry, ambiguous success resolution, unknown error preservation and five-attempt ceiling passed')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
