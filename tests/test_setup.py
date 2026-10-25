"""Library tests: setup, plugin install, the relay folder, default branch, projects."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # unittest from the repo root has only the root on sys.path
from relay_testbase import Base, ROOT  # noqa: E402


class Setup(Base):
    def test_setup_then_doctor(self):
        import relay_setup
        proj = os.path.join(self.tmp, "proj")
        os.makedirs(proj)
        subprocess.run(["git", "init", "-q", proj], check=True)
        open(os.path.join(proj, "go.mod"), "w").write("module x\n")
        d, flow, product, done, todo = relay_setup.setup(proj, flow="none", product=False)
        self.assertEqual(d["stack"], "go")
        self.assertTrue(os.path.isfile(os.path.join(proj, ".claude", "kit.toml")))
        settings = json.load(open(os.path.join(proj, ".claude", "settings.json")))
        self.assertTrue(settings["enabledPlugins"]["delegate@relay"])
        checks = relay_setup.doctor(proj, profile={})
        names = {n: ok for n, ok, _ in checks}
        self.assertTrue(names["project has .claude/kit.toml"])
        self.assertTrue(names["gate.check exists and is executable"])
        # idempotent
        d2, *_ = relay_setup.setup(proj, flow="none", product=False)
        self.assertTrue(d2["has_bindings"])


class PluginInstall(Base):
    def _proj(self):
        proj = os.path.join(self.tmp, "ip")
        os.makedirs(proj)
        subprocess.run(["git", "init", "-q", proj], check=True)
        return proj

    def _registry(self, entries):
        cdir = os.path.join(self.tmp, "cdir")
        os.makedirs(os.path.join(cdir, "plugins"), exist_ok=True)
        json.dump({"version": 2, "plugins": entries}, open(os.path.join(cdir, "plugins", "installed_plugins.json"), "w"))
        old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = cdir
        def restore():
            if old is None:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = old
        self.addCleanup(restore)

    def test_setup_openspec_installs_openspec_at_project_scope(self):
        import relay_setup
        self._registry({})
        proj = self._proj()
        calls = []
        def runner(root, key):
            calls.append((root, key))
            return True, ""
        _, _, _, done, todo = relay_setup.setup(proj, specs="openspec", product=False, apply_global=False, install_runner=runner)
        # only the flow plugin openspec is project-scope; core/observe/delegate/front are user-level
        self.assertEqual(calls, [(os.path.realpath(proj), "openspec@relay")])
        self.assertIn("installed openspec@relay at project scope", done)
        self.assertFalse([t for t in todo if "openspec@relay" in t])

    def test_setup_install_failure_todo_names_the_command(self):
        import relay_setup
        self._registry({})
        proj = self._proj()
        _, _, _, done, todo = relay_setup.setup(proj, specs="openspec", product=False, apply_global=False,
                                                install_runner=lambda root, key: (False, "no claude"))
        self.assertTrue([t for t in todo if "claude plugin install openspec@relay --scope project" in t])
        self.assertFalse([d for d in done if "installed openspec@relay" in d])

    def test_doctor_fixes_enabled_but_not_installed(self):
        import relay_setup
        self._registry({})
        proj = self._proj()
        relay_setup.setup(proj, specs="openspec", product=False, apply_global=False, install_runner=lambda r, k: (False, ""))
        names = {n: ok for n, ok, _ in relay_setup.doctor(proj, profile={})}
        self.assertFalse(names["openspec@relay installed"])
        self._registry({"openspec@relay": [{"scope": "project", "projectPath": proj}]})
        names = {n: ok for n, ok, _ in relay_setup.doctor(proj, profile={})}
        self.assertTrue(names["openspec@relay installed"])

    def test_doctor_checks_plugins_of_any_marketplace(self):
        import relay_setup
        self._registry({"other@mk": [{"scope": "user"}]})
        proj = self._proj()
        os.makedirs(os.path.join(proj, ".claude"))
        json.dump({"enabledPlugins": {"openspec@relay": True, "superpowers@official": True, "other@mk": True, "x@y": False}},
                  open(os.path.join(proj, ".claude", "settings.json"), "w"))
        names = {n: ok for n, ok, _ in relay_setup.doctor(proj, profile={})}
        self.assertFalse(names["superpowers@official installed"])
        self.assertTrue(names["other@mk installed"])  # listed with user scope
        self.assertNotIn("x@y installed", names)  # disabled: no check

    def test_failure_todo_carries_reason_and_follows_marketplace_step(self):
        import relay_setup
        self._registry({})
        proj = self._proj()
        _, _, _, _, todo = relay_setup.setup(proj, specs="openspec", product=False, apply_global=False,
                                             install_runner=lambda r, k: (False, "marketplace relay not found"))
        line = [i for i, t in enumerate(todo) if "claude plugin install openspec@relay --scope project" in t]
        market = [i for i, t in enumerate(todo) if "/plugin marketplace add" in t]
        self.assertTrue(line and market)
        self.assertIn("marketplace relay not found", todo[line[0]])
        self.assertLess(market[0], line[0])

    def test_already_installed_does_not_call_runner(self):
        import relay_setup
        proj = self._proj()
        self._registry({"openspec@relay": [{"scope": "project", "projectPath": os.path.realpath(proj)}]})
        def boom(r, k):
            raise AssertionError("runner called")
        _, _, _, done, _ = relay_setup.setup(proj, specs="openspec", product=False, apply_global=False, install_runner=boom)
        self.assertIn("openspec@relay already installed", done)

    def _fake_claude(self, body):
        script = os.path.join(self.tmp, "fakeclaude")
        open(script, "w").write("#!/bin/sh\n" + body)
        os.chmod(script, 0o755)
        old = os.environ.get("RELAY_CLAUDE_BIN")
        os.environ["RELAY_CLAUDE_BIN"] = script
        def restore():
            if old is None:
                os.environ.pop("RELAY_CLAUDE_BIN", None)
            else:
                os.environ["RELAY_CLAUDE_BIN"] = old
        self.addCleanup(restore)

    def test_run_plugin_install_real_runner(self):
        import relay_setup
        root = os.path.realpath(self._proj())
        out = os.path.join(self.tmp, "argv")
        self._fake_claude(f'echo "$@" > {out}; pwd >> {out}\nexit 0\n')
        ok, _ = relay_setup.run_plugin_install(root, "openspec@relay")
        self.assertTrue(ok)
        lines = open(out).read().split("\n")
        self.assertEqual(lines[0], "plugin install openspec@relay --scope project")
        self.assertEqual(os.path.realpath(lines[1]), root)
        self._fake_claude("echo boom >&2\nexit 1\n")
        self.assertEqual(relay_setup.run_plugin_install(root, "openspec@relay"), (False, "boom"))
        os.environ["RELAY_CLAUDE_BIN"] = os.path.join(self.tmp, "missing")
        ok, why = relay_setup.run_plugin_install(root, "openspec@relay")
        self.assertFalse(ok)
        self.assertTrue(why)


class RelayFolder(Base):
    """S1-S3 (design 12.7): `relay setup --relay-folder` writes `.relay/README.md` and nothing else."""

    def _repo(self):
        repo = os.path.join(self.tmp, "fixture-repo")
        os.makedirs(repo)
        subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
        with open(os.path.join(repo, "go.mod"), "w") as handle:
            handle.write("module x\n")
        subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
        subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"], check=True)
        return repo

    def _env(self):
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, ".claude"), exist_ok=True)
        settings = os.path.join(home, ".claude", "settings.json")
        with open(settings, "w") as handle:
            handle.write('{"enabledPlugins": {"x@y": true}}\n')
        return dict(os.environ, HOME=home, CLAUDE_CONFIG_DIR=os.path.join(home, ".claude")), settings

    def _run(self, env, *args, cwd=None):
        return subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "setup", *args],
                              env=env, cwd=cwd, capture_output=True, text=True, timeout=60)

    def _status(self, repo):
        return subprocess.run(["git", "-C", repo, "status", "--porcelain", "-uall"], capture_output=True, text=True, check=True).stdout.splitlines()

    def test_s1_relay_folder_writes_only_the_readme(self):
        repo = self._repo()
        env, settings = self._env()
        projects = os.environ["RELAY_PROJECTS"]
        before = (open(settings, "rb").read(), open(projects, "rb").read())
        out = self._run(env, "--relay-folder", repo)
        self.assertEqual(out.returncode, 0, out.stderr)
        # only the one file is new: every other piece of plain setup (kit.toml, bin/*, settings, project entry) is absent
        self.assertEqual(self._status(repo), ["?? .relay/README.md"])
        self.assertEqual((open(settings, "rb").read(), open(projects, "rb").read()), before)
        for rel in ("bin/check", "bin/wt", ".claude/kit.toml"):
            self.assertFalse(os.path.exists(os.path.join(repo, rel)), rel)

    def test_s1_default_folder_is_the_current_one(self):
        repo = self._repo()
        env, _ = self._env()
        out = self._run(env, "--relay-folder", cwd=repo)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self._status(repo), ["?? .relay/README.md"])

    def test_s2_existing_readme_is_left_alone(self):
        repo = self._repo()
        env, settings = self._env()
        os.makedirs(os.path.join(repo, ".relay"))
        with open(os.path.join(repo, ".relay", "README.md"), "w") as handle:
            handle.write("mine\n")
        before = open(settings, "rb").read()
        out = self._run(env, "--relay-folder", repo)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(open(os.path.join(repo, ".relay", "README.md")).read(), "mine\n")
        self.assertEqual(self._status(repo), ["?? .relay/README.md"])   # still just the pre-existing file, nothing added
        self.assertEqual(open(settings, "rb").read(), before)

    def test_relay_folder_refuses_other_flags_and_a_missing_folder(self):
        env, _ = self._env()
        out = self._run(env, "--relay-folder", "--flow", "none", self._repo())
        self.assertEqual(out.returncode, 2)
        out = self._run(env, "--relay-folder", os.path.join(self.tmp, "nope"))
        self.assertEqual(out.returncode, 2)

    def test_s3_plain_setup_still_writes_kit_toml_settings_and_readme(self):
        import relay_setup
        repo = self._repo()
        d, flow, product, done, todo = relay_setup.setup(repo, flow="none", product=False)
        self.assertTrue(os.path.isfile(os.path.join(repo, ".claude", "kit.toml")))
        self.assertTrue(os.path.isfile(os.path.join(repo, ".claude", "settings.json")))
        self.assertTrue(os.path.isfile(os.path.join(repo, ".relay", "README.md")))


    def test_f10_migrate_plan_and_apply_leave_the_relay_folder_out(self):
        """Review F10: `relay migrate` (a plan, and --apply) does the plain setup but writes no .relay/ (not Kartoteka's)."""
        import relay_setup
        for apply in (False, True):
            repo = self._repo() if not apply else os.path.join(self.tmp, "second")
            if apply:
                os.makedirs(repo)
                subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
            relay_setup.migrate(repo, apply=apply, flow="none", product=False)
            self.assertTrue(os.path.isfile(os.path.join(repo, ".claude", "kit.toml")), apply)       # the rest of setup ran
            self.assertFalse(os.path.exists(os.path.join(repo, ".relay")), apply)
        relay_setup.setup(repo, flow="none", product=False)                                      # relay setup of that one project does
        self.assertTrue(os.path.isfile(os.path.join(repo, ".relay", "README.md")))


class DefaultBranch(unittest.TestCase):
    """T18: relay_git.default_branch is never the current branch (design fact 2.8)."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="relay-git-test-"))
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", GIT_AUTHOR_NAME="t",
                        GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        sys.modules.pop("relay_git", None)
        import relay_git
        self.relay_git = relay_git

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, repo, *args):
        subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=self.env)

    def repo(self, name, *branches):
        """A repository whose first commit is on branches[0]; the others are local branches at the same commit."""
        d = os.path.join(self.tmp, name)
        os.makedirs(d)
        subprocess.run(["git", "init", "-q", "-b", branches[0], d], check=True, env=self.env)
        self.git(d, "commit", "-q", "--allow-empty", "-m", "init")
        for b in branches[1:]:
            self.git(d, "branch", b)
        return d

    def kit(self, repo, branch):
        os.makedirs(os.path.join(repo, ".claude"))
        with open(os.path.join(repo, ".claude", "kit.toml"), "w") as handle:
            handle.write('[project]\ndefault_branch = "%s"\n' % branch)

    def test_only_develop_with_binding(self):
        d = self.repo("a", "develop")
        self.assertIsNone(self.relay_git.default_branch(d))   # no binding, no master/main: none, not the current branch
        self.kit(d, "develop")
        self.assertEqual(self.relay_git.default_branch(d), "develop")

    def test_worktree_on_task_branch_gets_master(self):
        d = self.repo("relay-like", "master")
        self.git(d, "worktree", "add", "-q", os.path.join(d, ".worktrees", "review-gate"), "-b", "wt/review-gate")
        wt = os.path.join(d, ".worktrees", "review-gate")
        self.assertEqual(self.relay_git.default_branch(wt), "master")   # setup's default_branch answers wt/review-gate here
        self.assertEqual(self.relay_git.main_checkout(wt), d)

    def test_master_and_main_prefers_master(self):
        self.assertEqual(self.relay_git.default_branch(self.repo("b", "main", "master")), "master")

    def test_main_alone(self):
        self.assertEqual(self.relay_git.default_branch(self.repo("m", "main")), "main")

    def test_binding_naming_a_task_branch_is_ignored(self):
        d = self.repo("c", "master")
        self.kit(d, "wt/x")
        self.assertEqual(self.relay_git.default_branch(d), "master")

    def test_origin_head_wins_over_binding(self):
        d = self.repo("o", "master")
        self.kit(d, "develop")
        self.git(d, "update-ref", "refs/remotes/origin/trunk", "HEAD")
        self.git(d, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        self.assertEqual(self.relay_git.default_branch(d), "trunk")

    def test_unreadable_kit_toml_is_ignored(self):
        d = self.repo("u", "develop")
        os.makedirs(os.path.join(d, ".claude"))
        with open(os.path.join(d, ".claude", "kit.toml"), "w") as handle:
            handle.write("[project\n")
        self.assertIsNone(self.relay_git.default_branch(d))

    def test_outside_a_repository(self):
        self.assertIsNone(self.relay_git.default_branch(self.tmp))
        self.assertIsNone(self.relay_git.main_checkout(self.tmp))


class TestNoOwnerProjects(unittest.TestCase):
    """relay is portable: its own projects.toml names only global and relay, and install imports nothing."""

    def test_projects_toml_has_only_global_and_relay(self):
        import relay_config
        data = relay_config.read_toml(os.path.join(ROOT, "projects.toml"))
        self.assertEqual(sorted(data), ["global", "relay"])

    def test_install_has_no_import_from_a_principles_library(self):
        import inspect
        import relay_setup
        self.assertFalse(hasattr(relay_setup, "import_principles_projects"))
        self.assertNotIn("principles", inspect.signature(relay_setup.install).parameters)


class TestInstallRegistersNoProject(Base):
    """install leaves projects.toml as it is even when a principles library with projects.toml sits in HOME."""

    def test_install_does_not_import_principles_projects(self):
        old_home = os.environ.get("HOME")
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, "principles"))
        with open(os.path.join(home, "principles", "projects.toml"), "w") as handle:
            handle.write('[alix]\nfile = "~/alix/CLAUDE.local.md"\n\n[arsenal]\nfile = "~/arsenal/CLAUDE.local.md"\n')
        os.environ["HOME"] = home
        try:
            projects = os.environ["RELAY_PROJECTS"]
            with open(projects, "rb") as handle:
                before = handle.read()
            import relay_setup
            done, _ = relay_setup.install(run_claude=False)
            with open(projects, "rb") as handle:
                after = handle.read()
        finally:
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home
        self.assertEqual(before, after)
        self.assertFalse([line for line in done if "imported" in line.lower()])


if __name__ == "__main__":
    unittest.main(verbosity=1)
