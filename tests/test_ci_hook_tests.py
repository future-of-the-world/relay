"""bin/ci's hook-test step: the tools it needs, and the live session test (tests/hooks_live.py), left for the full run. The hook suites
themselves are tests/test_hook_*.py, run with the library tests. Free; no model call.
Each case copies bin/ci into a temporary tree holding a stub hooks_live.py and reads that run's hook-tests log."""
import os, shutil, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_tools import install_fake  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def copy_gate(tree):
    """bin/ci is a wrapper of lib/relay_ci.py: both go into the temporary tree."""
    for rel in (("bin", "ci"), ("lib", "relay_ci.py"), ("lib", "relay_ci_lines.py"), ("lib", "relay_ci_python.py"), ("lib", "relay_ci_probe.py")):
        os.makedirs(os.path.join(tree, rel[0]), exist_ok=True)
        shutil.copy(os.path.join(ROOT, *rel), os.path.join(tree, *rel))
    shutil.copy(os.path.join(ROOT, "deps.toml"), os.path.join(tree, "deps.toml"))   # bin/ci reads the python pin from it
    # the fast "types and lint" step runs first and ends a red gate: a stub that passes keeps these trees reaching the step under test
    stub = os.path.join(tree, "bin", "types-lint")
    with open(stub, "w") as handle:
        handle.write("#!/bin/sh\nexit 0\n")
    os.chmod(stub, 0o755)


def run_ci(args, drop=(), env_extra=None):
    tmp = tempfile.mkdtemp()
    try:
        copy_gate(tmp)
        d = os.path.join(tmp, "tests"); os.makedirs(d)
        with open(os.path.join(d, "hooks_live.py"), "w") as f:
            f.write("print('STUB-RAN hooks-live')\n")
        env = dict(os.environ); env.pop("RELAY_GATE", None); env.pop("RELAY_INERT_FULL_HOOKS", None); env.update(env_extra or {})
        if drop:  # hide tools by shadowing them with a PATH that lacks their directories' copies
            bindir = os.path.join(tmp, "fakebin"); os.makedirs(bindir)
            for tool in ("bash", "env", "dirname", "mkdir", "date", "cat", "grep", "head", "sed", "python3", "git", "jq", "claude", "bun", "cmp", "rm", "sort", "diff", "mktemp"):
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
    def test_quick_leaves_hooks_live_for_the_full_run_and_says_so(self):
        _, log = run_ci(["--quick"])
        self.assertNotIn("STUB-RAN hooks-live", log)
        self.assertIn("hooks_live.py (left for the full bin/ci", log)

    def test_missing_bun_fails_naming_the_tool(self):
        _, log = run_ci(["--quick"], drop=("bun",))
        self.assertIn("FAIL hook tests need bun on PATH: curl -fsSL https://bun.sh/install", log)
        self.assertNotIn("STUB-RAN", log)

    def test_full_without_claude_fails_hooks_live(self):
        # a full run makes no model call without claude on PATH (evals and validate are skipped too)
        _, log = run_ci([], drop=("claude",))
        self.assertIn("FAIL tests/hooks_live.py needs claude on PATH", log)
        self.assertNotIn("STUB-RAN hooks-live", log)

    def test_the_inert_probes_nested_quick_run_never_runs_hooks_live(self):
        _, log = run_ci(["--quick"], env_extra={"RELAY_INERT_FULL_HOOKS": "1"})
        self.assertNotIn("STUB-RAN hooks-live", log)
        self.assertIn("hooks_live.py (left for the full bin/ci", log)

    def test_full_gate_runs_hooks_live_once_and_the_inert_comparison_ignores_its_ok_lines(self):
        # Under RELAY_GATE the full run runs the (stub) hooks-live, which prints an "ok" line; the nested quick run does not.
        # The inert step must still say "the same results". Fake claude (exit 0) so the full run reaches the inert step.
        tmp = tempfile.mkdtemp()
        try:
            fake = os.path.join(tmp, "fake"); os.makedirs(fake)
            install_fake(os.path.join(fake, "claude"), "#!/bin/sh\nexit 0\n")
            tree = os.path.join(tmp, "tree"); os.makedirs(tree)
            copy_gate(tree)
            d = os.path.join(tree, "tests"); os.makedirs(d)
            with open(os.path.join(d, "hooks_live.py"), "w") as f:
                f.write("print('STUB-RAN hooks-live')\nprint('ok    live case')\n")
            g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
            for c in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "x"]):
                subprocess.run(g[:5] + c if c[0] == "commit" else ["git"] + c, cwd=tree, check=True, capture_output=True)
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tree, check=True, capture_output=True, text=True).stdout.strip()
            env = dict(os.environ, RELAY_GATE=head, PATH=fake + os.pathsep + os.environ["PATH"]); env.pop("RELAY_INERT_FULL_HOOKS", None)
            subprocess.run(["bash", "bin/ci"], cwd=tree, env=env, capture_output=True, text=True)
            with open(os.path.join(tree, ".ci", "steps", "hook-tests.log")) as f:
                self.assertEqual(f.read().count("STUB-RAN hooks-live"), 1)
            with open(os.path.join(tree, ".ci", "steps", "inert.log")) as f:
                self.assertIn("inert: the same results", f.read())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
