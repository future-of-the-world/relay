"""Scaffolding for per-command modules: the command list helper, its floor, the harness, and the one-test-file-per-module rule."""
import os
import tempfile
import unittest

import relay_commands
from cmd_harness import run_relay


def make(root: str, *relative: str) -> None:
    for rel in relative:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("")


class CommandList(unittest.TestCase):
    def test_floor_is_a_superset_of_todays_names(self) -> None:
        # the 21 names are written out here, not taken from the helper's FLOOR
        today = {"status", "report", "calibrate", "improve", "bench", "candidate", "profile", "sync", "setup", "install", "migrate",
                 "doctor", "flows", "rules", "changed", "gate", "land", "precheck", "check", "queue", "license"}
        self.assertEqual(len(today), 21)
        self.assertEqual(relay_commands.FLOOR, today)
        self.assertLessEqual(today, set(relay_commands.names()))

    def test_walk_adds_a_module_to_the_table(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            make(root, "bin/relay", "lib/relay_cmd/hello.py", "lib/relay_cmd/Bad-Name.py", "lib/relay_cmd/__init__.py",
                 "lib/relay_cmd/queue/__init__.py", "lib/relay_cmd/queue/add.py", "lib/relay_cmd/nopkg/readme.py")
            with open(os.path.join(root, "bin", "relay"), "w", encoding="utf-8") as handle:
                handle.write('"""relay queue [show|count] x"""\nCOMMANDS = {"status": None}\nQUEUE_WRITES = ("take",)\n')
            # hello (file) and queue (package) are found; Bad-Name fails the name rule; nopkg has no __init__.py; status is from the table
            self.assertEqual(relay_commands.names(root), ["hello", "queue", "status"])
            # queue words: module add, QUEUE_WRITES take, usage show|count
            self.assertEqual(relay_commands.queue_words(root), {"add", "take", "show", "count"})

    def test_a_command_missing_from_both_walk_and_table_is_not_listed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            make(root, "bin/relay")
            with open(os.path.join(root, "bin", "relay"), "w", encoding="utf-8") as handle:
                handle.write('COMMANDS = {"status": None}\n')
            self.assertFalse(relay_commands.FLOOR <= set(relay_commands.names(root)))  # what the help test's floor check catches

    def test_queue_words_follow_the_usage_into_a_command_module(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            make(root, "bin/relay", "lib/relay_cmd/queue/__init__.py")
            with open(os.path.join(root, "bin", "relay"), "w", encoding="utf-8") as handle:
                handle.write("COMMANDS = {}\n")
            with open(os.path.join(root, "lib", "relay_cmd", "queue", "__init__.py"), "w", encoding="utf-8") as handle:
                handle.write('USAGE = "relay queue [count|purge]"\n')
            # the usage lives only in the module: its words are still found
            self.assertEqual(relay_commands.queue_words(root), {"count", "purge"})

    def test_queue_floor_is_todays_fifteen_words(self) -> None:
        today = {"count", "show", "history", "check", "migrate", "land", "ip", "take", "release", "done", "drop", "add", "note",
                 "edit", "start"}
        self.assertEqual(len(today), 15)
        self.assertEqual(relay_commands.QUEUE_FLOOR, today)
        self.assertLessEqual(today, relay_commands.queue_words())

    def test_a_tree_without_the_usage_falls_below_the_queue_floor(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            make(root, "bin/relay")
            with open(os.path.join(root, "bin", "relay"), "w", encoding="utf-8") as handle:
                handle.write("COMMANDS = {}\n")
            self.assertFalse(relay_commands.QUEUE_FLOOR <= relay_commands.queue_words(root))

    def test_live_names_and_queue_words(self) -> None:
        self.assertTrue(relay_commands.FLOOR <= set(relay_commands.names()))
        self.assertLessEqual({"add", "show", "take", "count"}, relay_commands.queue_words())


class Harness(unittest.TestCase):
    def test_harness_returns_code_stdout_and_files(self) -> None:
        ran = run_relay(["land"])  # no branch: the usage refusal, exit 2, nothing written
        self.assertEqual(ran.code, 2)
        self.assertIn("relay land <branch>", ran.stderr)
        self.assertEqual(ran.written, [])
        ran = run_relay(["status"])
        self.assertEqual(ran.code, 0)
        self.assertIn("No ledger events", ran.stdout)


class EveryModuleHasATestFile(unittest.TestCase):
    def test_every_module_in_the_walk_has_its_test_file(self) -> None:
        self.assertEqual(relay_commands.missing_test_files(), [], "add the named test file(s) in tests/")

    def test_a_fake_module_without_a_test_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as tests:
            make(root, "lib/relay_cmd/hello.py", "lib/relay_cmd/queue/__init__.py", "lib/relay_cmd/queue/add.py")
            make(tests, "test_cmd_queue_add.py")
            # hello has no test_cmd_hello.py; the queue package is covered by its action file
            self.assertEqual(relay_commands.missing_test_files(root, tests), ["test_cmd_hello.py"])
            make(tests, "test_cmd_hello.py")
            self.assertEqual(relay_commands.missing_test_files(root, tests), [])


if __name__ == "__main__":
    unittest.main()
