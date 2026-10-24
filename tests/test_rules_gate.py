"""A change that only edits rules/*.md gets the short rules gate in `bin/ci --quick`; one with code gets the full quick gate.
Free: each case builds a temporary repository holding a copy of bin/ci and lib/ and reads which steps the run recorded."""
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_textonly  # noqa: E402

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd: str, *args: str) -> None:
    done = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    assert done.returncode == 0, done.stderr


def steps_run(changed: dict[str, str], dirty: dict[str, str] | None = None) -> list[str]:
    """Build a repository on master with bin/ci and lib/, commit `changed` (path: text) on a branch, run bin/ci --quick on it;
    return the steps it recorded in .ci/results.txt."""
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "bin"))
        shutil.copy(os.path.join(ROOT, "bin", "ci"), os.path.join(tmp, "bin", "ci"))
        shutil.copy(os.path.join(ROOT, ".gitignore"), os.path.join(tmp, ".gitignore"))  # keeps .ci/ and __pycache__ out of the status
        shutil.copytree(os.path.join(ROOT, "lib"), os.path.join(tmp, "lib"), ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(os.path.join(tmp, "rules"))
        with open(os.path.join(tmp, "rules", "old.md"), "w") as f:
            f.write("old\n")
        git(tmp, "init", "-q", "-b", "master")
        git(tmp, "add", "-A")
        git(tmp, "commit", "-q", "-m", "base")
        git(tmp, "checkout", "-q", "-b", "wt/task")
        for rel, text in changed.items():
            os.makedirs(os.path.dirname(os.path.join(tmp, rel)), exist_ok=True)
            with open(os.path.join(tmp, rel), "w") as f:
                f.write(text)
        git(tmp, "add", "-A")
        git(tmp, "commit", "-q", "-m", "change")
        for rel, text in (dirty or {}).items():  # uncommitted edits, left in the worktree
            os.makedirs(os.path.dirname(os.path.join(tmp, rel)), exist_ok=True)
            with open(os.path.join(tmp, rel), "w") as f:
                f.write(text)
        env = {k: v for k, v in os.environ.items() if k not in ("RELAY_GATE", "RELAY_INERT_FULL_HOOKS")}
        subprocess.run(["bash", "bin/ci", "--quick"], cwd=tmp, env=env, capture_output=True, text=True)
        with open(os.path.join(tmp, ".ci", "results.txt")) as f:
            return [line.rsplit(" ", 1)[0] for line in f.read().splitlines()]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class RulesGate(unittest.TestCase):
    def test_a_rules_only_change_runs_the_short_gate(self) -> None:
        # Q1: rules/*.md alone is on the text-only list, so the quick gate is the one rules step, not the library tests and the rest.
        self.assertEqual(steps_run({"rules/old.md": "new\n", "rules/added.md": "x\n"}), ["rules text tests"])

    def test_a_change_with_code_runs_the_full_quick_gate(self) -> None:
        # lib/ is not on the list: the first full step, library tests, runs and the rules step does not.
        steps = steps_run({"lib/relay_new.py": "x = 1\n"})
        self.assertIn("library tests", steps)
        self.assertNotIn("rules text tests", steps)

    def test_rules_plus_code_runs_the_full_quick_gate(self) -> None:
        steps = steps_run({"rules/old.md": "new\n", "bin/tool": "echo hi\n"})
        self.assertIn("library tests", steps)
        self.assertNotIn("rules text tests", steps)

    def test_the_list_is_fixed_paths(self) -> None:
        self.assertTrue(relay_textonly.only(["rules/git.md"]))
        self.assertFalse(relay_textonly.only([]))
        for path in ("rules/sub/git.md", "rules/git.py", "plugins/core/hooks/x.md", "bin/ci", "docs/handover.md"):
            self.assertFalse(relay_textonly.matches(path), path)

    def test_an_uncommitted_code_edit_runs_the_full_quick_gate(self) -> None:
        # F2 pass 1: commits touch only rules, but lib/relay_rules.py is edited and not committed.
        steps = steps_run({"rules/old.md": "new\n"}, dirty={"lib/relay_rules.py": "# edited\n"})
        self.assertIn("library tests", steps)
        self.assertNotIn("rules text tests", steps)

    def test_a_clean_tree_keeps_the_short_gate(self) -> None:
        # F2 pass 2.
        self.assertEqual(steps_run({"rules/old.md": "new\n"}), ["rules text tests"])

    def test_an_uncommitted_inert_edit_keeps_the_short_gate(self) -> None:
        # F2 pass 3: docs/handover.md is inert.
        self.assertEqual(steps_run({"rules/old.md": "new\n"}, dirty={"docs/handover.md": "x\n"}), ["rules text tests"])


def _covered(module: str, cls: str) -> bool:
    names = relay_textonly.RULE_TESTS
    return f"tests.{module}" in names or f"tests.{module}.{cls}" in names


class RuleTestsComplete(unittest.TestCase):
    # F1: the short gate runs only RULE_TESTS, so every test class that reads the rules folder must be on it.
    READS_RULES = re.compile(r"""os\.path\.join\(ROOT, "rules"|rules/[\w*-]+\.md|relay_rules\.(?:rules|render_target|sync)\(|relay_bench\.make_workspace""")

    def test_every_test_class_reading_rules_is_listed(self) -> None:
        missing = []
        tests_dir = os.path.join(ROOT, "tests")
        for fname in sorted(os.listdir(tests_dir)):
            if not fname.endswith(".py") or fname == "test_rules_gate.py":
                continue
            module = fname[:-3]
            with open(os.path.join(tests_dir, fname)) as f:
                source = f.read()
            for node in ast.parse(source).body:
                if isinstance(node, ast.ClassDef) and self.READS_RULES.search(ast.get_source_segment(source, node) or ""):
                    if not _covered(module, node.name):
                        missing.append(f"tests.{module}.{node.name}")
        self.assertEqual(missing, [])

    def test_the_classes_the_review_named_are_listed(self) -> None:
        for name in ("tests.test_relay.TestPrinciplesRule", "tests.test_relay.AutoMergeTextsTest",
                     "tests.test_bench_worker", "tests.test_paid_batch"):
            self.assertIn(name, relay_textonly.RULE_TESTS)

    def test_the_guard_flags_an_unlisted_class(self) -> None:
        self.assertFalse(_covered("test_new", "Reader"))
        self.assertTrue(_covered("test_python_rule", "Anything"))


if __name__ == "__main__":
    unittest.main()
