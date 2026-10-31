"""Library tests: setup, plugin install, the relay folder, default branch, projects."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # unittest from the repo root has only the root on sys.path
from relay_testbase import Base, ROOT  # noqa: E402


class Setup(Base):
    def _wt_project(self, wt_script):
        import relay_setup
        proj = os.path.join(self.tmp, "wtproj")
        os.makedirs(os.path.join(proj, "bin"))
        subprocess.run(["git", "init", "-q", proj], check=True, capture_output=True)
        if wt_script is not None:
            with open(os.path.join(proj, "bin", "wt"), "w") as handle:
                handle.write(wt_script)
        d = relay_setup.detect(proj)
        return relay_setup.bindings_text(d, "none")

    def test_setup_writes_the_new_delegate_names_each_with_a_comment(self):
        import relay_kit
        text = self._wt_project(None)
        lines = text.split("\n")
        start = lines.index("[delegate]")
        keys = [ln for ln in lines[start + 1:lines.index("[observe]")] if ln]
        self.assertEqual([ln.split(" =")[0] for ln in keys],
                         ["typed_agents_only", "no_session_copy_above_tokens", "max_agents_at_once", "opus_for_builders"])
        for ln in keys:
            self.assertIn("   # ", ln)
        # F6: the route guard counts agents in the whole session, so the name and comment say so
        cap = [ln for ln in keys if ln.startswith("max_agents_at_once")][0]
        self.assertIn("# agents running at the same time in one session", cap)
        self.assertEqual(relay_kit.parse(text).problems, ())

    def test_setup_migrates_an_old_kit_toml_with_one_line_per_key(self):
        import relay_setup
        proj = os.path.join(self.tmp, "oldkit")
        os.makedirs(os.path.join(proj, ".claude"))
        path = os.path.join(proj, ".claude", "kit.toml")
        with open(path, "w") as handle:
            handle.write('[delegate]\nmax_parallel = 6\nbuild_tier_opus = "deny"\n')
        done = relay_setup.rename_delegate_keys(proj)
        self.assertEqual(done, ["[delegate] max_parallel -> max_agents_at_once", "[delegate] build_tier_opus -> opus_for_builders"])
        self.assertEqual(open(path).read(), '[delegate]\nmax_agents_at_once = 6\nopus_for_builders = "never"\n')
        self.assertEqual(relay_setup.rename_delegate_keys(proj), [])


    def test_setup_uses_the_folder_bin_wt_makes(self):
        # ALIX: bin/wt makes .worktree/<name>; kit.toml must say so, not the default.
        text = self._wt_project('#!/bin/sh\ngit worktree add ".worktree/$1" -b "wt/$1"\n')
        self.assertIn('worktrees = ".worktree"', text)

    def _gitignore_after(self, wt_script, pre_ignore=""):
        import relay_setup
        proj = os.path.join(self.tmp, "giproj")
        os.makedirs(os.path.join(proj, "bin"))
        subprocess.run(["git", "init", "-q", proj], check=True, capture_output=True)
        if wt_script is not None:
            with open(os.path.join(proj, "bin", "wt"), "w") as handle:
                handle.write(wt_script)
        with open(os.path.join(proj, ".gitignore"), "w") as handle:
            handle.write(pre_ignore)
        relay_setup.ensure_gitignore(proj, relay_setup.detect(proj))   # first setup: no kit.toml, d["bindings"] is empty
        return open(os.path.join(proj, ".gitignore")).read().splitlines()

    def test_first_setup_ignores_the_folder_bin_wt_makes(self):
        lines = self._gitignore_after('#!/bin/sh\ngit worktree add ".worktree/$1"\n')
        self.assertIn(".worktree/", lines)
        self.assertNotIn(".worktrees/", lines)

    def test_first_setup_adds_no_worktrees_line_when_already_ignored(self):
        lines = self._gitignore_after('#!/bin/sh\ngit worktree add ".worktree/$1"\n', "/.worktree/\n")
        self.assertEqual([x for x in lines if "worktree" in x], ["/.worktree/"])

    def test_first_setup_ignores_default_folder_without_bin_wt(self):
        self.assertIn(".worktrees/", self._gitignore_after(None))

    def _registered(self, name, folder):
        main = os.path.join(self.tmp, name)
        os.makedirs(main)
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(g + ["init", "-q", main], check=True, capture_output=True)
        subprocess.run(g + ["-C", main, "commit", "-q", "--allow-empty", "-m", "i"], check=True, capture_output=True)
        subprocess.run(g + ["-C", main, "worktree", "add", "-q", folder + "/x", "-b", "wt/x"], check=True, capture_output=True)
        return main

    def test_worktrees_folder_sees_registered_worktree_without_bin_wt(self):
        import relay_setup
        main = self._registered("regproj", ".worktree")
        self.assertEqual(relay_setup.worktrees_folder(main), ".worktree")
        self.assertEqual(relay_setup.worktrees_folder(os.path.join(main, ".worktree", "x")), ".worktree")

    def test_worktrees_folder_registered_in_dot_worktrees(self):
        import relay_setup
        self.assertEqual(relay_setup.worktrees_folder(self._registered("regproj2", ".worktrees")), ".worktrees")

    def test_setup_default_worktrees_folder_without_bin_wt(self):
        text = self._wt_project(None)
        self.assertIn('worktrees = ".worktrees"', text)

    def test_setup_doc_states_squash_merge_limit(self):
        # A project that squash-merges pull requests on its server gets the check records in the squashed tree, naming
        # commits of the deleted branch; relay land never squashes. The doc must say both, plainly.
        text = open(os.path.join(ROOT, "docs", "setup.md"), encoding="utf-8").read()
        # Assert inside the Limit paragraph only, so the words elsewhere in the file cannot satisfy it.
        self.assertIn("Limit:", text)
        limit = text[text.index("Limit:"):].split("\n- ", 1)[0]
        self.assertIn("squash on its server is not gated", " ".join(limit.split()))
        self.assertIn("name commits", " ".join(limit.split()))
        self.assertIn("git merge --ff-only wt/<name>", limit)

    def test_relay_folder_readme_states_squash_limit(self):
        import relay_setup
        proj = os.path.join(self.tmp, "fresh")
        os.makedirs(proj)
        path, created = relay_setup.relay_folder(proj)
        self.assertTrue(created)
        text = " ".join(open(path, encoding="utf-8").read().split())
        self.assertIn("squash-merged on the server is not gated", text)
        self.assertIn("name commits of the deleted branch", text)
        # An existing README is left as it is.
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("mine\n")
        self.assertEqual(relay_setup.relay_folder(proj), (path, False))
        self.assertEqual(open(path, encoding="utf-8").read(), "mine\n")

    def _repo(self, name, agents):
        proj = os.path.join(self.tmp, name)
        os.makedirs(proj)
        subprocess.run(["git", "init", "-q", proj], check=True)
        open(os.path.join(proj, "go.mod"), "w").write("module x\n")
        if agents:
            open(os.path.join(proj, "AGENTS.md"), "w").write("team rules\n")
        return proj

    def test_setup_skeleton_imports_agents_md(self):
        # Claude Code loads AGENTS.md by itself only when no CLAUDE.md or CLAUDE.local.md exists; setup writes both,
        # so the new CLAUDE.md must import it on its first line.
        import relay_setup
        proj = self._repo("withagents", True)
        relay_setup.setup(proj)
        lines = open(os.path.join(proj, "CLAUDE.md"), encoding="utf-8").read().splitlines()
        self.assertEqual(lines[0], "@AGENTS.md")

    def test_setup_skeleton_unchanged_without_agents_md(self):
        import relay_setup
        proj = self._repo("noagents", False)
        relay_setup.setup(proj)
        text = open(os.path.join(proj, "CLAUDE.md"), encoding="utf-8").read()
        self.assertNotIn("@AGENTS.md", text)
        self.assertTrue(text.startswith("# noagents\n"))

    def test_setup_never_rewrites_existing_claude_md_and_doctor_reports_missing_import(self):
        import relay_setup
        proj = self._repo("existing", True)
        open(os.path.join(proj, "CLAUDE.md"), "w").write("mine\n")
        relay_setup.setup(proj)
        self.assertEqual(open(os.path.join(proj, "CLAUDE.md")).read(), "mine\n")
        names = {n: ok for n, ok, _ in relay_setup.doctor(proj, profile={})}
        self.assertFalse(names["AGENTS.md is loaded (imported by CLAUDE.md)"])
        open(os.path.join(proj, "CLAUDE.md"), "w").write("@AGENTS.md\n\nmine\n")
        names = {n: ok for n, ok, _ in relay_setup.doctor(proj, profile={})}
        self.assertTrue(names["AGENTS.md is loaded (imported by CLAUDE.md)"])

    def _loaded(self, claude, agents_in=("AGENTS.md",), extra=None):
        import relay_setup
        proj = os.path.join(self.tmp, "loaded%d" % len(os.listdir(self.tmp)))
        os.makedirs(os.path.join(proj, ".claude"))
        for name in agents_in:
            open(os.path.join(proj, name), "w").write("rules\n")
        for name, text in dict(extra or {}, **({"CLAUDE.md": claude} if claude is not None else {})).items():
            open(os.path.join(proj, name), "w").write(text)
        return relay_setup.agents_md_loaded(proj)

    def test_agents_md_loaded_ignores_fake_settings_key(self):
        # F1: claude-md-and-agents-md is a value of a plugin option, not a project settings key: it must not count.
        self.assertFalse(self._loaded("# x\n", extra={".claude/settings.json": '{"claude-md-and-agents-md": true}'}))

    def test_agents_md_loaded_import_forms(self):
        # F2: Claude Code imports @path anywhere in the text, with ./, and from .claude/CLAUDE.md
        self.assertTrue(self._loaded("@./AGENTS.md\n# x\n"))
        self.assertTrue(self._loaded("Team rules: @AGENTS.md\n"))
        self.assertTrue(self._loaded("# x\n", extra={".claude/CLAUDE.md": "@../AGENTS.md\n"}))
        self.assertTrue(self._loaded("@AGENTS.md\n# x\n"))
        self.assertFalse(self._loaded("# x\nsee AGENTS.md\n"))
        self.assertTrue(self._loaded("# x\n", agents_in=()))

    def test_dot_claude_agents_md_is_imported_and_checked(self):
        # F3: .claude/AGENTS.md is also lost once CLAUDE.md exists
        import relay_setup
        proj = os.path.join(self.tmp, "dotclaude")
        os.makedirs(os.path.join(proj, ".claude"))
        open(os.path.join(proj, ".claude", "AGENTS.md"), "w").write("rules\n")
        self.assertEqual(relay_setup.agents_import(proj), "@.claude/AGENTS.md\n\n")
        self.assertFalse(self._loaded("# x\n", agents_in=(".claude/AGENTS.md",)))
        self.assertTrue(self._loaded("@.claude/AGENTS.md\n", agents_in=(".claude/AGENTS.md",)))
        self.assertFalse(self._loaded("@AGENTS.md\n", agents_in=("AGENTS.md", ".claude/AGENTS.md")))

    def test_setup_then_doctor(self):
        import relay_setup
        proj = os.path.join(self.tmp, "proj")
        os.makedirs(proj)
        subprocess.run(["git", "init", "-q", proj], check=True)
        open(os.path.join(proj, "go.mod"), "w").write("module x\n")
        d, flow, done, todo = relay_setup.setup(proj)
        self.assertEqual(d["stack"], "go")
        self.assertTrue(os.path.isfile(os.path.join(proj, ".claude", "kit.toml")))
        settings = json.load(open(os.path.join(proj, ".claude", "settings.json")))
        self.assertTrue(settings["enabledPlugins"]["delegate@amidman"])
        checks = relay_setup.doctor(proj, profile={})
        names = {n: ok for n, ok, _ in checks}
        self.assertTrue(names["project has .claude/kit.toml"])
        self.assertTrue(names["gate.check exists and is executable"])
        # idempotent
        d2, *_ = relay_setup.setup(proj)
        self.assertTrue(d2["has_bindings"])

    def test_doctor_parts_keep_machine_checks_out_of_the_project_part(self):
        import relay_setup
        proj = os.path.join(self.tmp, "proj")
        os.makedirs(proj)
        subprocess.run(["git", "init", "-q", proj], check=True)
        open(os.path.join(proj, "go.mod"), "w").write("module x\n")
        relay_setup.setup(proj)
        machine, project = relay_setup.doctor_parts(proj, profile={})
        # the user's settings are empty in the temp Claude folder, so the machine part has FIXes (e.g. "rules in sync" or the marketplace)
        self.assertTrue([n for n, good, _ in machine if not good])
        # "project has .claude/kit.toml" is the first project check; no machine check names the project
        self.assertEqual(project[0][0], "project has .claude/kit.toml")
        self.assertNotIn("relay marketplace in ~/.claude/settings.json", [n for n, _, _ in project])
        self.assertEqual(relay_setup.doctor_parts(None, profile={})[1], [])

    def _relay_repo(self, name="relayrepo"):
        """A temporary git repo standing in for the relay checkout, with bin/relay committed."""
        repo = os.path.join(self.tmp, name)
        os.makedirs(os.path.join(repo, "bin"))
        subprocess.run(["git", "init", "-q", repo], check=True)
        with open(os.path.join(repo, "bin", "relay"), "w") as handle:
            handle.write("real relay\n")
        git = ["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run([*git, "add", "bin/relay"], check=True)
        subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)
        return repo

    def _bin_relay_entries(self, repo, root=None):
        """The doctor's bin/relay entries when relay runs from `repo`; `root` is the project given to doctor. The rest of the check-up
        needs a whole relay, so only the bin/relay check is pointed at `repo`, and only when doctor hands it relay's own ROOT."""
        import relay_setup
        real = relay_setup.bin_relay_problem
        asked = []

        def point_at_repo(folder):
            asked.append(folder)
            return real(repo)
        with mock.patch.object(relay_setup, "bin_relay_problem", point_at_repo):
            machine, _ = relay_setup.doctor_parts(root, profile={})
        self.assertEqual(asked, [relay_setup.ROOT])   # relay's own checkout, never the project given to doctor
        return [(n, good, d) for n, good, d in machine if "bin/relay" in n]

    def test_doctor_names_a_main_checkout_whose_bin_relay_differs_from_head(self):
        repo = self._relay_repo()
        with open(os.path.join(repo, "bin", "relay"), "w") as handle:
            handle.write("stub\n")   # the 28 Oct incident: another file's bytes in bin/relay
        entries = self._bin_relay_entries(repo)
        self.assertEqual(len(entries), 1)
        name, good, detail = entries[0]
        self.assertFalse(good)
        self.assertIn("differs from HEAD", detail)
        self.assertIn("git -C " + os.path.realpath(repo) + " restore --source=HEAD --staged --worktree bin/relay", detail)

    def test_doctor_passes_bin_relay_equal_to_head(self):
        entries = self._bin_relay_entries(self._relay_repo())
        self.assertEqual([good for _, good, _ in entries], [True])

    def test_doctor_checks_the_main_checkout_not_the_task_worktree(self):
        repo = self._relay_repo()
        wt = os.path.join(self.tmp, "wt")
        subprocess.run(["git", "-C", repo, "worktree", "add", "-q", "-b", "task", wt], check=True)
        with open(os.path.join(wt, "bin", "relay"), "w") as handle:
            handle.write("a branch editing bin/relay\n")   # legitimate work in the worktree
        self.assertEqual([good for _, good, _ in self._bin_relay_entries(wt)], [True])
        with open(os.path.join(repo, "bin", "relay"), "w") as handle:
            handle.write("stub\n")
        self.assertEqual([good for _, good, _ in self._bin_relay_entries(wt)], [False])

    def test_doctor_checks_relays_checkout_not_the_project_given_to_it(self):
        # F4 pass case 2: ROOT clean, the project given to doctor is another repo with its own changed bin/relay
        other = self._relay_repo("other")
        with open(os.path.join(other, "bin", "relay"), "w") as handle:
            handle.write("changed\n")
        self.assertEqual([good for _, good, _ in self._bin_relay_entries(self._relay_repo(), other)], [True])

    def test_doctor_bin_relay_check_leaves_the_index_alone_and_takes_no_lock(self):
        # F2: stale stat info makes `git status` rewrite .git/index; a held index.lock must not change the answer
        import relay_setup
        repo = self._relay_repo()
        os.utime(os.path.join(repo, "bin", "relay"), (1, 1))
        index = os.path.join(repo, ".git", "index")
        os.utime(index, (5, 5))
        self.assertIsNone(relay_setup.bin_relay_problem(repo))
        self.assertEqual(os.stat(index).st_mtime, 5)
        open(index + ".lock", "w").close()
        self.assertIsNone(relay_setup.bin_relay_problem(repo))
        with open(os.path.join(repo, "bin", "relay"), "w") as handle:
            handle.write("stub\n")
        self.assertIn("differs from HEAD", relay_setup.bin_relay_problem(repo))
        self.assertTrue(os.path.exists(index + ".lock"))   # nobody removed or took it

    def test_doctor_restore_command_brings_back_a_staged_stub(self):
        # F3: `git restore bin/relay` alone leaves a staged stub; the printed command must restore index and file
        import relay_setup
        repo = self._relay_repo()
        with open(os.path.join(repo, "bin", "relay"), "w") as handle:
            handle.write("stub\n")
        subprocess.run(["git", "-C", repo, "add", "bin/relay"], check=True)
        cmd = relay_setup.bin_relay_problem(repo).split("terminal outside the session: ", 1)[1].split()
        subprocess.run(cmd, check=True)
        self.assertIsNone(relay_setup.bin_relay_problem(repo))
        self.assertEqual(open(os.path.join(repo, "bin", "relay")).read(), "real relay\n")

    def _doctor_project(self, installed=True, leftovers=(), fresh_rules=True):
        """A set-up temp project whose plugins are (by default) installed for it; the user's settings stay empty, so the machine part has FIXes."""
        import relay_setup
        proj = os.path.realpath(os.path.join(self.tmp, "proj"))
        os.makedirs(proj)
        subprocess.run(["git", "init", "-q", proj], check=True)
        relay_setup.setup(proj, install_runner=lambda r, k: (True, ""))
        keys = [k for k, v in json.load(open(os.path.join(proj, ".claude", "settings.json")))["enabledPlugins"].items() if v] if installed else []
        plugins = {k: [{"scope": "project", "projectPath": proj}] for k in keys}
        for key, path in leftovers:
            plugins[key] = [{"scope": "project", "projectPath": path}]
        os.makedirs(os.path.join(self.claude, "plugins"), exist_ok=True)
        with open(os.path.join(self.claude, "plugins", "installed_plugins.json"), "w") as handle:
            json.dump({"plugins": plugins}, handle)
        # setup registers the project in projects.toml; write its rules file as sync would, unless the test wants it stale
        import relay_config
        import relay_rules
        spec = relay_rules.targets()["proj"]
        if fresh_rules:
            os.makedirs(os.path.dirname(spec["file"]), exist_ok=True)
            with open(spec["file"], "w", encoding="utf-8") as handle:
                handle.write(relay_rules.render_target("proj", spec, relay_rules.rules(), relay_config.active_profile()))
        return proj

    def _doctor(self, *args):
        done = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "doctor", *args], capture_output=True, text=True, env=os.environ.copy())
        head, _, tail = done.stdout.partition("# This machine")
        return done.returncode, head, tail, done.stdout + done.stderr

    def test_relay_doctor_of_a_fine_project_exits_0_with_a_machine_fix(self):
        # The project part is all ok (plugins installed for it); the empty user settings give machine FIXes. Exit 0, FIXes shown under the machine heading.
        proj = self._doctor_project()
        code, head, tail, out = self._doctor(proj)
        self.assertNotIn("FIX ", head, out)
        self.assertIn("FIX  relay marketplace in ~/.claude/settings.json ", tail)
        self.assertEqual(code, 0, out)

    def test_relay_doctor_of_a_project_with_one_project_fix_exits_1(self):
        proj = self._doctor_project()
        os.chmod(os.path.join(proj, "bin", "check"), 0o644) if os.path.isfile(os.path.join(proj, "bin", "check")) else self.fail("no bin/check")
        code, head, _, out = self._doctor(proj)
        self.assertIn("FIX  gate.check exists and is executable", head)
        self.assertEqual(code, 1, out)

    def test_relay_doctor_without_a_folder_counts_a_machine_fix(self):
        code, _, _, out = self._doctor()
        self.assertIn("FIX  relay marketplace in ~/.claude/settings.json ", out)
        self.assertEqual(code, 1, out)

    def test_a_stale_rules_file_of_the_checked_project_decides_its_exit_code(self):
        # setup registered [proj], the checked folder, and its file is not written (stale); [demo] is stale too and stays machine-wide.
        proj = self._doctor_project(fresh_rules=False)
        code, head, tail, out = self._doctor(proj)
        self.assertIn("FIX  rules for this project in sync", head)
        self.assertEqual(code, 1, out)
        rules_line = [l for l in tail.splitlines() if "rules in sync" in l][0]
        self.assertIn("demo", rules_line)
        self.assertNotIn("proj", rules_line.replace("project", ""))

    def test_a_stale_rules_file_of_another_project_does_not_decide_the_exit_code(self):
        proj = self._doctor_project()
        code, head, tail, out = self._doctor(proj)
        self.assertNotIn("rules for this project", head.replace("ok   rules for this project in sync", ""))
        self.assertIn("FIX  rules in sync  (global; demo -> relay sync)", tail)   # only the other projects are named
        self.assertEqual(code, 0, out)

    def test_nothing_stale_shows_no_rules_fix(self):
        import relay_setup
        proj = self._doctor_project()
        import relay_config
        import relay_rules
        for name, spec in relay_rules.targets().items():
            os.makedirs(os.path.dirname(spec["file"]), exist_ok=True)
            open(spec["file"], "w").write(relay_rules.render_target(name, spec, relay_rules.rules(), relay_config.active_profile()))
        machine, project = relay_setup.doctor_parts(proj, profile=relay_config.active_profile())
        self.assertTrue(dict((n, g) for n, g, _ in machine)["rules in sync"])
        self.assertTrue(dict((n, g) for n, g, _ in project)["rules for this project in sync"])

    def test_a_leftover_install_for_the_checked_project_counts_for_it(self):
        proj = self._doctor_project(leftovers=[("gone@amidman", os.path.join(self.tmp, "proj"))])
        code, head, tail, out = self._doctor(proj)
        self.assertIn("FIX  installed plugin still shipped", head)
        self.assertNotIn("installed plugin still shipped", tail)
        self.assertEqual(code, 1, out)

    def test_a_leftover_install_for_another_project_stays_machine_wide(self):
        proj = self._doctor_project(leftovers=[("gone@amidman", os.path.join(self.tmp, "other"))])
        code, head, tail, out = self._doctor(proj)
        self.assertNotIn("installed plugin still shipped", head)
        self.assertIn("FIX  installed plugin still shipped", tail)
        self.assertEqual(code, 0, out)


