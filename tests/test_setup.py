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


class SetupIsProjectOnly(Base):
    """Owner's decision A (26 Oct): `relay setup <dir>` writes only into the project; the Claude folder is the global command's."""

    def _snapshot(self):
        out = {}
        for folder, _, files in os.walk(self.claude):
            for f in files:
                path = os.path.join(folder, f)
                out[os.path.relpath(path, self.claude)] = open(path, "rb").read()
        return out

    def _project(self):
        proj = os.path.join(self.tmp, "proj")
        os.makedirs(proj)
        subprocess.run(["git", "init", "-q", proj], check=True)
        return proj

    def test_project_setup_leaves_every_file_in_the_claude_folder_byte_identical(self):
        # The failing case: setup <project> with no flags rewrote the relay marketplace path in the user's settings.json.
        import relay_setup
        with open(os.path.join(self.claude, "settings.json"), "w") as handle:
            json.dump({"extraKnownMarketplaces": {"relay": {"source": {"source": "directory", "path": "/somewhere/else"}}}, "model": "x"}, handle)
        with open(os.path.join(self.claude, "CLAUDE.md"), "w") as handle:
            handle.write("my own file\n")
        before = self._snapshot()
        proj = self._project()
        relay_setup.setup(proj, flow="none", product=False, install_runner=lambda r, k: (True, ""))
        self.assertEqual(self._snapshot(), before)   # no file changed, none added (no .bak either)
        self.assertTrue(os.path.isfile(os.path.join(proj, ".claude", "settings.json")))

    def test_project_setup_on_an_empty_claude_folder_creates_nothing_there(self):
        import relay_setup
        proj = self._project()
        relay_setup.setup(proj, flow="none", product=False, install_runner=lambda r, k: (True, ""))
        self.assertEqual(self._snapshot(), {})

    def test_project_setup_names_the_global_command_when_the_global_part_is_missing(self):
        import relay_setup
        proj = self._project()
        *_, todo = relay_setup.setup(proj, flow="none", product=False, install_runner=lambda r, k: (True, ""))
        self.assertTrue(any("relay setup --global" in t for t in todo), todo)

    def test_the_global_command_writes_the_marketplace_at_relays_main_checkout(self):
        import relay_setup
        path, changed, _ = relay_setup.merge_user_settings(["core"])
        data = json.load(open(path))
        self.assertTrue(changed)
        self.assertEqual(data["extraKnownMarketplaces"]["relay"]["source"]["path"], relay_setup.marketplace_root())

    def test_doctor_flags_a_marketplace_path_that_is_missing_or_is_a_linked_worktree(self):
        import relay_setup
        wt = os.path.join(self.tmp, "relay-wt")
        main = os.path.join(self.tmp, "relay-main")
        os.makedirs(main)
        git = ["git", "-C", main, "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", main], check=True)
        subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "i"], check=True)
        subprocess.run(git + ["worktree", "add", "-q", "-b", "wt/x", wt], check=True)
        name = "relay marketplace in ~/.claude/settings.json is relay's main checkout"

        def verdict(path):
            with open(os.path.join(self.claude, "settings.json"), "w") as handle:
                json.dump({"extraKnownMarketplaces": {"relay": {"source": {"source": "directory", "path": path}}}}, handle)
            return {n: ok for n, ok, _ in relay_setup.doctor(None, profile={})}[name]

        self.assertFalse(verdict(os.path.join(self.tmp, "gone")))   # does not exist
        self.assertFalse(verdict(wt))                                # a linked worktree
        self.assertTrue(verdict(relay_setup.marketplace_root()))     # relay's main checkout


