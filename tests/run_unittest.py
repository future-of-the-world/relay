"""The library tests under unittest (what bin/ci runs) with the same temporary-folder default pytest gets."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import tmp_default

if __name__ == "__main__":
    tmp_default.patch_unittest()
    unittest.main(module=None, argv=["unittest", "discover", "-s", HERE, "-p", "test_*.py"])
