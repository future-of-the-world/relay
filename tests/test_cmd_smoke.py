"""One smoke case per relay command: harmless arguments, the exit code and one output line (the harness convention).
A command that cannot run in a temporary tree is checked by its refusal. Each case also catches an argument passed off by one."""
import unittest

import relay_commands
from cmd_harness import run_relay

# command: (args, git repository?, exit code, stream, a piece of one line)
SMOKE = {
    "status": (["status"], False, 0, "stdout", "No ledger events in the last 12 hours"),
    "report": (["report"], False, 0, "stdout", "No sessions found in that period"),
    "calibrate": (["calibrate"], False, 1, "stderr", "relay calibrate: [Errno 2]"),
    "improve": (["improve", "log"], False, 0, "stdout", "No adoptions yet."),
    "bench": (["bench"], False, 2, "stderr", "relay bench <profileA>"),
    "candidate": (["candidate"], False, 2, "stderr", "relay candidate <name>"),
    "profile": (["profile", "nosuch"], False, 1, "stderr", "no profile 'nosuch'"),
    "sync": (["sync"], False, 1, "stderr", "relay sync: waits for a green paid run"),
    "setup": (["setup", "--bogus"], False, 2, "stderr", "unknown flag --bogus"),
    "install": (["install", "--bogus"], False, 1, "stderr", "relay install: [Errno 2]"),
    "migrate": (["migrate", "--bogus"], False, 2, "stderr", "unknown flag --bogus"),
    "doctor": (["doctor"], False, 1, "stderr", "relay doctor: "),
    "flows": (["flows"], False, 1, "stderr", "relay flows: [Errno 2]"),
    "rules": (["rules"], False, 1, "stderr", "relay rules: [Errno 2]"),
    "changed": (["changed"], False, 2, "stderr", "relay changed [-C <repo>] [--own] [--archive] <sha> [<until>]"),
    "gate": (["gate"], True, 1, "stderr", "the default branch has no .relay/ folder"),
    "land": (["land"], False, 2, "stderr", "relay land <branch>"),
    "precheck": (["precheck"], False, 1, "stdout", "skip types and lint"),
    "check": (["check"], False, 2, "stderr", "relay check show"),
    "queue": (["queue"], False, 2, "stderr", "relay queue: not a git repository"),
    "license": (["license"], False, 2, "stderr", "relay license add"),
}


class Smoke(unittest.TestCase):
    def test_every_floor_command_has_a_smoke_case(self) -> None:
        self.assertEqual(set(SMOKE), set(relay_commands.FLOOR))

    def test_each_command_smoke(self) -> None:
        for name, (args, git, code, stream, piece) in sorted(SMOKE.items()):
            ran = run_relay(args, git=git)
            self.assertEqual(ran.code, code, f"{name}: {ran.stderr}")
            self.assertIn(piece, getattr(ran, stream), name)


if __name__ == "__main__":
    unittest.main()
