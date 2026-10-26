"""The library tests under unittest (what bin/ci runs) with the same temporary-folder default pytest gets."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))  # names like tests.test_rules need the repo root

import tmp_default

if __name__ == "__main__":
    tmp_default.patch_unittest()
    names = sys.argv[1:]  # names given: run them; none: discover every library test
    argv = ["unittest", *names] if names else ["unittest", "discover", "-s", HERE, "-p", "test_*.py"]
    unittest.main(module=None, argv=argv)
