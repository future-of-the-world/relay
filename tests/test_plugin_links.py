"""The eval tool's sandbox reads a plugin folder but not a link's target outside it (paid run 30 Oct, plan-one-line:
`import relay_toml` failed in plugins/relay/bin/kit). Every plugin bin must import with only its own folder readable."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_plugin_links  # noqa: E402


class PluginLinks(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)

    def copy_repo(self) -> str:
        """The repo's lib/ and plugins/ as links, in a scratch root."""
        root = os.path.join(self.tmp, "repo")
        for folder in ("lib", "plugins"):
            shutil.copytree(os.path.join(ROOT, folder), os.path.join(root, folder), symlinks=True)
        shutil.copyfile(os.path.join(ROOT, "prices.toml"), os.path.join(root, "prices.toml"))
        return root

    def kit(self, root: str) -> subprocess.CompletedProcess[str]:
        """kit as the sandbox runs it: from a scratch project, with the repo's lib/ unreadable (removed)."""
        project = os.path.join(self.tmp, "project")
        os.makedirs(project, exist_ok=True)
        shutil.rmtree(os.path.join(root, "lib"))
        os.remove(os.path.join(root, "prices.toml"))
        return subprocess.run([sys.executable, os.path.join(root, "plugins", "relay", "bin", "kit"), "dump"],
                              cwd=project, capture_output=True, text=True, check=False)

    def test_kit_imports_with_the_target_out_of_reach(self) -> None:
        root = self.copy_repo()
        with relay_plugin_links.real_files(root):
            got = self.kit(root)
        # kit gets past its imports and stops at the missing .claude/kit.toml (exit 1, naming the file)
        self.assertNotIn("ModuleNotFoundError", got.stderr)
        self.assertIn("kit.toml", got.stderr + got.stdout)

    def test_kit_fails_on_dangling_links(self) -> None:
        # the failure the paid run showed: with the links left as they are, the import cannot resolve
        got = self.kit(self.copy_repo())
        self.assertIn("ModuleNotFoundError", got.stderr)

    def test_links_come_back(self) -> None:
        root = self.copy_repo()
        path = os.path.join(root, "plugins", "relay", "lib", "relay_toml.py")
        text = os.readlink(path)
        with relay_plugin_links.real_files(root):
            self.assertFalse(os.path.islink(path))
        self.assertEqual(os.readlink(path), text)

    def test_links_come_back_after_an_error(self) -> None:
        root = self.copy_repo()
        path = os.path.join(root, "plugins", "relay", "lib", "relay_toml.py")
        with self.assertRaises(RuntimeError):
            with relay_plugin_links.real_files(root):
                raise RuntimeError("eval died")
        self.assertTrue(os.path.islink(path))


if __name__ == "__main__":
    unittest.main()
