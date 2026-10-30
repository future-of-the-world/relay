"""The eval tool's sandbox reads a plugin folder but not a link's target outside it (paid run 30 Oct, plan-one-line:
`import relay_toml` failed in plugins/relay/bin/kit). Every plugin bin must import with only its own folder readable."""
import os
import shutil
import subprocess
import sys
import stat
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_ci  # noqa: E402
import relay_plugin_links  # noqa: E402
from test_ci_python import Recorder, stubs  # noqa: E402
from contextlib import redirect_stdout  # noqa: E402
import io  # noqa: E402
from unittest import mock  # noqa: E402


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

    def small_root(self, executable: bool = False) -> tuple[str, str, str]:
        """A root with lib/relay_x.py and plugins/p/lib/relay_x.py -> ../../../lib/relay_x.py; returns (root, link, text)."""
        root = os.path.join(self.tmp, "small")
        os.makedirs(os.path.join(root, "lib"))
        os.makedirs(os.path.join(root, "plugins", "p", "lib"))
        source = os.path.join(root, "lib", "relay_x.py")
        with open(source, "w") as handle:
            handle.write("X = 1\n")
        os.chmod(source, 0o755 if executable else 0o644)
        link = os.path.join(root, "plugins", "p", "lib", "relay_x.py")
        text = "../../../lib/relay_x.py"
        os.symlink(text, link)
        return root, link, text

    def test_the_eval_step_runs_with_real_files(self) -> None:
        # F1: the claude call must see a regular file with the target's content; afterwards the link is back
        root, link, text = self.small_root()
        seen: list[tuple[bool, str]] = []

        def answer(argv: list[str]) -> tuple[int, str]:
            if argv[0] == "claude":
                with open(link) as handle:
                    seen.append((os.path.islink(link), handle.read()))
            if "ceiling" in argv:
                return 0, "1 15\n"
            if "estimate" in argv:
                return 0, "about $4\n"
            return 0, ""
        env = {"PATH": stubs(os.path.join(root, "stub"), ["git", "jq", "python3", "bun", "claude", "podman"])}
        ci = relay_ci.Ci(root, False, env=env, runner=Recorder(answer))
        ci.lib_links = lambda log: 0   # type: ignore[method-assign]  # no git repository here
        ci.prepare()
        with redirect_stdout(io.StringIO()):
            ci.plugin_evals()
        self.assertEqual(seen, [(False, "X = 1\n")])
        self.assertEqual(os.readlink(link), text)

    def test_a_failed_copy_still_gets_its_link_back(self) -> None:
        # F2a: the copy raises after the link was removed; the link must exist again
        root, link, text = self.small_root()
        with mock.patch.object(relay_plugin_links.shutil, "copy2", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                with relay_plugin_links.real_files(root):
                    pass
        self.assertEqual(os.readlink(link), text)

    def test_a_copy_keeps_the_mode_of_its_target(self) -> None:
        # F2c: a link to an executable is an executable file inside the block
        root, link, _text = self.small_root(executable=True)
        with relay_plugin_links.real_files(root):
            self.assertTrue(os.stat(link).st_mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