class SetupGitignore(Base):
    """A fresh project stays clean (git status empty) after setup, a check's output and a worktrees folder; an existing .gitignore keeps its lines."""

    def _proj(self, ignore=None):
        import relay_setup
        proj = os.path.join(self.tmp, "proj")
        os.makedirs(proj)
        subprocess.run(["git", "init", "-q", proj], check=True)
        open(os.path.join(proj, "pyproject.toml"), "w").write("[project]\nname = 'x'\n")
        if ignore is not None:
            open(os.path.join(proj, ".gitignore"), "w").write(ignore)
        relay_setup.setup(proj)
        return proj

    def _status(self, proj):
        return subprocess.run(["git", "-C", proj, "status", "--short", "-uall"], capture_output=True, text=True, check=True).stdout.splitlines()

    def test_what_a_check_and_a_worktree_leave_behind_is_ignored(self):
        proj = self._proj()
        for rel in (".ci/check/a.log", ".worktrees/t/f", "__pycache__/m.pyc", ".pytest_cache/v"):
            os.makedirs(os.path.dirname(os.path.join(proj, rel)), exist_ok=True)
            open(os.path.join(proj, rel), "w").write("x")
        # setup's own files (kit.toml, bin/*, settings, CLAUDE.md, docs) are the owner's to commit; nothing else may show
        shown = [line for line in self._status(proj) if not line.startswith("?? .claude/") and not line.startswith("?? bin/") and not line.startswith("?? .relay/") and line not in ("?? CLAUDE.md", "?? docs/handover.md", "?? pyproject.toml")]
        self.assertEqual(shown, ["?? .gitignore"])

    def test_existing_lines_are_kept_and_not_duplicated(self):
        proj = self._proj(ignore="secret.txt\n.ci\n/.worktrees")   # no final newline; two entries written without the slash form we add
        lines = open(os.path.join(proj, ".gitignore")).read().splitlines()
        self.assertEqual(lines[:3], ["secret.txt", ".ci", "/.worktrees"])
        self.assertEqual(lines[3:], ["__pycache__/", ".pytest_cache/", ".ruff_cache/", ".mypy_cache/"])


