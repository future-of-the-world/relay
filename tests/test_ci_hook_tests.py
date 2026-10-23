"""bin/ci's hook-test step: which plugin test files it runs in quick mode. Free; no model call.
Each case copies bin/ci into a temporary tree holding stub test files and reads that run's hook-tests log."""
import os, shutil, subprocess, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUBS = ["inject-addition", "packet", "check-contract", "shim", "spec-check", "hooks-live"]


def run_ci(args, drop=()):
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "bin")); shutil.copy(os.path.join(ROOT, "bin", "ci"), os.path.join(tmp, "bin", "ci"))
        d = os.path.join(tmp, "plugins", "core", "tests"); os.makedirs(d)
        for n in STUBS:
            with open(os.path.join(d, n + ".test.sh"), "w") as f:
                f.write("echo STUB-RAN %s\n" % n)
        env = dict(os.environ); env.pop("RELAY_GATE", None); env.pop("RELAY_INERT_FULL_HOOKS", None)
        if drop:  # hide tools by shadowing them with a PATH that lacks their directories' copies
            bindir = os.path.join(tmp, "fakebin"); os.makedirs(bindir)
            for tool in ("bash", "env", "dirname", "mkdir", "date", "cat", "grep", "head", "sed", "python3", "git", "jq", "node", "claude", "bun", "cmp", "rm", "sort", "diff", "mktemp"):
                if tool in drop: continue
                p = shutil.which(tool)
                if p: os.symlink(p, os.path.join(bindir, tool))
            env["PATH"] = bindir
        p = subprocess.run([shutil.which("bash") if not drop else "/bin/bash", "bin/ci"] + args, cwd=tmp, env=env, capture_output=True, text=True)
        with open(os.path.join(tmp, ".ci", "steps", "hook-tests.log")) as f:
            log = f.read()
        return p, log
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class HookTestsStep(unittest.TestCase):
    def test_quick_runs_the_free_core_tests(self):
        _, log = run_ci(["--quick"])
        for n in STUBS[:-1]:
            self.assertIn("STUB-RAN " + n, log)  # inject-addition among them: a role-injection regression must fail the quick gate
        self.assertNotIn("skipped", log)

    def test_quick_leaves_hooks_live_for_the_full_run_and_says_so(self):
        _, log = run_ci(["--quick"])
        self.assertNotIn("STUB-RAN hooks-live", log)
        self.assertIn("hooks-live.test.sh (left for the full bin/ci", log)

    def test_missing_bun_fails_naming_the_tool(self):
        _, log = run_ci(["--quick"], drop=("bun",))
        self.assertIn("FAIL hook tests need bun on PATH: curl -fsSL https://bun.sh/install", log)
        self.assertNotIn("STUB-RAN", log)


if __name__ == "__main__":
    unittest.main()
