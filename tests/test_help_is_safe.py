"""`relay <cmd> --help` prints usage and writes nothing (queue item relay-cmd-help-runs-the-command-instead-of-help)."""
import os
import subprocess
import sys
import tempfile
import unittest

import relay_commands

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RELAY = os.path.join(ROOT, "bin", "relay")


def snapshot(top: str) -> list[str]:
    found = []
    for base, dirs, files in os.walk(top):
        found += [os.path.relpath(os.path.join(base, n), top) for n in dirs + files]
    return sorted(found)


def run_help(cmd: list[str]) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run relay with --help in a temporary home and working folder; return the result and what appeared there."""
    with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as root:
        env = {**os.environ, "HOME": home, "RELAY_HOME": os.path.join(home, ".relay"), "RELAY_ROOT": root}
        done = subprocess.run([sys.executable, RELAY, *cmd], cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
        return done, snapshot(home) + ["cwd:" + n for n in snapshot(cwd)] + ["root:" + n for n in snapshot(root)]


def command_names() -> list[str]:
    return relay_commands.names()


def defines_wants_help() -> object:
    """The module that defines wants_help: bin/relay now, lib/relay_cli.py once it moves there (move 4)."""
    relay = relay_commands.load_relay()
    if hasattr(relay, "wants_help"):
        return relay
    import importlib
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    try:
        return importlib.import_module("relay_cli")
    finally:
        sys.path.remove(os.path.join(ROOT, "lib"))


class HelpIsSafe(unittest.TestCase):
    def test_candidate_help_creates_no_profile(self) -> None:
        # the failing case: `relay candidate --help` used to create a profile named '--help'
        done, written = run_help(["candidate", "--help"])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(written, [])
        self.assertIn("relay candidate", done.stdout)

    def test_install_and_calibrate_help_write_nothing(self) -> None:
        for cmd in ("install", "calibrate"):
            done, written = run_help([cmd, "--help"])
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(written, [], cmd)
            self.assertIn("relay " + cmd, done.stdout)

    def test_every_command_in_the_table_writes_nothing(self) -> None:
        names = command_names()
        # the floor: today's 21 names must all be listed, whether from the walk or the table (no exact count)
        self.assertLessEqual(relay_commands.FLOOR, set(names))
        for name in names:
            for flag in ("--help", "-h"):
                done, written = run_help([name, flag])
                self.assertEqual(done.returncode, 0, f"{name} {flag}: {done.stderr}")
                self.assertEqual(written, [], f"{name} {flag}")
                self.assertTrue(done.stdout.strip(), name)

    def test_help_after_a_queue_action_and_after_other_args(self) -> None:
        for cmd in (["queue", "add", "--help"], ["gate", "-C", ".", "--help"], ["queue", "note", "x", "-h"]):
            done, written = run_help(cmd)
            self.assertEqual(done.returncode, 0, f"{cmd}: {done.stderr}")
            self.assertEqual(written, [], cmd)

    def test_help_after_bare_double_dash_is_not_relay_help(self) -> None:
        module = defines_wants_help()
        self.assertFalse(module.wants_help(["-C", ".", "--", "--help"]))
        self.assertTrue(module.wants_help(["-C", ".", "--help"]))
        self.assertTrue(module.wants_help(["--help", "--", "x"]))

    def test_top_level_help_exits_0_and_no_command_exits_2(self) -> None:
        for args in (["--help"], ["-h"], ["help"]):
            done, _ = run_help(args)
            self.assertEqual(done.returncode, 0, args)
            self.assertTrue(done.stdout.strip(), args)
        done, _ = run_help([])
        self.assertEqual(done.returncode, 2)
        self.assertTrue(done.stdout.strip())


if __name__ == "__main__":
    unittest.main()
