"""The tests folder as a package, so `python3 -m unittest tests.test_x` works; importing it gives every test its own temporary
folders (tests/tmp_default.py), the same as the gate's runner does. The test files import their helpers by bare name (`from
relay_testbase import ...`), so this folder is put on the path first."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tmp_default

tmp_default.patch_unittest()
