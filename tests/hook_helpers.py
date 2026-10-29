"""Shared helper of the hook test suites ported from plugins/*/tests/*.test.sh: run a hook script on a JSON event."""
import linecache
import os
import subprocess
import sys
import unittest
from typing import Callable, Mapping, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_hook(script: str, stdin: str, env: Optional[Mapping[str, str]] = None, cwd: Optional[str] = None) -> str:
    """Stdout of `python3 script` fed `stdin`; the hook's own failure is not an error here (fail-open hooks print nothing)."""
    full = dict(os.environ)
    full.update(env or {})
    done = subprocess.run([sys.executable, script], input=stdin, capture_output=True, text=True, env=full, cwd=cwd)
    return done.stdout


_PLAIN = ("assertEqual", "assertNotEqual", "assertTrue", "assertFalse", "assertIs", "assertIsNot", "assertIsNone", "assertIsNotNone",
          "assertIn", "assertNotIn", "assertIsInstance", "assertGreater", "assertGreaterEqual", "assertLess", "assertLessEqual",
          "assertRegex", "assertNotRegex", "assertCountEqual", "assertMultiLineEqual", "assertListEqual", "assertDictEqual")


class SoftCases(unittest.TestCase):
    """A test case whose method runs every assert, however many fail: the bash suites named each failing case and went on;
    a plain assert stops its method at the first one. Each failed assert is listed with its file, line and source text
    (the old case's text), all of them in one failure at the end of the method."""

    def _callTestMethod(self, method: Callable[[], object]) -> None:
        soft: list[str] = []
        for name in _PLAIN:
            setattr(self, name, self._softened(getattr(unittest.TestCase, name), soft))
        error: Optional[BaseException] = None
        try:
            method()
        except BaseException as caught:
            error = caught
        for name in _PLAIN:
            delattr(self, name)
        if not soft and error is None:
            return
        if not soft and error is not None:
            raise error
        text = "%d failed asserts:\n%s" % (len(soft), "\n".join(soft))
        if error is not None:
            text += "\nthen the method raised %r" % (error,)
        raise AssertionError(text) from error

    def _softened(self, real: Callable[..., None], soft: list[str]) -> Callable[..., None]:
        def check(*args: object, **kwargs: object) -> None:
            frame = sys._getframe(1)
            try:
                real(self, *args, **kwargs)
            except AssertionError as failure:
                where = "%s:%d" % (os.path.basename(frame.f_code.co_filename), frame.f_lineno)
                source = linecache.getline(frame.f_code.co_filename, frame.f_lineno).strip()
                soft.append("  %s  %s\n      %s" % (where, source, str(failure).splitlines()[0] if str(failure) else ""))
        return check
