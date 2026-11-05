"""Keep the existing hook's /tool/openwrt_container.py --outputs interface."""

import sys

sys.path.insert(0, "/core_ci")
from openwrt_container import outputs

if __name__ == "__main__":
    outputs()
