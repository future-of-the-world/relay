"""tests/hooks_live.py keeps each session's stream-json output when a case fails. Free: a fake `claude` answers."""
import os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "tests", "hooks_live.py")

# The fake emits a hook event that holds every codeword (as the real hooks do), then a result line.
# `broken` makes the agent session answer NONE; the other sessions answer correctly.
FAKE = r'''#!/usr/bin/env bash
for last; do :; done
if [ -n "${ARGLOG:-}" ]; then echo "$@" >> "$ARGLOG"; fi
if [ "${CRASH:-0}" = 1 ]; then echo "Error: not logged in"; exit 1; fi
echo '{"type":"system","subtype":"hook_response","output":"OTTER-77 BADGER-31 guard-main"}'
case "$last" in
  */openspec:archive*) r="OTTER-77";;
  *openspec:author*) if [ "${BROKEN:-0}" = 1 ]; then r="NONE"; else r="BADGER-31"; fi;;
  *echo\ probe*) case "$PWD" in */.worktrees/w) echo probe > guard-probe.txt; r="DONE";; *) r="guard-main";; esac;;
esac
printf '{"duration_api_ms":1,"type":"result","result":"%s"}\n' "$r"
'''


def run_script(broken: bool, crash: bool = False, arglog: str = "") -> tuple[subprocess.CompletedProcess, str]:
    with tempfile.TemporaryDirectory() as d:
        bindir = os.path.join(d, "bin"); os.makedirs(bindir)
        claude = os.path.join(bindir, "claude")
        with open(claude, "w") as f:
            f.write(FAKE)
        os.chmod(claude, 0o755)
        tmpdir = os.path.join(d, "tmp"); os.makedirs(tmpdir)
        env = dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"], TMPDIR=tmpdir, BROKEN="1" if broken else "0", CRASH="1" if crash else "0", ARGLOG=arglog)
        env.pop("HOOKS_LIVE", None)
        r = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True, env=env, timeout=60)
        kept = sorted(os.listdir(tmpdir))
        kept_files: list[str] = []
        for name in kept:
            p = os.path.join(tmpdir, name)
            if name.startswith("hooks-live-") and os.path.isdir(p):
                kept_files = sorted(os.listdir(p))
                assert p in r.stdout, r.stdout  # the printed path is the real folder
        return r, ",".join(kept_files)


class HooksLiveKeepsOutput(unittest.TestCase):
    def test_failure_keeps_the_four_outputs_and_prints_where(self) -> None:
        r, kept = run_script(broken=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        # The agent case fails; the hook event holds BADGER-31 but only the result line counts.
        self.assertIn("FAIL  openspec:author", r.stdout)
        self.assertEqual(kept, "agent.out,control.out,guard.out,stage.out")

    def test_no_result_line_shows_the_raw_output(self) -> None:
        # F2: a session that crashes writes no result line; the FAIL line must show its text.
        r, kept = run_script(broken=False, crash=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("FAIL  openspec:author", r.stdout)
        self.assertRegex(r.stdout, r"FAIL  .*: Error: not logged in")
        self.assertEqual(kept, "agent.out,control.out,guard.out,stage.out")

    def test_sessions_ignore_user_level_settings(self) -> None:
        # F1: every session is started with --setting-sources project,local.
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "args")
            r, _ = run_script(broken=False, arglog=log)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            lines = open(log).read().splitlines()
            self.assertEqual(len(lines), 4)
            for line in lines:
                self.assertIn("--setting-sources project,local", line)

    def test_success_keeps_nothing(self) -> None:
        r, kept = run_script(broken=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(kept, "")


if __name__ == "__main__":
    unittest.main()