class SetupInWorktree(Base):
    def _repo_with_worktree(self):
        main = os.path.join(self.tmp, "mainproj")
        os.makedirs(main)
        git = ["git", "-C", main, "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", main], check=True)
        open(os.path.join(main, "go.mod"), "w").write("module x\n")
        subprocess.run(git + ["add", "go.mod"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "init"], check=True)
        wt = os.path.join(self.tmp, "somewt")
        subprocess.run(git + ["worktree", "add", "-q", "-b", "wt/x", wt], check=True)
        return main, wt

    def test_setup_in_a_linked_worktree_names_the_project_after_the_main_checkout(self):
        # Q1: the worktree folder is "somewt"; the project is "mainproj". Files go into the worktree, the registry points at the main checkout.
        import relay_setup
        main, wt = self._repo_with_worktree()
        d, *_ = relay_setup.setup(wt, flow="none", product=False)
        self.assertEqual(d["name"], "mainproj")
        self.assertIn('name = "mainproj"', open(os.path.join(wt, ".claude", "kit.toml")).read())
        self.assertFalse(os.path.exists(os.path.join(main, ".claude")))   # the main checkout stays untouched
        registry = open(os.environ["RELAY_PROJECTS"]).read()
        self.assertIn("[mainproj]", registry)
        self.assertIn(os.path.join(os.path.realpath(main), "CLAUDE.local.md"), registry)
        self.assertNotIn("somewt", registry)

    def _marketplace_path(self):
        return json.load(open(os.path.join(self.claude, "settings.json")))["extraKnownMarketplaces"]["relay"]["source"]["path"]

    def test_user_settings_marketplace_never_points_at_a_linked_worktree(self):
        # relay run from a linked worktree of itself: the global marketplace entry must name the main checkout, not the worktree
        # (the worktree is removed after its merge and every session would then load relay from nowhere).
        import relay_setup
        main, wt = self._repo_with_worktree()
        relay_setup.ROOT = wt
        relay_setup.merge_user_settings(["core"])
        self.assertEqual(self._marketplace_path(), os.path.realpath(main))

    def test_user_settings_marketplace_in_the_main_checkout_is_that_checkout(self):
        import relay_setup
        main, _ = self._repo_with_worktree()
        relay_setup.ROOT = main
        relay_setup.merge_user_settings(["core"])
        self.assertEqual(self._marketplace_path(), main)

    def _path_todo(self, root, on_path=False):
        import relay_setup
        relay_setup.ROOT = root
        real_which = shutil.which
        relay_setup.shutil.which = lambda name, *a, **k: ("/usr/bin/relay" if on_path else None) if name == "relay" else real_which(name, *a, **k)
        try:
            _, todo = relay_setup.install(run_claude=False)
        finally:
            relay_setup.shutil.which = real_which
        return [t for t in todo if t.startswith("put relay on your PATH")]

    def test_install_path_todo_never_names_a_linked_worktree(self):
        # F1: the PATH link must point at the main checkout's bin/relay; a worktree is removed after its merge and the link would dangle.
        main, wt = self._repo_with_worktree()
        (line,) = self._path_todo(wt)
        self.assertIn(os.path.join(os.path.realpath(main), "bin", "relay"), line)
        self.assertNotIn("somewt", line)

    def test_install_path_todo_in_the_main_checkout_names_that_checkout(self):
        main, _ = self._repo_with_worktree()
        (line,) = self._path_todo(main)
        self.assertIn(os.path.join(main, "bin", "relay"), line)

    def test_install_adds_no_path_todo_when_relay_is_on_path(self):
        _, wt = self._repo_with_worktree()
        self.assertEqual(self._path_todo(wt, on_path=True), [])

    def test_main_checkout_is_exact_for_each_kind_of_checkout(self):
        # F1: only a linked worktree has a main checkout elsewhere; a submodule and a --separate-git-dir checkout are their own.
        import relay_setup
        main, wt = self._repo_with_worktree()
        self.assertEqual(relay_setup.main_checkout(wt), os.path.realpath(main))
        self.assertIsNone(relay_setup.main_checkout(main))
        loose = os.path.join(self.tmp, "loose")
        os.makedirs(loose)
        self.assertIsNone(relay_setup.main_checkout(loose))
        sep = os.path.join(self.tmp, "sepwork")
        subprocess.run(["git", "init", "-q", f"--separate-git-dir={os.path.join(self.tmp, 'sep.git')}", sep], check=True)
        self.assertTrue(os.path.isfile(os.path.join(sep, ".git")))
        self.assertIsNone(relay_setup.main_checkout(sep))
        d, *_ = relay_setup.setup(sep, flow="none", product=False)
        self.assertEqual(d["name"], "sepwork")
        sub = os.path.join(main, "mods", "sub")
        subprocess.run(["git", "-C", self.tmp, "init", "-q", "subsrc"], check=True)
        src = os.path.join(self.tmp, "subsrc")
        g = ["git", "-C", src, "-c", "user.name=t", "-c", "user.email=t@t"]
        open(os.path.join(src, "f"), "w").write("x")
        subprocess.run(g + ["add", "f"], check=True)
        subprocess.run(g + ["commit", "-q", "-m", "i"], check=True)
        subprocess.run(["git", "-C", main, "-c", "protocol.file.allow=always", "-c", "user.name=t", "-c", "user.email=t@t",
                        "submodule", "add", "-q", src, "mods/sub"], check=True)
        self.assertTrue(os.path.isfile(os.path.join(sub, ".git")))
        self.assertIsNone(relay_setup.main_checkout(sub))

    def _old_agent(self, wt):
        os.makedirs(os.path.join(wt, ".claude", "agents"))
        os.makedirs(os.path.join(wt, "bin"), exist_ok=True)   # a migrating project has a bin/ folder
        open(os.path.join(wt, ".claude", "agents", "mainproj-worker.md"), "w").write("# old\n")

    def test_migrate_apply_in_a_linked_worktree_completes(self):
        # F2: no refusal, so no half-done migration: the old agent is moved aside and setup finishes, named after mainproj.
        import relay_setup
        main, wt = self._repo_with_worktree()
        self._old_agent(wt)
        d, items, moved, *_ = relay_setup.migrate(wt, apply=True, flow="none", product=False)
        self.assertEqual(d["name"], "mainproj")
        self.assertTrue(items)
        self.assertFalse(os.path.exists(os.path.join(wt, ".claude", "agents", "mainproj-worker.md")))
        self.assertTrue(os.path.isfile(os.path.join(wt, ".claude", "kit.toml")))
        self.assertFalse(os.path.exists(os.path.join(main, ".claude")))

    def test_migrate_all_with_a_worktree_registered_completes_and_reaches_later_projects(self):
        # F3: a registered worktree root does not abort the run; the project after it is migrated too.
        main, wt = self._repo_with_worktree()
        self._old_agent(wt)
        later = os.path.join(self.tmp, "later")
        os.makedirs(later)
        open(os.environ["RELAY_PROJECTS"], "w").write(
            f'[mainproj]\nfile = "{os.path.join(wt, "CLAUDE.local.md")}"\ntitle = "t"\nload = []\nread = []\n'
            f'[later]\nfile = "{os.path.join(later, "CLAUDE.local.md")}"\ntitle = "t"\nload = []\nread = []\n')
        run = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "bin", "relay"), "migrate", "--all", "--apply", "--principles", os.path.join(self.tmp, "none")],
                             capture_output=True, text=True, env=dict(os.environ), timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("==== later", run.stdout)
        self.assertTrue(os.path.isfile(os.path.join(wt, ".claude", "kit.toml")))

    def test_setup_in_the_main_checkout_still_runs_and_names_it(self):
        import relay_setup
        main, _wt = self._repo_with_worktree()
        d, *_ = relay_setup.setup(main, flow="none", product=False)
        self.assertEqual(d["name"], "mainproj")

    def test_second_setup_leaves_no_bak_beside_project_files(self):
        # kit.toml/settings.json are untracked on the first run and rewritten on the second: the copy goes under .git/, not beside them.
        import relay_setup
        main, _wt = self._repo_with_worktree()
        relay_setup.setup(main, flow="none", product=False)
        relay_setup.setup(main, flow="none", product=False, specs="none")
        strays = [os.path.join(r, f) for r, _, fs in os.walk(main) if ".git" not in r.split(os.sep) for f in fs if f.endswith(".bak")]
        self.assertEqual(strays, [])

    def test_backup_of_an_edited_file_goes_under_git_and_of_a_clean_tracked_file_is_skipped(self):
        import relay_setup
        main, _wt = self._repo_with_worktree()
        tracked = os.path.join(main, "go.mod")
        self.assertIsNone(relay_setup.backup(tracked))   # equal to HEAD: git holds it
        open(tracked, "w").write("module y\n")
        dest = relay_setup.backup(tracked)
        self.assertTrue(os.path.isfile(dest))
        self.assertTrue(os.path.realpath(dest).startswith(os.path.realpath(os.path.join(main, ".git")) + os.sep))

    def test_backup_outside_git_stays_beside_the_file(self):
        import relay_setup
        loose = os.path.join(self.tmp, "loose.json")
        open(loose, "w").write("{}")
        dest = relay_setup.backup(loose)
        self.assertEqual(os.path.dirname(dest), self.tmp)


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
        _, _, _, done, todo = relay_setup.setup(proj, specs="openspec", product=False, install_runner=runner)
        # only the flow plugin openspec is project-scope; core/observe/delegate/front are user-level
        self.assertEqual(calls, [(os.path.realpath(proj), "openspec@relay")])
        self.assertIn("installed openspec@relay at project scope", done)
        self.assertFalse([t for t in todo if "openspec@relay" in t])

    def test_setup_install_failure_todo_names_the_command(self):
        import relay_setup
        self._registry({})
        proj = self._proj()
        _, _, _, done, todo = relay_setup.setup(proj, specs="openspec", product=False,
                                                install_runner=lambda root, key: (False, "no claude"))
        self.assertTrue([t for t in todo if "claude plugin install openspec@relay --scope project" in t])
        self.assertFalse([d for d in done if "installed openspec@relay" in d])

    def test_doctor_fixes_enabled_but_not_installed(self):
        import relay_setup
        self._registry({})
        proj = self._proj()
        relay_setup.setup(proj, specs="openspec", product=False, install_runner=lambda r, k: (False, ""))
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
        _, _, _, _, todo = relay_setup.setup(proj, specs="openspec", product=False,
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
        _, _, _, done, _ = relay_setup.setup(proj, specs="openspec", product=False, install_runner=boom)
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

    def test_q1_migrate_leaves_no_settings_entry_for_a_hook_it_moved_aside(self):
        """A hook script migrate moves aside (issue-stage.sh) has no entry left in settings.json; a hook it leaves keeps its entry."""
        import relay_setup
        repo = self._repo()
        hooks = os.path.join(repo, ".claude", "hooks")
        os.makedirs(hooks)
        os.makedirs(os.path.join(repo, "bin"), exist_ok=True)   # migrate writes bin/kit and needs bin/ (a project with hooks has it)
        for name in ("issue-stage.sh", "guard.sh"):
            with open(os.path.join(hooks, name), "w") as handle:
                handle.write("#!/bin/sh\n")
        group = lambda name: {"hooks": [{"type": "command", "command": f'"$CLAUDE_PROJECT_DIR"/.claude/hooks/{name}'}]}
        with open(os.path.join(repo, ".claude", "settings.json"), "w") as handle:
            json.dump({"hooks": {"UserPromptSubmit": [group("issue-stage.sh")], "PreToolUse": [group("guard.sh")]}}, handle)
        relay_setup.migrate(repo, apply=True, flow="none", product=False)
        self.assertFalse(os.path.exists(os.path.join(hooks, "issue-stage.sh")))   # moved aside
        self.assertTrue(os.path.exists(os.path.join(hooks, "guard.sh")))          # left in place
        text = json.dumps(json.load(open(os.path.join(repo, ".claude", "settings.json")))["hooks"])
        self.assertNotIn("issue-stage.sh", text)
        self.assertIn("guard.sh", text)

    def _settings_with(self, repo, groups):
        os.makedirs(os.path.join(repo, ".claude"), exist_ok=True)
        with open(os.path.join(repo, ".claude", "settings.json"), "w") as handle:
            json.dump({"hooks": groups}, handle)

    @staticmethod
    def _cmd(path):
        return {"type": "command", "command": path}

    def test_f2_setup_keeps_entries_it_did_not_move(self):
        """Home-folder hooks and a project hook relay never moved keep their entry on plain setup (no migrate)."""
        import relay_setup
        repo = self._repo()
        later = '"$CLAUDE_PROJECT_DIR"/.claude/hooks/later.sh'   # does not exist, never moved by relay
        self._settings_with(repo, {"Stop": [{"hooks": [self._cmd("~/.claude/hooks/notify.sh")]}],
                                   "Notification": [{"hooks": [self._cmd("/Users/someone/.claude/hooks/notify.sh")]}],
                                   "PreToolUse": [{"hooks": [self._cmd(later)]}]})
        relay_setup.merge_settings(repo, [])
        hooks = json.load(open(os.path.join(repo, ".claude", "settings.json")))["hooks"]
        self.assertEqual(sorted(hooks), ["Notification", "PreToolUse", "Stop"])
        # migrate moving issue-stage.sh does not touch a home-folder hook of the same file name either
        relay_setup.merge_settings(repo, [], moved_hooks=(".claude/hooks/later.sh",))
        hooks = json.load(open(os.path.join(repo, ".claude", "settings.json")))["hooks"]
        self.assertEqual(sorted(hooks), ["Notification", "Stop"])   # only the exact moved project path went

    def test_f3_a_group_keeps_its_other_commands(self):
        """A group holding a moved hook and a kept hook loses only the moved command; a group left empty goes, and its event."""
        import relay_setup
        repo = self._repo()
        proj = lambda name: self._cmd(f'"$CLAUDE_PROJECT_DIR"/.claude/hooks/{name}')
        self._settings_with(repo, {"PreToolUse": [{"hooks": [proj("guard.sh"), proj("issue-stage.sh")]}],
                                   "UserPromptSubmit": [{"hooks": [proj("issue-stage.sh")]}],
                                   "Stop": [{"hooks": [proj("guard.sh")]}]})
        relay_setup.merge_settings(repo, [], moved_hooks=(".claude/hooks/issue-stage.sh",))
        hooks = json.load(open(os.path.join(repo, ".claude", "settings.json")))["hooks"]
        self.assertEqual(hooks["PreToolUse"], [{"hooks": [proj("guard.sh")]}])
        self.assertNotIn("UserPromptSubmit", hooks)
        self.assertEqual(hooks["Stop"], [{"hooks": [proj("guard.sh")]}])


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
