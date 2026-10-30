"""deps.toml, relay doctor's dependency checks, and install.sh --dry-run.

Every tool is a fake script on a temp PATH and every folder a temp folder; nothing is installed, and the real
PATH, HOME and relay settings are put back after each test.
"""
import json
import os
import shutil
import hashlib
import subprocess
import sys
import tempfile
import unittest
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import relay_setup  # noqa: E402

GIT = shutil.which("git") or "git"   # found before the tests narrow PATH
from fake_tools import install_fake  # noqa: E402

ENV_KEYS = ("PATH", "HOME", "CLAUDE_CONFIG_DIR", "RELAY_HOME")
# what every tool of deps.toml prints for --version when it is at the right version
GOOD = {"python3": "Python 3.14.6", "git": "git version 2.44.0", "jq": "jq-1.7.1", "uv": "uv 0.8.24 (abc 2025-10-07)",
        "ruff": "ruff 0.13.3", "mypy": "mypy 1.18.2 (compiled: yes)", "pytest": "pytest 8.4.2", "claude": "2.1.0 (Claude Code)",
        "bun": "1.2.0", "ps": "PID TTY", "lsof": "lsof version information", "coverage": "Coverage.py, version 7.17.0 with C extension"}


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

    def fake(self, name: str, output: str) -> None:
        install_fake(os.path.join(self.bin, name), f"#!/bin/sh\necho '{output}'\n")

    def fakes(self, **changes):
        """Every tool at its right version, except `changes`: a version text, or None for a tool that is not there."""
        for name, output in {**GOOD, **changes}.items():
            if output is not None:
                self.fake(name, output)


