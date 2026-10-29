"""Plugin lib files are links to the one source in lib/ (queue item lib-modules-are-committed-in-three-copies).
Two code paths copy plugin folders and must treat a link right: the bench's plugin copy for `--plugin-dir`, and `relay improve adopt`,
which copies a candidate's files back onto plugins/<p>/. Every folder here is a temporary one."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_bench  # noqa: E402


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class Repo(unittest.TestCase):
    """A scratch 'repo': lib/relay_x.py, and plugins/delegate with a link plugins/delegate/lib/relay_x.py -> ../../../lib/relay_x.py."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        write(os.path.join(self.tmp, "lib", "relay_x.py"), "X = 1\n")
        self.plugin = os.path.join(self.tmp, "plugins", "delegate")
        write(os.path.join(self.plugin, "agents", "worker.md"), "---\nname: worker\nrelay-tier: build\nmodel: opus\n---\nb\n")
        write(os.path.join(self.plugin, "lib", "kit_only.py"), "K = 1\n")
        os.symlink("../../../lib/relay_x.py", os.path.join(self.plugin, "lib", "relay_x.py"))

    def candidate(self, shared: str) -> str:
        """What a candidate holds: real files (copytree's default), the shared module with the text `shared`."""
        folder = os.path.join(self.tmp, "cand", "delegate")
        write(os.path.join(folder, "lib", "relay_x.py"), shared)
        write(os.path.join(folder, "lib", "kit_only.py"), "K = 2\n")
        return folder


class TestBenchCopy(Repo):
    def test_the_plugin_copy_for_a_run_holds_real_files_not_dangling_links(self) -> None:
        # pass case 6: a relative link copied alone into a scratch folder points nowhere; the copy must hold the content
        profile = {"profile": {"name": "t"}, "models": {}, "effort": {}}
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        copy = relay_bench.plugin_for_run(profile, self.plugin, out)
        moved = os.path.join(copy, "lib", "relay_x.py")
        self.assertFalse(os.path.islink(moved))
        self.assertEqual(read(moved), "X = 1\n")


class TestAdoptLib(Repo):
    def test_a_candidate_equal_to_the_source_is_adopted_and_lib_is_untouched(self) -> None:
        cand = self.candidate("X = 1\n")
        self.assertEqual(relay_bench.lib_adoption_conflicts(cand, self.plugin), [])
        relay_bench.adopt_lib(os.path.join(cand, "lib"), os.path.join(self.plugin, "lib"))
        self.assertTrue(os.path.islink(os.path.join(self.plugin, "lib", "relay_x.py")))      # still a link
        self.assertEqual(read(os.path.join(self.tmp, "lib", "relay_x.py")), "X = 1\n")        # the source is unchanged
        self.assertEqual(read(os.path.join(self.plugin, "lib", "kit_only.py")), "K = 2\n")    # a plugin-only file is adopted

    def test_a_candidate_that_edited_a_shared_module_is_refused_by_name(self) -> None:
        cand = self.candidate("X = 99\n")
        found = relay_bench.lib_adoption_conflicts(cand, self.plugin)
        self.assertEqual(len(found), 1)
        self.assertIn("lib/relay_x.py", found[0])
        self.assertIn("port that edit to lib/", found[0])
        # nothing was written by asking
        self.assertEqual(read(os.path.join(self.tmp, "lib", "relay_x.py")), "X = 1\n")
        self.assertEqual(read(os.path.join(self.plugin, "lib", "kit_only.py")), "K = 1\n")


if __name__ == "__main__":
    unittest.main()