class GitignoreCases(Base):
    """Review findings F1-F4 of the .gitignore lines: line endings, anchors and negations, a folder outside the project, the kit.toml folder."""

    def _ensure(self, ignore=None, worktrees=None, name="p"):
        import relay_setup
        root = os.path.join(self.tmp, name)
        os.makedirs(root, exist_ok=True)
        if ignore is not None:
            with open(os.path.join(root, ".gitignore"), "wb") as handle:
                handle.write(ignore)
        bindings = {} if worktrees is None else {"project": {"worktrees": worktrees}}
        added = relay_setup.ensure_gitignore(root, {"stack": "python", "bindings": bindings})
        return added, open(os.path.join(root, ".gitignore"), "rb").read()

    def test_f1_crlf_file_is_kept_byte_for_byte(self):
        _, data = self._ensure(b".ci/\r\nfoo\r\n")
        # .ci/ is present; the other lines are appended with the file's own endings
        self.assertEqual(data, b".ci/\r\nfoo\r\n.worktrees/\r\n__pycache__/\r\n.pytest_cache/\r\n.ruff_cache/\r\n.mypy_cache/\r\n")

    def test_f1_no_final_newline_and_fresh_file(self):
        _, data = self._ensure(b"secret.txt\n.ci\n/.worktrees", name="a")
        self.assertEqual(data, b"secret.txt\n.ci\n/.worktrees\n__pycache__/\n.pytest_cache/\n.ruff_cache/\n.mypy_cache/\n")
        _, data = self._ensure(None, name="b")
        self.assertEqual(data, b".ci/\n.worktrees/\n__pycache__/\n.pytest_cache/\n.ruff_cache/\n.mypy_cache/\n")

    def test_f2_anchored_cache_is_not_present(self):
        added, _ = self._ensure(b"/__pycache__/\n")
        self.assertIn("__pycache__/", added)

    def test_f2_negated_entry_is_left_in_force(self):
        added, data = self._ensure(b"!.ci/\n")
        self.assertNotIn(".ci/", added)
        self.assertEqual(data.count(b".ci/"), 1)

    def test_f2_anchored_root_folders_and_plain_cache_count_as_present(self):
        added, _ = self._ensure(b".ci\n/.worktrees\n__pycache__\n")
        self.assertEqual(added, [".pytest_cache/", ".ruff_cache/", ".mypy_cache/"])

    def test_f3_folder_outside_the_project_adds_no_line(self):
        for n, outside in enumerate(("/Users/x/wt", "../wt")):
            added, _ = self._ensure(worktrees=outside, name=f"o{n}")
            self.assertEqual(added, [".ci/", "__pycache__/", ".pytest_cache/", ".ruff_cache/", ".mypy_cache/"], outside)

    def test_f3_folder_inside_comes_from_kit_toml(self):
        added, _ = self._ensure(worktrees="trees")
        self.assertEqual(added[:2], [".ci/", "trees/"])
        self.assertNotIn(".worktrees/", added)

    def test_f4_setup_reads_kit_toml_worktrees(self):
        import relay_setup
        proj = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(proj, ".claude"))
        subprocess.run(["git", "init", "-q", proj], check=True)
        open(os.path.join(proj, "pyproject.toml"), "w").write("[project]\nname = 'x'\n")
        open(os.path.join(proj, ".claude", "kit.toml"), "w").write('[project]\nworktrees = "trees"\n')
        relay_setup.setup(proj)
        lines = open(os.path.join(proj, ".gitignore")).read().splitlines()
        self.assertIn("trees/", lines)
        self.assertNotIn(".worktrees/", lines)


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
            json.dump({"extraKnownMarketplaces": {"amidman": {"source": {"source": "directory", "path": "/somewhere/else"}}}, "model": "x"}, handle)
        with open(os.path.join(self.claude, "CLAUDE.md"), "w") as handle:
            handle.write("my own file\n")
        before = self._snapshot()
        proj = self._project()
        relay_setup.setup(proj, install_runner=lambda r, k: (True, ""))
        self.assertEqual(self._snapshot(), before)   # no file changed, none added (no .bak either)
        self.assertTrue(os.path.isfile(os.path.join(proj, ".claude", "settings.json")))

    def test_project_setup_on_an_empty_claude_folder_creates_nothing_there(self):
        import relay_setup
        proj = self._project()
        relay_setup.setup(proj, install_runner=lambda r, k: (True, ""))
        self.assertEqual(self._snapshot(), {})

    def test_project_setup_names_the_global_command_when_the_global_part_is_missing(self):
        import relay_setup
        proj = self._project()
        *_, todo = relay_setup.setup(proj, install_runner=lambda r, k: (True, ""))
        self.assertTrue(any("relay setup --global" in t for t in todo), todo)

    def test_the_global_command_writes_the_marketplace_at_relays_main_checkout(self):
        import relay_setup
        path, changed, _ = relay_setup.merge_user_settings(["relay"])
        data = json.load(open(path))
        self.assertTrue(changed)
        self.assertEqual(data["extraKnownMarketplaces"]["amidman"]["source"]["path"], relay_setup.marketplace_root())

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
                json.dump({"extraKnownMarketplaces": {"amidman": {"source": {"source": "directory", "path": path}}}}, handle)
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
        d, *_ = relay_setup.setup(wt)
        self.assertEqual(d["name"], "mainproj")
        self.assertIn('name = "mainproj"', open(os.path.join(wt, ".claude", "kit.toml")).read())
        self.assertFalse(os.path.exists(os.path.join(main, ".claude")))   # the main checkout stays untouched
        registry = open(os.environ["RELAY_PROJECTS"]).read()
        self.assertIn("[mainproj]", registry)
        self.assertIn(os.path.join(os.path.realpath(main), "CLAUDE.local.md"), registry)
        self.assertNotIn("somewt", registry)

    def _marketplace_path(self):
        return json.load(open(os.path.join(self.claude, "settings.json")))["extraKnownMarketplaces"]["amidman"]["source"]["path"]

    def test_user_settings_marketplace_never_points_at_a_linked_worktree(self):
        # relay run from a linked worktree of itself: the global marketplace entry must name the main checkout, not the worktree
        # (the worktree is removed after its merge and every session would then load relay from nowhere).
        import relay_setup
        main, wt = self._repo_with_worktree()
        relay_setup.ROOT = wt
        relay_setup.merge_user_settings(["relay"])
        self.assertEqual(self._marketplace_path(), os.path.realpath(main))

    def test_user_settings_marketplace_in_the_main_checkout_is_that_checkout(self):
        import relay_setup
        main, _ = self._repo_with_worktree()
        relay_setup.ROOT = main
        relay_setup.merge_user_settings(["relay"])
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
        d, *_ = relay_setup.setup(sep)
        self.assertEqual(d["name"], "sepwork")
        sub = os.path.join(main, "mods", "sub")
        subprocess.run(["git", "-C", self.tmp, "init", "-q", "subsrc"], check=True)
        src = os.path.join(self.tmp, "subsrc")
        g = ["git", "-C", src, "-c", "user.name=t", "-c", "user.email=t@t"]
        open(os.path.join(src, "f"), "w").write("x")
        subprocess.run(g + ["add", "f"], check=True)
        subprocess.run(g + ["commit", "-q", "-m", "i"], check=True)
        # `submodule add` clones a child repository and an ambient GIT_ALLOW_PROTOCOL or GIT_CONFIG_COUNT/KEY/VALUE from the
        # caller of the gate overrides the -c below (the gate of 6a204966 failed on it), so it runs with every GIT_* variable dropped.
        clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        subprocess.run(["git", "-C", main, "-c", "protocol.file.allow=always", "-c", "user.name=t", "-c", "user.email=t@t",
                        "submodule", "add", "-q", src, "mods/sub"], check=True, env=clean, capture_output=True, text=True)
        self.assertTrue(os.path.isfile(os.path.join(sub, ".git")))
        self.assertIsNone(relay_setup.main_checkout(sub))

    def test_submodule_check_ignores_ambient_git_protocol_settings(self):
        # the caller's GIT_ALLOW_PROTOCOL (only https) would refuse the file transport the submodule clone needs
        with mock.patch.dict(os.environ, {"GIT_ALLOW_PROTOCOL": "https"}):
            self.test_main_checkout_is_exact_for_each_kind_of_checkout()

    def _old_agent(self, wt):
        os.makedirs(os.path.join(wt, ".claude", "agents"))
        os.makedirs(os.path.join(wt, "bin"), exist_ok=True)   # a migrating project has a bin/ folder
        open(os.path.join(wt, ".claude", "agents", "mainproj-worker.md"), "w").write("# old\n")

    def test_migrate_apply_in_a_linked_worktree_completes(self):
        # F2: no refusal, so no half-done migration: the old agent is moved aside and setup finishes, named after mainproj.
        import relay_setup
        main, wt = self._repo_with_worktree()
        self._old_agent(wt)
        d, items, moved, *_ = relay_setup.migrate(wt, apply=True)
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
                             capture_output=True, text=True, env=dict(os.environ), timeout=600)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("==== later", run.stdout)
        self.assertTrue(os.path.isfile(os.path.join(wt, ".claude", "kit.toml")))

    def test_setup_in_the_main_checkout_still_runs_and_names_it(self):
        import relay_setup
        main, _wt = self._repo_with_worktree()
        d, *_ = relay_setup.setup(main)
        self.assertEqual(d["name"], "mainproj")

    def test_second_setup_leaves_no_bak_beside_project_files(self):
        # kit.toml/settings.json are untracked on the first run and rewritten on the second: the copy goes under .git/, not beside them.
        import relay_setup
        main, _wt = self._repo_with_worktree()
        relay_setup.setup(main)
        relay_setup.setup(main, specs="none")
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
        _, _, done, todo = relay_setup.setup(proj, specs="openspec", install_runner=runner)
        # only the flow plugin openspec is project-scope; core/observe/delegate/front are user-level
        self.assertEqual(calls, [(os.path.realpath(proj), "openspec@amidman")])
        self.assertIn("installed openspec@amidman at project scope", done)
        self.assertFalse([t for t in todo if "openspec@amidman" in t])

    def test_setup_todo_names_install_for_always_on_plugins_doctor_flags(self):
        import relay_setup
        self._registry({})
        proj = self._proj()
        calls = []
        _, _, _, todo = relay_setup.setup(proj, install_runner=lambda r, k: (calls.append(k) or True, ""))
        # always-on plugins are not installed by setup (user scope owns them), but doctor flags each
        # one that is installed nowhere, so the to-do must carry the exact command for each
        flagged = [n for n, ok, _ in relay_setup.doctor(proj, profile={}) if n.endswith(" installed") and not ok]
        self.assertTrue(flagged)
        for name in flagged:
            key = name[: -len(" installed")]
            self.assertTrue([t for t in todo if f"claude plugin install {key} --scope project" in t], key)
        self.assertEqual(calls, [])

    def test_setup_no_install_todo_for_always_on_plugins_installed_at_user_scope(self):
        import relay_setup
        keys = ["relay@amidman", "observe@amidman", "delegate@amidman", "front@amidman"]
        self._registry({k: [{"scope": "user"}] for k in keys})
        proj = self._proj()
        _, _, _, todo = relay_setup.setup(proj, install_runner=lambda r, k: (True, ""))
        # all four are installed at user scope (a set-up machine): nothing to install, no to-do
        self.assertEqual([t for t in todo if "claude plugin install" in t or "enabled but not installed" in t], [])

    def test_setup_todo_names_only_the_always_on_plugins_not_installed(self):
        import relay_setup
        proj = self._proj()
        self._registry({"front@amidman": [{"scope": "project", "projectPath": os.path.realpath(proj)}]})
        _, _, _, todo = relay_setup.setup(proj, install_runner=lambda r, k: (True, ""))
        named = lambda k: [t for t in todo if f"claude plugin install {k} --scope project" in t]
        # front is installed for this project; the other three are installed nowhere
        for k in ("relay@amidman", "observe@amidman", "delegate@amidman"):
            self.assertTrue(named(k), k)
        self.assertEqual(named("front@amidman"), [])

    def test_setup_install_failure_todo_names_the_command(self):
        import relay_setup
        self._registry({})
        proj = self._proj()
        _, _, done, todo = relay_setup.setup(proj, specs="openspec",
                                                install_runner=lambda root, key: (False, "no claude"))
        self.assertTrue([t for t in todo if "claude plugin install openspec@amidman --scope project" in t])
        self.assertFalse([d for d in done if "installed openspec@amidman" in d])

    def test_doctor_fixes_enabled_but_not_installed(self):
        import relay_setup
        self._registry({})
        proj = self._proj()
        relay_setup.setup(proj, specs="openspec", install_runner=lambda r, k: (False, ""))
        names = {n: ok for n, ok, _ in relay_setup.doctor(proj, profile={})}
        self.assertFalse(names["openspec@amidman installed"])
        self._registry({"openspec@amidman": [{"scope": "project", "projectPath": proj}]})
        names = {n: ok for n, ok, _ in relay_setup.doctor(proj, profile={})}
        self.assertTrue(names["openspec@amidman installed"])

    def test_doctor_checks_plugins_of_any_marketplace(self):
        import relay_setup
        self._registry({"other@mk": [{"scope": "user"}]})
        proj = self._proj()
        os.makedirs(os.path.join(proj, ".claude"))
        json.dump({"enabledPlugins": {"openspec@amidman": True, "superpowers@official": True, "other@mk": True, "x@y": False}},
                  open(os.path.join(proj, ".claude", "settings.json"), "w"))
        names = {n: ok for n, ok, _ in relay_setup.doctor(proj, profile={})}
        self.assertFalse(names["superpowers@official installed"])
        self.assertTrue(names["other@mk installed"])  # listed with user scope
        self.assertNotIn("x@y installed", names)  # disabled: no check

    def test_failure_todo_carries_reason_and_follows_marketplace_step(self):
        import relay_setup
        self._registry({})
        proj = self._proj()
        _, _, _, todo = relay_setup.setup(proj, specs="openspec",
                                             install_runner=lambda r, k: (False, "marketplace relay not found"))
        line = [i for i, t in enumerate(todo) if "claude plugin install openspec@amidman --scope project" in t]
        market = [i for i, t in enumerate(todo) if "/plugin marketplace add" in t]
        self.assertTrue(line and market)
        self.assertIn("marketplace relay not found", todo[line[0]])
        self.assertLess(market[0], line[0])

    def test_already_installed_does_not_call_runner(self):
        import relay_setup
        proj = self._proj()
        self._registry({"openspec@amidman": [{"scope": "project", "projectPath": os.path.realpath(proj)}]})
        def boom(r, k):
            raise AssertionError("runner called")
        _, _, done, _ = relay_setup.setup(proj, specs="openspec", install_runner=boom)
        self.assertIn("openspec@amidman already installed", done)

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
        ok, _ = relay_setup.run_plugin_install(root, "openspec@amidman")
        self.assertTrue(ok)
        lines = open(out).read().split("\n")
        self.assertEqual(lines[0], "plugin install openspec@amidman --scope project")
        self.assertEqual(os.path.realpath(lines[1]), root)
        self._fake_claude("echo boom >&2\nexit 1\n")
        self.assertEqual(relay_setup.run_plugin_install(root, "openspec@amidman"), (False, "boom"))
        os.environ["RELAY_CLAUDE_BIN"] = os.path.join(self.tmp, "missing")
        ok, why = relay_setup.run_plugin_install(root, "openspec@amidman")
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
                              env=env, cwd=cwd, capture_output=True, text=True, timeout=600)

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

    def test_new_kit_toml_has_no_observe_enabled(self):
        import relay_setup
        repo = self._repo()
        relay_setup.setup(repo)
        with open(os.path.join(repo, ".claude", "kit.toml"), encoding="utf-8") as handle:
            self.assertNotIn("enabled", handle.read().split("[observe]")[1].split("[")[0])

    def test_s3_plain_setup_still_writes_kit_toml_settings_and_readme(self):
        import relay_setup
        repo = self._repo()
        d, flow, done, todo = relay_setup.setup(repo)
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
            relay_setup.migrate(repo, apply=apply)
            self.assertTrue(os.path.isfile(os.path.join(repo, ".claude", "kit.toml")), apply)       # the rest of setup ran
            self.assertFalse(os.path.exists(os.path.join(repo, ".relay")), apply)
        relay_setup.setup(repo)                                      # relay setup of that one project does
        self.assertTrue(os.path.isfile(os.path.join(repo, ".relay", "README.md")))

    def test_q1_migrate_leaves_no_settings_entry_for_a_hook_it_moved_aside(self):
        """A hook script migrate moves aside (opsx-stage.sh) has no entry left in settings.json; a hook it leaves keeps its entry."""
        import relay_setup
        repo = self._repo()
        hooks = os.path.join(repo, ".claude", "hooks")
        os.makedirs(hooks)
        os.makedirs(os.path.join(repo, "bin"), exist_ok=True)   # migrate writes bin/kit and needs bin/ (a project with hooks has it)
        for name in ("opsx-stage.sh", "guard.sh"):
            with open(os.path.join(hooks, name), "w") as handle:
                handle.write("#!/bin/sh\n")
        group = lambda name: {"hooks": [{"type": "command", "command": f'"$CLAUDE_PROJECT_DIR"/.claude/hooks/{name}'}]}
        with open(os.path.join(repo, ".claude", "settings.json"), "w") as handle:
            json.dump({"hooks": {"UserPromptSubmit": [group("opsx-stage.sh")], "PreToolUse": [group("guard.sh")]}}, handle)
        relay_setup.migrate(repo, apply=True)
        self.assertFalse(os.path.exists(os.path.join(hooks, "opsx-stage.sh")))   # moved aside
        self.assertTrue(os.path.exists(os.path.join(hooks, "guard.sh")))          # left in place
        text = json.dumps(json.load(open(os.path.join(repo, ".claude", "settings.json")))["hooks"])
        self.assertNotIn("opsx-stage.sh", text)
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
    """relay is portable: the registry it ships names only global, and install imports nothing."""

    def test_shipped_registry_has_only_global(self):
        import relay_config
        data = relay_config.read_toml(os.path.join(ROOT, "defaults", "projects.toml"))
        self.assertEqual(sorted(data), ["global"])
        self.assertFalse(os.path.exists(os.path.join(ROOT, "projects.toml")))   # the registry is not a tracked file of relay

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