class DepsFile(unittest.TestCase):
    def test_list_parses_and_every_entry_has_its_fields(self):
        deps = relay_setup.load_deps()
        names = [d["name"] for d in deps]
        # the brief's list: python3, git, jq, claude, uv, the gate tools ruff, mypy, pytest, coverage, and bun (bin/ci hook tests); no node
        self.assertEqual(sorted(names), sorted(GOOD))
        for dep in deps:
            self.assertTrue(dep["command"] and dep["version_arg"], dep["name"])
            self.assertTrue(any(r in dep for r in relay_setup.DEP_ROUTES), dep["name"])
        by = {d["name"]: d for d in deps}
        self.assertEqual(by["python3"]["min"], "3.14.6")   # one exact python for the host and the container image
        self.assertTrue(by["python3"]["exact"])
        # a slim Linux image has no ps; the gate's process scans need it, so deps.toml lists it with its apt package
        self.assertEqual(by["ps"]["apt"], "procps")
        self.assertTrue(by["ps"]["presence"])
        # the slot reclaim asks lsof who holds the lock file; without it a waiting gate hangs, so the image must have it
        self.assertEqual(by["lsof"]["apt"], "lsof")
        self.assertTrue(by["lsof"]["presence"])
        for tool in ("ruff", "mypy", "pytest", "coverage"):   # a gate tool is pinned: an exact version, installed through uv
            self.assertTrue(by[tool]["exact"] and by[tool]["uv_tool"].endswith("==" + by[tool]["min"]), tool)
        self.assertEqual(len(by["uv"]["installer_sha256"]), 64)   # the pinned installer carries its checksum

    def test_presence_cannot_go_with_a_minimum(self):
        text = '[[dep]]\nname="a"\ncommand="a"\nversion_arg="-v"\nmanual="x"\npresence=true\nmin="1.0"\n'
        tmp = tempfile.mkdtemp(prefix="relay-deps-test-")
        try:
            path = os.path.join(tmp, "deps.toml")
            with open(path, "w") as handle:
                handle.write(text)
            with self.assertRaises(ValueError):
                relay_setup.load_deps(path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

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

    def test_ps_missing_is_a_fix_naming_procps_and_ps_that_runs_is_ok_without_a_version(self):
        # ps prints no version on macOS: it counts when it runs. A slim Linux image has none: the fix names procps.
        self.fakes(ps=None)
        got = {n: (g, d) for n, g, d in relay_setup.dep_checks()}
        good, detail = got["ps on PATH"]
        self.assertFalse(good)
        self.assertIn("not found", detail)
        by = {d["name"]: d for d in relay_setup.load_deps()}
        self.assertEqual(relay_setup.install_hint(by["ps"], "linux", "x86_64"), "sudo apt-get install -y procps")
        self.fakes()
        got = {n: g for n, g, _ in relay_setup.dep_checks()}
        self.assertTrue(got["ps on PATH"])

    def test_a_too_old_tool_is_a_fix(self):
        # the macOS system python is 3.9, below the pinned 3.14.6; ruff 0.13.2 is not the pinned 0.13.3
        self.fakes(python3="Python 3.9.6", ruff="ruff 0.13.2")
        got = {n: (g, d) for n, g, d in relay_setup.dep_checks()}
        good, detail = got["python3 3.14.6 (pinned)"]
        self.assertFalse(good)
        self.assertIn("found 3.9.6", detail)
        good, detail = got["ruff 0.13.3 (pinned)"]
        self.assertFalse(good)
        self.assertIn("found 0.13.2", detail)
        self.assertTrue(got["git on PATH"][0])

    def test_a_newer_python_is_not_ok_either_because_it_is_pinned(self):
        # the pin means exactly: python 3.14.7 and ruff 0.14.0 both fail
        self.fakes(python3="Python 3.14.7", ruff="ruff 0.14.0")
        got = {n: g for n, g, _ in relay_setup.dep_checks()}
        self.assertFalse(got["python3 3.14.6 (pinned)"])
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
        for util in ("awk", "grep", "head", "uname", "dirname", "sed", "cat", "mktemp", "rm", "sort", "tr", "id", "mkdir",
                     "chmod", "mv", "sh", "shasum", "sha256sum"):
            real = shutil.which(util, path=self.saved["PATH"])
            if real is None:
                self.assertIn(util, ("shasum", "sha256sum"))   # one of the two sum tools exists per OS
                continue
            os.symlink(real, os.path.join(self.bin, util))

    def script(self, name: str, body: str) -> None:
        """A fake program on PATH with a shell body (replaces a symlink of the same name)."""
        install_fake(os.path.join(self.bin, name), "#!/bin/sh\n" + body + "\n")

    def machine(self, system, arch):
        self.script("uname", f'case "$1" in -s) echo {system};; -m) echo {arch};; *) echo {system};; esac')

    def dry(self, script=None):
        done = subprocess.run(["/bin/sh", script or os.path.join(ROOT, "install.sh"), "--dry-run"], capture_output=True, text=True,
                              env=dict(os.environ), cwd=self.tmp)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.splitlines()

    def relay_copy(self, deps_text):
        """A copy of install.sh next to a deps.toml of the test's own, so a real run touches nothing real."""
        folder = os.path.join(self.tmp, "relay-copy")
        os.makedirs(os.path.join(folder, "bin"), exist_ok=True)
        shutil.copy(os.path.join(ROOT, "install.sh"), folder)
        with open(os.path.join(folder, "deps.toml"), "w") as handle:
            handle.write(deps_text)
        return os.path.join(folder, "install.sh")

    def real(self, script):
        return subprocess.run(["/bin/sh", script], capture_output=True, text=True, env=dict(os.environ), cwd=self.tmp)

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
        self.assertIn("install  python3 (found 3.9.6, pinned 3.14.6)", lines)
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


class CodeFolder(Fakes):
    # own class: InstallScript is inherited by three classes, which would run this test four times
    def test_code_folder_is_RELAY_ROOT_not_RELAY_HOME(self):
        """RELAY_HOME is relay's state folder (lib/relay_config.py), so it must not point install.sh at deps.toml;
        RELAY_ROOT, the code folder, does."""
        lone = os.path.join(self.tmp, "lone")           # install.sh with no deps.toml beside it
        os.makedirs(lone)
        shutil.copy(os.path.join(ROOT, "install.sh"), lone)
        code = os.path.join(self.tmp, "code")           # a folder that does hold deps.toml
        os.makedirs(code)
        shutil.copy(os.path.join(ROOT, "deps.toml"), code)
        script = os.path.join(lone, "install.sh")

        def run(var):
            env = {k: v for k, v in os.environ.items() if k not in ("RELAY_HOME", "RELAY_ROOT")}
            env[var] = code
            env["PATH"] = self.saved["PATH"]    # real tools: this test is about the folder lookup only
            return subprocess.run(["/bin/sh", script, "--dry-run"], capture_output=True, text=True, env=env, cwd=self.tmp)

        state = run("RELAY_HOME")
        self.assertEqual(state.returncode, 1, state.stdout)      # RELAY_HOME is state: deps.toml is not looked for there
        self.assertIn("deps.toml not found", state.stderr)
        self.assertIn("RELAY_ROOT", state.stderr)
        self.assertEqual(run("RELAY_ROOT").returncode, 0)


class Routes(InstallScript):
    """F1/F5: official installers first, Homebrew/apt only the fallback; the dry run names each route."""

    JQ_MAC = "https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-macos-arm64"
    JQ_MAC_SUM = "0bbe619e663e0de2c550be2fe0d240d076799d6f8a652b70fa04aea8a8362e8a"

    def test_macos_with_homebrew_goes_official_first(self):
        self.fakes(jq=None, git=None, claude=None, bun=None, python3="Python 3.9.6")
        self.machine("Darwin", "arm64")
        self.fake("brew", "brew")   # Homebrew is there, and must not be used where an official route exists
        lines = self.dry()
        self.assertNotIn("  would run: brew install jq", lines)
        self.assertNotIn("  would run: brew install git", lines)
        self.assertNotIn("  would run: brew install python@3.14", lines)
        # jq: the pinned release binary for darwin/arm64 with its sha256 (the publisher's sha256sum.txt value)
        self.assertIn(f"  would download {self.JQ_MAC}, check sha256 {self.JQ_MAC_SUM}, put it at {self.home}/.local/bin/jq", lines)
        self.assertIn("  would run: xcode-select --install", lines)   # git on macOS
        self.assertIn("  would run: uv python install 3.14.6", lines)   # python 3.9.6 -> 3.14.6 through uv
        self.assertIn("  would download https://claude.ai/install.sh and run it with bash", lines)
        self.assertIn("  would download https://bun.sh/install and run it with bash", lines)
        # no node step on macOS (the owner wants bun, no Node)
        self.assertFalse([l for l in lines if "node" in l.lower()], lines)

    def test_linux_apt_as_root_updates_once_without_sudo(self):
        self.fakes(git=None)
        self.machine("Linux", "x86_64")
        self.fake("apt-get", "apt")
        self.script("id", "echo 0")
        lines = self.dry()
        self.assertEqual(lines.count("  would run: apt-get update"), 1)   # once, before the first install
        self.assertLess(lines.index("  would run: apt-get update"), lines.index("  would run: apt-get install -y git"))
        self.assertFalse([l for l in lines if "node" in l.lower()], lines)   # no node step on Linux either
        self.assertFalse([ln for ln in lines if "sudo" in ln])

    def test_linux_apt_as_a_user_says_it_uses_sudo(self):
        self.fakes(git=None)
        self.machine("Linux", "x86_64")
        self.fake("apt-get", "apt")
        self.fake("sudo", "sudo")
        self.script("id", "echo 1000")
        lines = self.dry()
        self.assertIn("  this step uses sudo (apt-get install git)", lines)
        self.assertIn("  would run: sudo apt-get install -y git", lines)

    def test_doctor_names_the_same_route(self):
        by = {d["name"]: d for d in relay_setup.load_deps()}
        hint = relay_setup.install_hint
        self.assertIn(self.JQ_MAC, hint(by["jq"], "darwin", "arm64"))
        self.assertEqual(hint(by["git"], "darwin", "arm64"), "xcode-select --install")
        self.assertEqual(hint(by["python3"], "darwin", "arm64"), "uv python install --default 3.14.6")
        self.assertEqual(hint(by["claude"], "darwin", "arm64"), "curl -fsSL https://claude.ai/install.sh | bash")
        self.assertNotIn("node", by)
        self.assertEqual(hint(by["git"], "linux", "x86_64"), "sudo apt-get install -y git")


class PythonStep(InstallScript):
    """F2: the doctor runs under the pinned python, or the installer says there is none."""

    DEPS = '[[dep]]\nname = "python3"\ncommand = "python3"\nmin = "3.14.6"\nexact = true\nversion_arg = "--version"\nmanual = "get python"\n'

    def python(self, name, version):
        self.script(name, f'case "$1" in --version) echo "Python {version}";; *) echo "RAN {name} $*";; esac')

    def test_doctor_runs_under_the_pinned_python_when_python3_is_another(self):
        self.python("python3", "3.9.6")
        self.python("python3.14", "3.14.6")
        done = self.real(self.relay_copy(self.DEPS))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertRegex(done.stdout, r"RAN python3\.14 \S+/relay-copy/bin/relay doctor")
        self.assertNotIn("RAN python3 ", done.stdout)
        self.assertIn("python3 on PATH is 3.9.6; the doctor runs under", done.stdout)

    def test_no_pinned_python_stops_with_a_clear_line(self):
        self.python("python3", "3.9.6")
        done = self.real(self.relay_copy(self.DEPS))
        self.assertEqual(done.returncode, 1)
        self.assertIn("python3 is still 3.9.6; relay needs python 3.14.6 (exactly):", done.stdout)
        self.assertNotIn("RAN", done.stdout)

    def test_the_pinned_python3_runs_the_doctor_as_before(self):
        self.python("python3", "3.14.6")
        done = self.real(self.relay_copy(self.DEPS))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertRegex(done.stdout, r"RAN python3 \S+/relay-copy/bin/relay doctor")
        self.assertNotIn("python3 on PATH is", done.stdout)

    def test_dry_run_with_old_python_exits_zero_and_names_the_python(self):
        self.fakes(python3="Python 3.9.6")
        lines = self.dry()
        self.assertTrue(lines[-1].startswith("dry run done: python3 is 3.9.6;"), lines[-1])
        self.assertIn("python 3.14.6", lines[-1])


class BrokenAndMissing(InstallScript):
    """F3/F4/F6."""

    def test_bun_is_checked_and_node_is_not(self):
        self.fakes(bun=None)
        got = {n: (g, d) for n, g, d in relay_setup.dep_checks()}
        self.assertFalse(got["bun on PATH"][0])
        self.assertIn("https://bun.sh/install", got["bun on PATH"][1])
        self.assertNotIn("node on PATH", got)

    def test_a_tool_that_is_there_but_prints_no_version_is_not_ok(self):
        # the macOS /usr/bin/git stub without the developer tools: a file on PATH that exits 1 and prints a note
        self.fakes()
        self.script("git", "echo 'xcode-select: note: No developer tools were found' >&2; exit 1")
        got = {n: (g, d) for n, g, d in relay_setup.dep_checks()}
        good, detail = got["git on PATH"]
        self.assertFalse(good)
        self.assertIn("not working", detail)
        # the fix names the route of the machine the test runs on: macOS takes xcode-select, a Linux image apt-get (the Darwin lines below cover the installer's own route)
        self.assertIn("xcode-select --install" if sys.platform == "darwin" else "apt-get install -y git", detail)
        self.machine("Darwin", "arm64")
        lines = self.dry()
        self.assertIn("install  git (found but not working (prints no version))", lines)
        self.assertIn("  would run: xcode-select --install", lines)

    def test_a_working_git_and_claude_stay_ok(self):
        self.fakes()
        lines = self.dry()
        self.assertIn("ok       git 2.44.0", lines)
        self.assertIn("ok       claude 2.1.0", lines)
        got = {n: g for n, g, _ in relay_setup.dep_checks()}
        self.assertTrue(got["git on PATH"] and got["claude on PATH"])

    def uv_only(self, sha):
        return ('[[dep]]\nname = "uv"\ncommand = "uv"\nversion_arg = "--version"\n'
                f'installer_url = "https://example.invalid/uv-installer.sh"\ninstaller_sha256 = "{sha}"\n')

    def fake_curl(self):
        self.marker = os.path.join(self.tmp, "ran-marker")
        self.payload = f": > {self.marker}\n"
        self.script("curl", 'out=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && out="$2"; shift; done\n'
                    f"printf '%s' ': > {self.marker}' > \"$out\"")
        self.payload_sum = hashlib.sha256(f": > {self.marker}".encode()).hexdigest()

    def test_a_download_with_the_wrong_checksum_is_not_run(self):
        self.fakes(uv=None)
        self.fake_curl()
        done = self.real(self.relay_copy(self.uv_only("0" * 64)))
        self.assertIn("checksum mismatch for https://example.invalid/uv-installer.sh", done.stdout)
        self.assertIn("not run", done.stdout)
        self.assertFalse(os.path.exists(self.marker))

    def test_a_download_with_the_right_checksum_is_run(self):
        # the control for the test above: the same flow with the matching sum does run the script
        self.fakes(uv=None)
        self.fake_curl()
        done = self.real(self.relay_copy(self.uv_only(self.payload_sum)))
        self.assertIn("checksum ok", done.stdout)
        self.assertTrue(os.path.exists(self.marker), done.stdout)

    def test_dry_run_without_uv_says_what_it_would_download_and_run(self):
        self.fakes(uv=None, ruff=None)
        lines = self.dry()
        sha = {d["name"]: d for d in relay_setup.load_deps()}["uv"]["installer_sha256"]
        self.assertIn(f"  would download https://github.com/astral-sh/uv/releases/download/0.8.24/uv-installer.sh, check sha256 {sha}, run it", lines)
        self.assertIn("  would run: uv tool install ruff==0.13.3", lines)


class LeftoverPluginFolder(Fakes):
    """A renamed plugin's old folder (28 Oct: plugins/core) is named by doctor, with the command that removes it, and git ignores its node_modules."""

    def repo(self, tmp: str, tracked: tuple[str, ...] = ("relay", "front")) -> None:
        """A git repo with `plugins/<n>/.claude-plugin/plugin.json` committed for each tracked name."""
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        os.environ["PATH"] += os.pathsep + os.path.dirname(GIT)   # Fakes narrowed PATH; relay_setup runs `git` by name (restored in tearDown)
        subprocess.run([GIT, "-C", tmp, "init", "-q"], check=True, env=env)
        with open(os.path.join(tmp, ".gitignore"), "w") as f:
            f.write("__pycache__/\nnode_modules/\n")
        for n in tracked:
            os.makedirs(os.path.join(tmp, "plugins", n, ".claude-plugin"))
            open(os.path.join(tmp, "plugins", n, ".claude-plugin", "plugin.json"), "w").close()
        subprocess.run([GIT, "-C", tmp, "add", "-A"], check=True, env=env)
        subprocess.run([GIT, "-C", tmp, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], check=True, env=env)

    def test_a_folder_holding_only_ignored_files_the_marketplace_does_not_list_is_a_leftover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.repo(tmp)
            os.makedirs(os.path.join(tmp, "plugins", "core", "lib", "__pycache__"))
            open(os.path.join(tmp, "plugins", "core", "lib", "__pycache__", "x.pyc"), "w").close()
            # the real marketplace lists relay and front but not core; core holds only ignored files
            self.assertEqual(relay_setup.leftover_plugin_folders(tmp), [os.path.join(tmp, "plugins", "core")])

    def test_an_unlisted_folder_with_untracked_work_is_not_named_for_removal(self) -> None:
        # F4: a plugin being built (untracked plugin.json, not in the marketplace yet) must not get an rm -rf line
        with tempfile.TemporaryDirectory() as tmp:
            self.repo(tmp)
            os.makedirs(os.path.join(tmp, "plugins", "newp", ".claude-plugin"))
            open(os.path.join(tmp, "plugins", "newp", ".claude-plugin", "plugin.json"), "w").close()
            self.assertEqual(relay_setup.leftover_plugin_folders(tmp), [])

    def test_a_stale_install_is_listed_although_the_leftover_folder_exists(self) -> None:
        # F3: "shipped" is the marketplace's list, not the folders on disk; core@relay is not shipped though plugins/core exists
        claude = os.path.join(self.tmp, "claude")
        os.makedirs(os.path.join(claude, "plugins"))
        with open(os.path.join(claude, "plugins", "installed_plugins.json"), "w") as f:
            json.dump({"plugins": {"core@amidman": [{"scope": "project", "projectPath": "/p"}],
                                   "relay@amidman": [{"scope": "project", "projectPath": "/q"}]}}, f)
        saved = (relay_setup.ROOT, relay_setup.claude_dir)
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "plugins", "core"))
            os.makedirs(os.path.join(tmp, "plugins", "relay"))
            relay_setup.ROOT, relay_setup.claude_dir = tmp, lambda: claude
            try:
                lines = relay_setup.unshipped_installs()
            finally:
                relay_setup.ROOT, relay_setup.claude_dir = saved
        self.assertEqual(lines, ["core@amidman installed for /p: run relay setup /p"])

    def test_doctor_names_the_leftover_and_the_command_that_removes_it(self) -> None:
        self.fakes()
        leftover = os.path.join(self.tmp, "plugins", "core")
        original = relay_setup.leftover_plugin_folders
        relay_setup.leftover_plugin_folders = lambda code_root=None: [leftover]
        try:
            rows = [(n, g, d) for n, g, d in relay_setup.doctor(None, profile={}) if n == "no leftover plugin folder"]
        finally:
            relay_setup.leftover_plugin_folders = original
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0][1])
        self.assertIn(f"rm -rf {leftover}", rows[0][2])

    def test_git_ignores_node_modules_at_any_depth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(os.path.join(relay_setup.ROOT, ".gitignore"), tmp)
            subprocess.run([GIT, "-C", tmp, "init", "-q"], check=True)
            deep = os.path.join(tmp, "plugins", "core", "tests", "ts-deps", "node_modules", "typescript")
            os.makedirs(deep)
            open(os.path.join(deep, "x.js"), "w").close()
            status = subprocess.run([GIT, "-C", tmp, "status", "--short"], capture_output=True, text=True, check=True).stdout
            # only .gitignore is untracked: plugins/core holds nothing but node_modules, so git shows nothing for it
            self.assertEqual(status.split(), ["??", ".gitignore"])


