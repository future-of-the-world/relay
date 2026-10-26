"""The default every test gets: relay's home and Claude's folder are temporary, never the owner's."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

import relay_config

REAL_HOME = os.path.expanduser("~")  # captured at import, before any fixture runs


def _listing(path):
    return sorted(os.listdir(path)) if os.path.isdir(path) else None


class TemporaryFoldersTest(unittest.TestCase):
    def test_writes_land_in_temporary_folders_not_the_real_ones(self):
        real_claude = os.path.join(REAL_HOME, ".claude")
        real_relay = os.path.join(REAL_HOME, ".relay")
        # Compared by listing and mtime of the real folders; nothing is ever written there.
        before = [(p, _listing(p), os.path.getmtime(p) if os.path.exists(p) else None) for p in (real_claude, real_relay)]
        for folder in (relay_config.claude_dir(), relay_config.home_dir()):
            self.assertNotEqual(os.path.realpath(folder), os.path.realpath(real_claude))
            self.assertNotEqual(os.path.realpath(folder), os.path.realpath(real_relay))
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "sentinel"), "w") as handle:
                handle.write("x")
        self.assertEqual(os.path.expanduser("~"), os.environ["HOME"])
        self.assertNotEqual(os.path.realpath(os.environ["HOME"]), os.path.realpath(REAL_HOME))
        after = [(p, _listing(p), os.path.getmtime(p) if os.path.exists(p) else None) for p in (real_claude, real_relay)]
        self.assertEqual(before, after)
        self.assertNotIn("sentinel", _listing(real_claude) or [])


if __name__ == "__main__":
    unittest.main()
