"""Move 2 of the module split: no module grows past MAX_LINES unless it was over the limit when the cap began,
and every .py under lib/ is given to mypy (the one call of bin/types-lint)."""
import importlib.util
import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Default 600 (the owner, 28 Oct); the bound 300-1500: at 300 about 19 modules fail today, at 1500 only relay_queue.py does.
MAX_LINES = 600
MARKER = "# size: over the 600-line limit until its split item lands"
# The 9 files over 600 lines on 29 Oct, written once and never edited after: a new file cannot exempt itself.
FIRST_EXEMPT = frozenset({
    "bin/relay",
    "lib/relay_analyze.py",
    "lib/relay_bench.py",
    "lib/relay_queue.py",
    "lib/relay_setup.py",
    "lib/relay_verdict.py",
    "plugins/relay/hooks/merge.py",
    "plugins/relay/lib/kit_guard.py",
    "plugins/relay/lib/kit_packet.py",
})


def load_types_lint():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("types_lint", os.path.join(ROOT, "bin", "types_lint.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def has_marker(text: str) -> bool:
    return any(line.strip() == MARKER for line in text.splitlines()[:5])


def problem(path: str, text: str, max_lines: int = MAX_LINES, first_exempt: frozenset[str] = FIRST_EXEMPT) -> str | None:
    lines = len(text.splitlines())
    marked = has_marker(text)
    if lines > max_lines and not marked:
        return f"{path} has {lines} lines, limit {max_lines}: split it by responsibility (one module per command or subject)"
    if marked and lines <= max_lines:
        return f"{path}: remove the size marker: the file is under the limit"
    if marked and path not in first_exempt:
        return f"{path}: a new file cannot exempt itself"
    return None


def is_plugin_copy(path: str) -> bool:
    # plugins/<name>/lib/<module>.py with the same name in lib/ is a byte-identical copy; kit_* modules are not copies
    parts = path.split("/")
    return len(parts) == 4 and parts[0] == "plugins" and parts[2] == "lib" and os.path.exists(os.path.join(ROOT, "lib", parts[3]))


def in_scope(path: str) -> bool:
    if not (path.endswith(".py") or path == "bin/relay"):
        return False
    parts = path.split("/")
    if parts[0] == "tests" or (parts[0] == "plugins" and len(parts) > 2 and parts[2] == "tests"):
        return False
    return not is_plugin_copy(path)


def tracked() -> list[str]:
    out = subprocess.run(["git", "-C", ROOT, "ls-files"], capture_output=True, text=True, check=True).stdout
    return sorted(p for p in out.splitlines() if in_scope(p) and os.path.exists(os.path.join(ROOT, p)))


class ModuleSizes(unittest.TestCase):
    def test_the_limit_is_inside_its_bound(self) -> None:
        self.assertTrue(300 <= MAX_LINES <= 1500)

    def test_tree_passes(self) -> None:
        found = []
        for path in tracked():
            with open(os.path.join(ROOT, path)) as handle:
                msg = problem(path, handle.read())
            if msg:
                found.append(msg)
        self.assertEqual(found, [])

    def test_first_exempt_files_exist_and_carry_the_marker(self) -> None:
        for path in sorted(FIRST_EXEMPT):
            with self.subTest(path=path), open(os.path.join(ROOT, path)) as handle:
                text = handle.read()
            self.assertTrue(has_marker(text) or len(text.splitlines()) <= MAX_LINES, path)

    def test_a_long_file_without_a_marker_fails(self) -> None:
        # 601 lines is one over the limit of 600
        msg = problem("lib/relay_x.py", "x = 1\n" * 601)
        self.assertEqual(msg, "lib/relay_x.py has 601 lines, limit 600: split it by responsibility (one module per command or subject)")

    def test_a_file_at_the_limit_without_a_marker_passes(self) -> None:
        self.assertIsNone(problem("lib/relay_x.py", "x = 1\n" * 600))

    def test_a_marker_in_a_file_under_the_limit_fails(self) -> None:
        msg = problem("lib/relay_queue.py", MARKER + "\n" + "x = 1\n" * 599)   # 600 lines in all: at the limit
        self.assertEqual(msg, "lib/relay_queue.py: remove the size marker: the file is under the limit")

    def test_a_marker_in_a_new_file_fails(self) -> None:
        msg = problem("lib/relay_new.py", MARKER + "\n" + "x = 1\n" * 700)
        self.assertEqual(msg, "lib/relay_new.py: a new file cannot exempt itself")

    def test_a_marker_after_line_five_does_not_exempt(self) -> None:
        text = "x = 1\n" * 5 + MARKER + "\n" + "x = 1\n" * 700
        self.assertIn("limit 600", problem("lib/relay_queue.py", text) or "")

    def test_an_exempt_file_may_grow(self) -> None:
        # lib/relay_queue.py is 2046 lines in the item's pass case; no edit of FIRST_EXEMPT
        self.assertIsNone(problem("lib/relay_queue.py", MARKER + "\n" + "x = 1\n" * 2045))

    def test_a_split_taking_bin_relay_to_595_lines_is_green_without_the_marker(self) -> None:
        self.assertIsNone(problem("bin/relay", "x = 1\n" * 595, first_exempt=FIRST_EXEMPT))

    def test_plugin_copies_and_tests_are_out_of_scope(self) -> None:
        self.assertFalse(in_scope("plugins/front/lib/relay_queue.py"))
        self.assertFalse(in_scope("tests/test_queue.py"))
        self.assertFalse(in_scope("plugins/relay/tests/test_x.py"))
        self.assertTrue(in_scope("plugins/relay/lib/kit_guard.py"))
        self.assertTrue(in_scope("bin/relay"))

    def test_every_py_under_lib_is_given_to_mypy(self) -> None:
        # lib/queue_ext/json.py is a subfolder module: lib/*.py alone missed it
        given = set(load_types_lint().mypy_files(ROOT))
        on_disk = set()
        for folder, _dirs, names in os.walk(os.path.join(ROOT, "lib")):
            for name in names:
                if name.endswith(".py"):
                    on_disk.add(os.path.relpath(os.path.join(folder, name), ROOT))
        self.assertIn("lib/queue_ext/json.py", on_disk)
        self.assertEqual(sorted(on_disk - given), [])
        self.assertIn("bin/relay", given)


if __name__ == "__main__":
    unittest.main()
