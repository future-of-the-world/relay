"""deps.toml, relay doctor's dependency checks, and install.sh --dry-run.

Every tool is a fake script on a temp PATH and every folder a temp folder; nothing is installed, and the real
PATH, HOME and relay settings are put back after each test.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_setup  # noqa: E402

ENV_KEYS = ("PATH", "HOME", "CLAUDE_CONFIG_DIR", "RELAY_HOME")
# what every tool of deps.toml prints for --version when it is at the right version
GOOD = {"python3": "Python 3.12.1", "git": "git version 2.44.0", "jq": "jq-1.7.1", "uv": "uv 0.8.24 (abc 2025-10-07)",
        "ruff": "ruff 0.13.3", "mypy": "mypy 1.18.2 (compiled: yes)", "pytest": "pytest 8.4.2", "claude": "2.1.0 (Claude Code)"}


class Fakes(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ENV_KEYS}
        self.tmp = tempfile.mkdtemp(prefix="relay-installer-test-")
        self.bin = os.path.join(self.tmp, "bin")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.bin)
        os.makedirs(self.home)
        os.environ["PATH"] = self.bin
        os.environ["HOME"] = self.home
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.tmp, "claude")
        os.environ["RELAY_HOME"] = os.path.join(self.tmp, "relay-home")

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake(self, name, output):
        path = os.path.join(self.bin, name)
        with open(path, "w") as handle:
            handle.write(f"#!/bin/sh\necho '{output}'\n")
        os.chmod(path, 0o755)

    def fakes(self, **changes):
        """Every tool at its right version, except `changes`: a version text, or None for a tool that is not there."""
        for name, output in {**GOOD, **changes}.items():
            if output is not None:
                self.fake(name, output)


class DepsFile(unittest.TestCase):
    def test_list_parses_and_every_entry_has_its_fields(self):
        deps = relay_setup.load_deps()
        names = [d["name"] for d in deps]
        # the brief's list: python3, git, jq, claude, uv, and the gate tools ruff, mypy, pytest
        self.assertEqual(sorted(names), sorted(GOOD))
        for dep in deps:
            self.assertTrue(dep["command"] and dep["version_arg"], dep["name"])
            self.assertTrue(any(r in dep for r in relay_setup.DEP_ROUTES), dep["name"])
        by = {d["name"]: d for d in deps}
        self.assertEqual(by["python3"]["min"], "3.11")
        for tool in ("ruff", "mypy", "pytest"):   # a gate tool is pinned: an exact version, installed through uv
            self.assertTrue(by[tool]["exact"] and by[tool]["uv_tool"].endswith("==" + by[tool]["min"]), tool)
        self.assertEqual(len(by["uv"]["installer_sha256"]), 64)   # the pinned installer carries its checksum

    def test_a_bad_entry_is_refused(self):
        cases = {
            "unknown field": '[[dep]]\nname="a"\ncommand="a"\nversion_arg="-v"\nmanual="x"\ncolour="red"\n',
            "no way to install": '[[dep]]\nname="a"\ncommand="a"\nversion_arg="-v"\n',
            "checksum missing": '[[dep]]\nname="a"\ncommand="a"\nversion_arg="-v"\ninstaller_url="http://x"\n',
            "bad min": '[[dep]]\nname="a"\ncommand="a"\nversion_arg="-v"\nmanual="x"\nmin="new"\n',
        }
        tmp = tempfile.mkdtemp(prefix="relay-deps-test-")
        try:
            for label, text in cases.items():
                path = os.path.join(tmp, "deps.toml")
                with open(path, "w") as handle:
                    handle.write(text)
                with self.assertRaises(ValueError, msg=label):
                    relay_setup.load_deps(path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class DoctorDeps(Fakes):
    def test_everything_right_is_ok(self):
        self.fakes()
        self.assertEqual([(n, g) for n, g, _ in relay_setup.dep_checks() if not g], [])

    def test_a_missing_tool_is_a_fix_naming_the_install_command(self):
        self.fakes(jq=None, mypy=None)
        got = {n: (g, d) for n, g, d in relay_setup.dep_checks()}
        good, detail = got["jq on PATH"]
        self.assertFalse(good)
        self.assertIn("not found", detail)
        self.assertIn("jq", detail)   # brew install jq / sudo apt-get install -y jq
        good, detail = got["mypy 1.18.2 (pinned)"]
        self.assertFalse(good)
        self.assertIn("uv tool install mypy==1.18.2", detail)

    def test_a_too_old_tool_is_a_fix(self):
        # the macOS system python is 3.9, below the 3.11 minimum; ruff 0.13.2 is not the pinned 0.13.3
        self.fakes(python3="Python 3.9.6", ruff="ruff 0.13.2")
        got = {n: (g, d) for n, g, d in relay_setup.dep_checks()}
        good, detail = got["python3 3.11+"]
        self.assertFalse(good)
        self.assertIn("found 3.9.6", detail)
        good, detail = got["ruff 0.13.3 (pinned)"]
        self.assertFalse(good)
        self.assertIn("found 0.13.2", detail)
        self.assertTrue(got["git on PATH"][0])

    def test_a_newer_minimum_tool_is_ok_but_a_newer_pin_is_not(self):
        # 3.13 >= 3.11 passes; the pin means exactly 0.13.3, so 0.14.0 fails
        self.fakes(python3="Python 3.13.0", ruff="ruff 0.14.0")
        got = {n: g for n, g, _ in relay_setup.dep_checks()}
        self.assertTrue(got["python3 3.11+"])
        self.assertFalse(got["ruff 0.13.3 (pinned)"])

    def test_relay_doctor_carries_the_checks(self):
        self.fakes(jq=None)
        names = {n: g for n, g, _ in relay_setup.doctor(None, profile={})}
        self.assertFalse(names["jq on PATH"])
        self.assertTrue(names["git on PATH"])
        self.assertIn("uv 0.8.24+", names)


class InstallScript(Fakes):
    def setUp(self):
        super().setUp()
        # the only real programs the script may use; no real jq, brew or apt-get can be found
        for util in ("awk", "grep", "head", "uname", "dirname", "sed", "cat", "mktemp", "rm", "sort", "tr"):
            real = shutil.which(util, path=self.saved["PATH"])
            self.assertTrue(real, util)
            os.symlink(real, os.path.join(self.bin, util))

    def snapshot(self):
        out = {}
        for top in (self.bin, self.home):
            for folder, _, files in os.walk(top):
                for f in files:
                    p = os.path.join(folder, f)
                    out[p] = os.path.getmtime(p) if not os.path.islink(p) else os.readlink(p)
                out[folder] = sorted(os.listdir(folder))
        return out

    def test_dry_run_lists_what_is_missing_and_changes_nothing(self):
        self.fakes(jq=None, mypy=None, claude=None, python3="Python 3.9.6")
        before = self.snapshot()
        done = subprocess.run(["/bin/sh", os.path.join(ROOT, "install.sh"), "--dry-run"], capture_output=True, text=True,
                              env=dict(os.environ), cwd=self.tmp)
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.splitlines()
        self.assertIn("install  jq (missing)", lines)
        self.assertIn("install  mypy (missing)", lines)
        self.assertIn("install  claude (missing)", lines)
        self.assertIn("install  python3 (found 3.9.6, needs 3.11+)", lines)
        self.assertIn("  would run: uv tool install mypy==1.18.2", lines)   # uv is there, so a gate tool goes through it
        self.assertIn("ok       git 2.44.0", lines)
        self.assertIn("ok       ruff 0.13.3", lines)
        self.assertFalse([ln for ln in lines if ln.startswith("install  ") and any(w in ln for w in ("git", "ruff", "uv", "pytest"))])
        self.assertTrue(lines[-1].startswith("dry run done"))
        self.assertEqual(self.snapshot(), before)   # no file made, nothing touched in HOME or on PATH

    def test_a_second_run_with_everything_there_installs_nothing(self):
        self.fakes()
        done = subprocess.run(["/bin/sh", os.path.join(ROOT, "install.sh"), "--dry-run"], capture_output=True, text=True,
                              env=dict(os.environ), cwd=self.tmp)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([ln for ln in done.stdout.splitlines() if ln.startswith(("install", "  would"))], [])


if __name__ == "__main__":
    unittest.main()