class RegistryLocation(Base):
    """With RELAY_PROJECTS unset the registry is <RELAY_HOME>/projects.toml, never a tracked file in relay's checkout."""

    def _fake_root(self):
        # Only LEGACY_PROJECTS (where the old registry sat) points at the fake checkout; the rest of relay stays real.
        root = os.path.join(self.tmp, "relay-checkout")
        os.makedirs(root)
        import relay_config
        patcher = mock.patch.object(relay_config, "LEGACY_PROJECTS", os.path.join(root, "projects.toml"))
        patcher.start()
        self.addCleanup(patcher.stop)
        return root

    def _repo(self):
        proj = os.path.join(self.tmp, "newproj")
        os.makedirs(proj)
        subprocess.run(["git", "init", "-q", proj], check=True)
        open(os.path.join(proj, "go.mod"), "w").write("module x\n")
        return proj

    def test_setup_without_relay_projects_writes_only_under_relay_home(self):
        root = self._fake_root()
        os.environ.pop("RELAY_PROJECTS")
        import relay_setup
        relay_setup.setup(self._repo())
        # The new entry is in the home registry; the checkout holds no projects.toml at all.
        registry = os.path.join(self.home, "projects.toml")
        self.assertIn("[newproj]", open(registry, encoding="utf-8").read())
        self.assertEqual(os.listdir(root), [])

    def test_old_registry_in_the_checkout_is_moved_once_with_a_line(self):
        root = self._fake_root()
        os.environ.pop("RELAY_PROJECTS")
        old = os.path.join(root, "projects.toml")
        with open(old, "w") as handle:
            handle.write('[global]\ntitle = "kept"\n')
        import io
        from contextlib import redirect_stderr
        import relay_config
        err = io.StringIO()
        with redirect_stderr(err):
            first = relay_config.projects_file()
            second = relay_config.projects_file()
        self.assertEqual(first, os.path.join(self.home, "projects.toml"))
        self.assertEqual(second, first)
        self.assertFalse(os.path.exists(old))
        self.assertIn('title = "kept"', open(first, encoding="utf-8").read())
        # One line, once: the second call finds nothing to move.
        lines = err.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1, err.getvalue())
        self.assertIn("moved the project registry", lines[0])


if __name__ == "__main__":
    unittest.main(verbosity=1)
