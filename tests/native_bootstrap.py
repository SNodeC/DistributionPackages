"""Image identity checks through the real native bootstrap entry point."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core_ci"))
import native_container as module

class Suite(unittest.TestCase):
    def check(self,distribution,suite,release,sources='',accepted=True,actual_arch='amd64'):
        class File:
            def __init__(self,name): self.name=name
            def read_text(self): return sources if self.name.endswith('debian.sources') else release
            def iterdir(self): return iter(())
            def is_file(self): return True
        target={'distribution':distribution,'suite':suite,'arch':'amd64','build':{'format':'deb'}}
        with patch.object(module,'assignment',return_value={'target':target}),patch.object(module,'Path',File),patch.object(module,'output',return_value=actual_arch),patch.object(sys,'argv',['fixture','--install']):
            if accepted: module.main()
            else:
                with self.assertRaises(ValueError): module.main()
    def test_rocky_major(self): self.check('rocky','10','ID=rocky\nVERSION_ID=10.1\n')
    def test_rocky_wrong_major(self): self.check('rocky','9','ID=rocky\nVERSION_ID=10.1\n',accepted=False)
    def test_sid(self): self.check('debian','sid','ID=debian\nVERSION_CODENAME=forky\n','Types: deb\nSuites: sid\n')
    def test_sid_wrong_source(self): self.check('debian','sid','ID=debian\nVERSION_CODENAME=forky\n','Suites: forky\n',False)
    def test_ubuntu_point_release(self): self.check('ubuntu','24.04','ID=ubuntu\nVERSION_ID=24.04\nVERSION_CODENAME=noble\n')
    def test_ubuntu_wrong_point_release(self): self.check('ubuntu','24.04','ID=ubuntu\nVERSION_ID=24.10\nVERSION_CODENAME=oracular\n',accepted=False)
    def test_rocky_9(self): self.check('rocky','9','ID=rocky\nVERSION_ID=9.6\n')
    def test_stable(self): self.check('debian','trixie','ID=debian\nVERSION_ID=13\nVERSION_CODENAME=trixie\n')
    def test_wrong_distribution(self): self.check('ubuntu','trixie','ID=debian\nVERSION_CODENAME=trixie\n',accepted=False)
    def test_wrong_arch(self): self.check('debian','trixie','ID=debian\nVERSION_CODENAME=trixie\n',accepted=False,actual_arch='arm64')
if __name__=='__main__': unittest.main()