if __name__ == "__main__":
    unittest.main()


class ValidateSkipsLeftover(unittest.TestCase):
    """F1: the gate's plugin validate step skips a plugin folder in which git tracks nothing (the renamed plugin's old folder)."""

    def run_validate(self, extra_untracked: dict[str, bool], broken_tracked: bool = False) -> tuple[int, list[str]]:
        import relay_ci
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
            root = os.path.join(tmp, "repo")
            os.makedirs(os.path.join(root, ".claude-plugin"))
            open(os.path.join(root, ".claude-plugin", "marketplace.json"), "w").close()
            os.makedirs(os.path.join(root, "plugins", "relay", ".claude-plugin"))
            open(os.path.join(root, "plugins", "relay", ".claude-plugin", "plugin.json"), "w").close()
            if broken_tracked:
                os.makedirs(os.path.join(root, "plugins", "broken"))
                open(os.path.join(root, "plugins", "broken", "x.txt"), "w").close()
            subprocess.run([GIT, "-C", root, "init", "-q"], check=True, env=env)
            subprocess.run([GIT, "-C", root, "add", "-A"], check=True, env=env)
            subprocess.run([GIT, "-C", root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], check=True, env=env)
            for n in extra_untracked:
                os.makedirs(os.path.join(root, "plugins", n, "lib", "__pycache__"))
                open(os.path.join(root, "plugins", n, "lib", "__pycache__", "x.pyc"), "w").close()
            calls: list[str] = []

            def runner(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[Any]:
                if argv[0] == "claude":
                    calls.append(argv[3])
                    # a fake validator: a folder is valid when it holds a manifest
                    ok = os.path.exists(os.path.join(root, argv[3], ".claude-plugin"))
                    return subprocess.CompletedProcess(argv, 0 if ok else 1)
                return subprocess.run(argv, **kw)

            bindir = os.path.join(tmp, "bin")
            os.makedirs(bindir)
            fake = os.path.join(bindir, "claude")
            open(fake, "w").close()
            os.chmod(fake, 0o755)
            ci = relay_ci.Ci(root, quick=True, env={**env, "PATH": bindir + os.pathsep + os.path.dirname(GIT)}, runner=runner)
            with open(os.path.join(tmp, "log"), "w") as log:
                return ci.validate_all(log), calls

    def test_a_folder_git_tracks_nothing_in_is_not_validated(self) -> None:
        rc, calls = self.run_validate({"core": True})
        self.assertEqual(calls, [".", "plugins/relay/"])
        self.assertEqual(rc, 0)

    def test_a_tracked_broken_plugin_is_still_validated_and_fails(self) -> None:
        rc, calls = self.run_validate({}, broken_tracked=True)
        self.assertEqual(calls, [".", "plugins/broken/", "plugins/relay/"])
        self.assertEqual(rc, 1)
