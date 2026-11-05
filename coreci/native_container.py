"""Keep the existing hook's /tool/native_container.py --package interface."""

import sys

sys.path.insert(0, "/core_ci")
from native_container import package

if __name__ == "__main__":
    package(sys.argv[2])
