"""Review fixes of the clean-Linux quick gate: the packet's tsc without node (F1), the python advice that really makes
python3 the pinned one (F2), and install.sh's python messages and versioned search (F3). Temporary folders and fake
programs only."""
import os
import shutil
import sys
import tempfile
import unittest
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(ROOT, "plugins", "relay", "lib"))
sys.path.insert(0, HERE)
import kit_packet  # noqa: E402
import relay_ci  # noqa: E402
import relay_setup  # noqa: E402
import test_installer_doctor as tid  # noqa: E402
from fake_tools import install_fake  # noqa: E402


class PacketTscRunner(unittest.TestCase):
    """F1: tsc's shebang is `env node`; with no node the packet runs it under bun, with neither it says what to install."""

    def setUp(self) -> None:
        self.saved_path = os.environ.get("PATH")
        self.tmp = tempfile.mkdtemp(prefix="relay-tsc-test-")
        self.bin = os.path.join(self.tmp, "bin")
        self.root = os.path.join(self.tmp, "proj")
        self.log = os.path.join(self.tmp, "calls.log")
        os.makedirs(self.bin)
        os.makedirs(os.path.join(self.root, "node_modules", ".bin"))
        self.tsc = os.path.join(self.root, "node_modules", ".bin", "tsc")
        install_fake(self.tsc, f'#!/bin/sh\necho "tsc $*" >> "{self.log}"\n')
        os.environ["PATH"] = self.bin + os.pathsep + os.path.dirname(shutil.which("mkdir") or "/bin/mkdir")
        kit_packet._declarations.clear()

    def tearDown(self) -> None:
        if self.saved_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = self.saved_path
        kit_packet._declarations.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def calls(self) -> list[str]:
        with open(self.log, encoding="utf-8") as handle:
            return handle.read().splitlines()

    def test_no_node_runs_tsc_under_bun(self) -> None:
        install_fake(os.path.join(self.bin, "bun"), f'#!/bin/sh\necho "bun $*" >> "{self.log}"\n')
        kit_packet.declarations(self.root)
        got = self.calls()
        self.assertEqual(len(got), 1, got)
        self.assertTrue(got[0].startswith(f"bun {self.tsc} -p "), got[0])   # bun first, then the tsc script

    def test_node_present_runs_tsc_directly(self) -> None:
        install_fake(os.path.join(self.bin, "node"), "#!/bin/sh\nexit 0\n")
        install_fake(os.path.join(self.bin, "bun"), f'#!/bin/sh\necho "bun $*" >> "{self.log}"\n')
        kit_packet.declarations(self.root)
        got = self.calls()
        self.assertEqual(len(got), 1, got)
        self.assertTrue(got[0].startswith("tsc -p "), got[0])

    def test_neither_node_nor_bun_names_what_to_install(self) -> None:
        with self.assertRaises(kit_packet.RefError) as ctx:
            kit_packet.declarations(self.root)
        self.assertIn("bun", str(ctx.exception))
        self.assertFalse(os.path.exists(self.log))

    def test_no_tsc_still_names_the_install_command(self) -> None:
        os.remove(self.tsc)
        with self.assertRaises(kit_packet.RefError) as ctx:
            kit_packet.declarations(self.root)
        self.assertIn("node_modules/.bin/tsc", str(ctx.exception))


class PythonAdvice(unittest.TestCase):
    def test_refusal_names_the_default_flag_and_both_versions(self) -> None:
        tmp = tempfile.mkdtemp(prefix="relay-ci-pin-")
        self.addCleanup(shutil.rmtree, tmp, True)
        with open(os.path.join(tmp, "deps.toml"), "w") as handle:
            handle.write('[[dep]]\nname = "python3"\nmin = "3.14.6"\nexact = true\n')
        got = relay_ci.python_problem(tmp, (3, 13, 5))
        assert got is not None
        self.assertIn("uv python install --default 3.14.6", got)   # plain `uv python install` leaves python3 unchanged
        self.assertIn("3.13.5", got)
        self.assertIn("pins 3.14.6", got)

    def test_doctor_fix_for_python_makes_it_the_default(self) -> None:
        dep: Any = {"uv_python": "3.14.6"}
        self.assertEqual(relay_setup.install_hint(dep, "linux", "x86_64"), "uv python install --default 3.14.6")


class InstallPythonSearch(tid.InstallScript):
    PIN = PythonAdvicePin = '[[dep]]\nname = "python3"\ncommand = "python3"\nmin = "3.14.6"\nexact = true\nversion_arg = "--version"\nmanual = "m"\n'
    LOOSE = '[[dep]]\nname = "python3"\ncommand = "python3"\nmin = "3.11"\nversion_arg = "--version"\nmanual = "m"\n'

    def python(self, name: str, version: str) -> None:
        self.script(name, f'case "$1" in --version) echo "Python {version}";; *) echo "RAN {name} $*";; esac')

    def test_uv_line_names_the_pinned_minor_not_3_11(self) -> None:
        self.fakes(python3="Python 3.9.6")
        lines = self.dry()
        uv_line = [ln for ln in lines if "via uv python install" in ln]
        self.assertEqual(len(uv_line), 1, lines)
        self.assertIn("python3.14 lands in ~/.local/bin", uv_line[0])
        self.assertNotIn("3.11", uv_line[0])

    def test_unpinned_search_finds_a_versioned_python(self) -> None:
        self.python("python3", "3.9.6")
        self.python("python3.13", "3.13.0")
        done = self.real(self.relay_copy(self.LOOSE))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertRegex(done.stdout, r"RAN python3\.13 \S+/relay-copy/bin/relay doctor")

    def test_pinned_search_still_runs_the_doctor_under_python3_14(self) -> None:
        self.python("python3", "3.9.6")
        self.python("python3.14", "3.14.6")
        done = self.real(self.relay_copy(self.PIN))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertRegex(done.stdout, r"RAN python3\.14 ")


if __name__ == "__main__":
    unittest.main()
