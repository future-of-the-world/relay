"""The clean-image fixes: the sync tests run the working tree's code, and the image sets no git identity."""
import contextlib
import io
import os
import subprocess
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import test_paid_batch  # noqa: E402
import tempfile  # noqa: E402
import relay_ci  # noqa: E402
import test_ci_python  # noqa: E402


class SyncTestRunsTheWorkingTree(unittest.TestCase):
    def test_run_sync_runs_this_checkouts_bin_relay_and_clones_nothing(self):
        # an uncommitted edit to bin/relay or bin/paid-cost must be what the test runs: no clone of HEAD
        calls: list[list[str]] = []
        real = subprocess.run

        def spy(cmd, *a, **kw):
            calls.append(list(cmd))
            return real(cmd, *a, **kw)

        case = test_paid_batch.SyncWaits("test_sync_dry_still_prints_its_plan")
        with mock.patch.object(test_paid_batch.subprocess, "run", spy):
            case.run_sync("--dry")
        self.assertFalse([c for c in calls if "clone" in c], calls)
        ran = [c for c in calls if len(c) > 1 and c[1].endswith(os.path.join("bin", "relay"))]
        self.assertEqual([c[1] for c in ran], [os.path.join(ROOT, "bin", "relay")])

    def test_run_sync_leaves_no_master_it_made(self):
        # a detached clone has no master: the test makes one for its run and removes it after
        case = test_paid_batch.SyncWaits("test_sync_dry_still_prints_its_plan")
        before = subprocess.run(["git", "-C", ROOT, "rev-parse", "--verify", "-q", "refs/heads/master"], capture_output=True).returncode
        case.run_sync("--dry")
        case.doCleanups()
        after = subprocess.run(["git", "-C", ROOT, "rev-parse", "--verify", "-q", "refs/heads/master"], capture_output=True).returncode
        self.assertEqual(before, after)


class PaidRunBuildsTheCleanImageGate(unittest.TestCase):
    """F1: the full gate (the paid run) runs the Containerfile recipe through podman and is red when it is."""
    STEP = "clean image quick gate (podman, about 20 min)"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)

    def ci(self, runner: test_ci_python.Recorder, tools: list[str]) -> relay_ci.Ci:
        path = test_ci_python.stubs(os.path.join(self.root, "stub"), tools)
        ci = relay_ci.Ci(self.root, False, env={"PATH": path}, runner=runner)
        ci.prepare()
        return ci

    def answers(self, run_code: int):
        # by hand: `git rev-parse HEAD` answers the head; the `podman run` is the recipe's last command and answers run_code
        def answer(argv: list[str]):
            if argv[:2] == ["git", "rev-parse"]:
                return 0, "abc123\n"
            return (run_code, "") if argv[:2] == ["podman", "run"] else (0, "")
        return answer

    def test_the_step_runs_the_recipe_in_order_with_podman_only(self) -> None:
        rec = test_ci_python.Recorder(self.answers(0))
        ci = self.ci(rec, ["podman", "git"])
        with open(os.path.join(self.root, "log"), "w") as log:
            self.assertEqual(ci.clean_image(log), 0)
        words = [" ".join(c[:2]) for c in rec.calls]
        self.assertEqual(words, ["git rev-parse", "podman build", "git clone", "git -C", "podman run"])
        self.assertFalse([c for c in rec.calls if "docker" in c[0]])
        self.assertIn("bin/ci --quick", rec.calls[-1][-1])
        self.assertIn("--no-hardlinks", rec.calls[2])

    def test_a_red_gate_in_the_image_makes_the_step_red_and_stops_before_the_paid_evals(self) -> None:
        rec = test_ci_python.Recorder(self.answers(1))
        ci = self.ci(rec, ["podman", "git", "claude"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.run_full(ci), 1)
        self.assertIn("ci: %s FAILED" % self.STEP, out.getvalue())
        self.assertIn("the paid evals were not started", out.getvalue())
        self.assertEqual(rec.find("claude"), [])

    def test_a_green_gate_in_the_image_shows_its_time_in_the_step_line_and_the_evals_go_on(self) -> None:
        rec = test_ci_python.Recorder(self.answers(0))
        ci = self.ci(rec, ["podman", "git", "claude"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.run_full(ci), 0)
        self.assertRegex(out.getvalue(), r"ci: clean image quick gate \(podman, about 20 min\) ok \(\d+s\)")
        self.assertEqual(self.evals_started, [True])

    def test_no_podman_is_red_never_a_pass(self) -> None:
        ci = self.ci(test_ci_python.Recorder(self.answers(0)), ["git"])
        with open(os.path.join(self.root, "log"), "w") as log:
            self.assertNotEqual(ci.clean_image(log), 0)
        self.assertIn("podman is not on PATH", open(os.path.join(self.root, "log")).read())

    def run_full(self, ci: relay_ci.Ci) -> int:
        """The full gate with the other steps replaced by do-nothings; the paid evals are a flag."""
        self.evals_started: list[bool] = []
        for attr in ("lib_tests", "types_lint", "hook_tests", "lib_links", "grader_tests", "validate_all"):
            setattr(ci, attr, lambda log: 0)
        ci.plugin_evals = lambda: self.evals_started.append(True)    # type: ignore[method-assign,assignment]
        ci.record = lambda: None                                      # type: ignore[method-assign]
        return ci.main()


class ImageHasNoGitIdentity(unittest.TestCase):
    def test_containerfile_sets_no_author_variable(self):
        # each test gives its own git calls an identity; the image must not hide one that does not
        text = open(os.path.join(ROOT, "container", "Containerfile"), encoding="utf-8").read()
        self.assertNotIn("GIT_AUTHOR", text)
        self.assertNotIn("GIT_COMMITTER", text)


if __name__ == "__main__":
    unittest.main()
