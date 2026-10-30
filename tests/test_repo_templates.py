"""The template repositories of the git-heavy tests: a case's repository is a copy of a folder, made with no git call."""
import os
import subprocess
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
sys.path.insert(0, HERE)

import repo_templates  # noqa: E402
import test_queue as tq  # noqa: E402
import tmp_default  # noqa: E402


class TestTemplateCopy(tq.Base):
    def test_a_second_repo_with_the_same_key_starts_no_git_and_is_independent(self):
        first = self.repo("first", seed={"a.txt": "a\n"})          # builds the template if no earlier test has
        head = tq.git(first, "rev-parse", "HEAD")
        started = []
        real = subprocess.Popen

        def counting(*args, **kwargs):
            started.append(args[0] if args else kwargs.get("args"))
            return real(*args, **kwargs)

        with mock.patch("subprocess.Popen", counting):
            second = self.repo("second", seed={"a.txt": "a\n"})
        self.assertEqual(started, [])                               # a folder copy: not one process
        self.assertNotEqual(first, second)
        self.assertEqual(tq.git(second, "rev-parse", "HEAD"), head)  # same history
        self.write_commit(second, {"b.txt": "b\n"}, "only in the copy")
        self.assertNotEqual(tq.git(second, "rev-parse", "HEAD"), head)
        self.assertEqual(tq.git(first, "rev-parse", "HEAD"), head)  # a write in one copy leaves the other unchanged
        template = [r for r in os.listdir(repo_templates.template_root("queue"))]
        probe = os.path.join(repo_templates.template_root("queue"), sorted(template)[0])
        self.assertNotEqual(tq.git(probe, "rev-parse", "HEAD"), tq.git(second, "rev-parse", "HEAD"))


class TestTemplateRoot(unittest.TestCase):
    def test_the_root_is_inside_the_runs_folder_not_the_running_tests(self):
        root = repo_templates.template_root("queue")
        self.assertEqual(os.path.dirname(root), os.path.realpath(tmp_default.run_temp()))
        self.assertIs(repo_templates.template_root("queue"), repo_templates.template_root("queue"))


if __name__ == "__main__":
    unittest.main()
