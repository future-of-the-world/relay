"""guard-main's rule on .relay/checks (lib/kit_guard.py): inline code that only names the folder is not a write."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "relay", "lib"))
import kit_guard  # noqa: E402


def kinds(cmd: str) -> list[str]:
    with tempfile.TemporaryDirectory() as d:
        return [row[0] for row in kit_guard.analyze(cmd, os.path.realpath(d), [])]


class ChecksInline(unittest.TestCase):
    def test_script_that_prints_the_folder_name_is_allowed(self) -> None:
        # the 25 Oct case: reads the queue, prints ".relay/checks writes"; "writes" is text, not a call
        cmd = "python3 -c \"import glob; print('.relay/checks writes', glob.glob('.relay/queue/*.json'))\""
        self.assertNotIn("X", kinds(cmd))

    def test_redirect_into_checks_is_refused(self) -> None:
        self.assertIn("X", kinds("echo x > .relay/checks/a.json"))

    def test_cp_into_checks_is_refused(self) -> None:
        self.assertIn("X", kinds("cp f .relay/checks/"))

    def test_python_open_for_writing_is_refused(self) -> None:
        self.assertIn("X", kinds("python3 -c \"open('.relay/checks/a.json', 'w').write('x')\""))

    def test_python_write_text_is_refused(self) -> None:
        self.assertIn("X", kinds("python3 -c \"import pathlib; pathlib.Path('.relay/checks/a').write_text('x')\""))

    def test_node_unlinkSync_is_refused(self) -> None:
        self.assertIn("X", kinds("node -e \"require('fs').unlinkSync('.relay/checks/a')\""))

    def test_node_renameSync_is_refused(self) -> None:
        self.assertIn("X", kinds("node -e \"require('fs').renameSync('a','.relay/checks/a')\""))

    def test_perl_unlink_without_parentheses_is_refused(self) -> None:
        self.assertIn("X", kinds("perl -e \"unlink '.relay/checks/a'\""))

    def test_node_unlinkSync_on_a_queue_item_is_refused(self) -> None:
        self.assertIn("Y", kinds("node -e \"require('fs').unlinkSync('.relay/queue/x.json')\""))


if __name__ == "__main__":
    unittest.main()
