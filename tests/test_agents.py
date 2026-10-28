"""Library tests: agent files and the texts they carry."""
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # unittest from the repo root has only the root on sys.path
from relay_testbase import ROOT  # noqa: E402


class Agents(unittest.TestCase):
    def test_every_agent_has_a_turn_limit_and_judges_write_their_file_early(self):
        """Two Opus agents once ran out of turns with no report. Every agent file in every plugin carries maxTurns
        (a new agent without one fails here): Opus judges and thinkers 60 and must start the file early, Sonnet
        builders and fixers 80, the small lookup agents keep their own."""
        import glob
        import re
        files = sorted(glob.glob(os.path.join(ROOT, "plugins", "*", "agents", "*.md")))
        self.assertGreaterEqual(len(files), 10)   # 11 before the product plugin (its ui-reviewer agent) was removed
        for path in files:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            name = os.path.relpath(path, ROOT)
            front = text.split("---", 2)[1]
            turns = re.search(r"(?m)^maxTurns: (\d+)$", front)
            self.assertIsNotNone(turns, name + " has no maxTurns")
            model = re.search(r"(?m)^model: (\w+)$", front).group(1)
            if model == "opus":
                self.assertEqual(turns.group(1), "60", name)
                self.assertIn("within your first 10 tool calls", text, name)
                # a run cut short still leaves what was found: a thinker appends to its file, a judge records its input early and again
                self.assertTrue("append to it as you go" in text or "record again as you add findings" in text, name)
            elif model == "sonnet":
                self.assertEqual(turns.group(1), "80", name)

    def test_no_place_restates_the_old_loop(self):
        """A6 (part 1): the review is one review and a checked fix. No rule, base, skill or agent says the old loop
        (two passes, a third pass, debt), and each of the five review places names roles/judge.md."""
        import glob
        banned = ["over the fix range", "at most twice", "no third pass", "second pass", "tech debt", "technical debt",
                  "follow-up with an id", "follow-up id"]
        files = []
        for pattern in ("rules/*.md", "roles/*.md", "roles/parts/*.md", "plugins/*/skills/*/SKILL.md", "plugins/*/agents/*.md"):
            files += glob.glob(os.path.join(ROOT, pattern))
        self.assertGreater(len(files), 35)   # was 40 before the issues and product plugins (6 skills, 1 agent) were removed
        for path in sorted(files):
            with open(path, encoding="utf-8") as handle:
                text = handle.read().lower()
            for phrase in banned:
                self.assertNotIn(phrase, text, "%s still says %r" % (os.path.relpath(path, ROOT), phrase))
        places = ["rules/delegation.md", "plugins/delegate/skills/delegate/SKILL.md",
                  "plugins/openspec/skills/spec-review/SKILL.md"]
        for place in places:
            with open(os.path.join(ROOT, place), encoding="utf-8") as handle:
                self.assertIn("roles/judge.md", handle.read(), place + " does not name roles/judge.md")

    def test_project_rule_rating_belongs_to_the_judge(self):
        """A project rule reaches every agent that rates under it: in every judge-base agent the rating is the agent's
        own (a skill's severities are input), style is a finding when a project rule makes it one, and a finding a
        project rule raises gets its own reply line with the rule's label; the two judges that run a skill say so."""
        import glob
        import re
        def read(rel):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
                return " ".join(handle.read().split())
        agents = [p for p in sorted(glob.glob(os.path.join(ROOT, "plugins/*/agents/*.md")))
                  if "<!-- relay:base judge -->" in open(p, encoding="utf-8").read()]
        self.assertGreaterEqual(len(agents), 4)   # was 5 before the product plugin (ui-reviewer) was removed
        own_list_flows = ("plugins/openspec/agents/spec-reviewer.md", "plugins/openspec/agents/spec-conformance.md")
        for path in agents:
            text = read(os.path.relpath(path, ROOT))
            name = os.path.relpath(path, ROOT)
            self.assertIn("unless a project rule makes it one", text, name)
            self.assertIn("## The rating is yours", text, name)
            self.assertIn("carries the rule's label", text, name)
            self.assertIn("Every finding a project rule raises gets one line too (where, what, the rule's label)", text, name)
            # the reply section the agent actually emits: the shared one says the lines beyond the 10 belong to every
            # reply, and a flow that gives its own reply list names the project-rule line in that list
            reply = text[text.index("## Reply "):]
            self.assertIn("belong to every reply, a flow's own list included", reply, name)
            if "## Reply, in addition" in text:
                own = text[text.index("## Reply, in addition"):]
                own = re.split(r" ## (?!Reply, in addition)", own)[0]
                has_own_list = re.search(r"replaces the shared reply list|reply with at most 10|In the reply give", own)
                if name in own_list_flows:   # a rewording that hides the list must fail here, not skip
                    self.assertTrue(has_own_list, name + ": the flow's own reply list cannot be found")
                if has_own_list:
                    self.assertRegex(own, r"project rule\s+raises \(where, what, the rule's label\)", name + " own reply list")
        for flow in ("plugins/openspec/agents/spec-reviewer.md", "plugins/openspec/agents/spec-conformance.md"):
            self.assertIn("## Reply, in addition", read(flow), flow)
        self.assertIn("The skill does not see the project's rules", read("plugins/openspec/agents/spec-conformance.md"))
        conf = " ".join(read("plugins/openspec/agents/spec-conformance.md").split())
        self.assertIn("that cap counts only these CRITICAL and MISSING lines", conf)
        self.assertIn("beyond that and never inside the cap", conf)
        self.assertIn("is given once, as its labelled line beyond the cap", conf)

    def test_gate_runs_before_the_check_in_every_flow(self):
        """F3/F4/F6/F7: in each flow the order is fix, full gate (a log that starts with `head <sha>`), check; a flow
        with no gate says so; the global texts name relay's path for the judge base; an open finding inside the change
        is not deferred."""
        def read(rel):   # line breaks do not matter to the wording
            with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
                return " ".join(handle.read().split())
        writer = 'echo "head $(git -C <wt> rev-parse HEAD)"'
        delegate = read("plugins/delegate/skills/delegate/SKILL.md")
        self.assertIn(writer, delegate)
        self.assertIn("pipeline #<n> on <full sha> passed", delegate)
        self.assertLess(delegate.index("6. **Gate again.**"), delegate.index("7. **Check.**"))
        self.assertLess(delegate.index("3. **Gate before the review.**"), delegate.index("4. **One whole-change review.**"))
        # the checker side: the log form, the remote form and the no-gate form are all named, and agree with spec-review
        judge = read("roles/judge.md")
        self.assertIn("`head <full sha>`", judge)
        self.assertIn("pipeline #<n> on <full sha> passed", judge)
        self.assertIn("`Gate: none (artifacts only)`", judge)
        self.assertIn("outside `openspec/`", judge)   # a code fix with no gate is still open +1
        checker = read("plugins/delegate/agents/checker.md")
        spec = read("plugins/openspec/skills/spec-review/SKILL.md")
        self.assertIn("Gate: none (artifacts only)", spec)
        self.assertIn("writes no verdict", spec)
        self.assertIn("writes no verdict", checker)
        # review F9: the artifacts-only check writes plain text, so the skill names a .md report and reads it directly
        self.assertIn("spec-check.md", spec)
        self.assertNotIn("spec-check.json", spec)
        self.assertNotIn("relay check show <scratchpad>/review/spec-check", spec)
        self.assertIn("plain text file", checker)
        # F6: the global rule and the skills that run in other projects give relay's path, never a bare roles/judge.md
        for rel in ("rules/delegation.md", "plugins/delegate/skills/delegate/SKILL.md",
                    "plugins/openspec/skills/spec-review/SKILL.md"):
            text = read(rel)
            self.assertIn("~/relay/roles/judge.md", text, rel)
            self.assertEqual(text.count("roles/judge.md"), text.count("~/relay/roles/judge.md"), rel)

    def test_relay_changed(self):
        """A12: `relay changed -C <repo> <sha>` lists the changed files that are not inert, and follows the matcher:
        `*` stays inside one path part, `**` crosses parts."""
        tmp = tempfile.mkdtemp(prefix="relay-changed-")
        self.addCleanup(shutil.rmtree, tmp, True)
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)

        def git(*args):
            return subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *args],
                                  capture_output=True, text=True, check=True).stdout.strip()

        def write(rel, text):
            path = os.path.join(repo, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write(text)

        git("init", "-q")
        write("lib/a.py", "1\n")
        write("docs/handover.md", "1\n")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        base = git("rev-parse", "HEAD")
        write("lib/a.py", "2\n")
        write("docs/handover.md", "2\n")
        write("docs/handover.md.bak", "x\n")
        write(".relay/queue/x.md", "x\n")
        write(".relay/queue/deep/y.md", "y\n")
        write(".relay/checks/%s.json" % base, "{}\n")
        write(".relay/other.md", "z\n")
        git("add", "-A")
        git("commit", "-q", "-m", "change")
        env = dict(os.environ, RELAY_ROOT=ROOT)
        run = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "changed", "-C", repo, base],
                             capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 0, run.stderr)
        # not inert: the code, a sibling of the handover with another name, an unlisted .relay file
        self.assertEqual(sorted(run.stdout.split()), [".relay/other.md", "docs/handover.md.bak", "lib/a.py"])
        # nothing changed since HEAD: nothing listed
        run = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "changed", "-C", repo, "HEAD"],
                             capture_output=True, text=True, env=env)
        self.assertEqual((run.returncode, run.stdout), (0, ""))
        # the matcher itself
        sys.path.insert(0, os.path.join(ROOT, "lib"))
        import relay_inert
        self.assertTrue(relay_inert.matches(".relay/queue/a/b/c.md"))
        self.assertTrue(relay_inert.matches(".relay/checks/abc.json"))
        self.assertFalse(relay_inert.matches(".relay/queuex/a.md"))
        self.assertFalse(relay_inert.matches("sub/docs/handover.md"))
        # F1: a rename counts as delete + add, so code moved into an inert folder (or out of one) is listed
        write("lib/foo.py", "1\n")
        write("lib/\u00fc.py", "1\n")
        git("add", "-A")
        git("commit", "-q", "-m", "more")
        start = git("rev-parse", "HEAD")
        git("mv", "lib/foo.py", ".relay/queue/foo.py")
        git("mv", "docs/handover.md", "lib/h.py")
        write("lib/\u00fc.py", "2\n")
        write("docs/handover.md", "again\n")   # a new inert file, ignored
        write(".relay/checks/x.json", "{}\n")
        git("add", "-A")
        git("commit", "-q", "-m", "moves")
        self.assertEqual(relay_inert.changed(repo, start), ["lib/foo.py", "lib/h.py", "lib/\u00fc.py"])
        git("commit", "-q", "--allow-empty", "-m", "nothing")
        write("docs/handover.md", "3\n")
        write(".relay/checks/y.json", "{}\n")
        git("add", "-A")
        git("commit", "-q", "-m", "inert only")
        self.assertEqual(relay_inert.changed(repo, "HEAD~1"), [])
        self.assertTrue(relay_inert._regex("a/*/c").match("a/b/c"))
        self.assertFalse(relay_inert._regex("a/*/c").match("a/b/d/c"))
        self.assertTrue(relay_inert._regex("a/**/c").match("a/b/d/c"))
        self.assertTrue(relay_inert._regex("a/**/c").match("a/c"))

    def test_relay_changed_own(self):
        """A14: `relay changed --own` leaves out what only the default branch changed (design 7.2, the six rows of the
        worked values), and plain `changed` lists master's file for the same pair.

        Worked by hand. master M0 holds queue.py v1, inert.py v1, bin.txt (six lines), no foo item. The branch adds
        marks.py and merge.py (a) and fixes inert.py and the first line of bin.txt, and is checked there: X.
        Master then gains queue.py v2, the item foo.md and a change of bin.txt's last line. The branch edits merge.py
        (b), reverts inert.py to v1, and merges master: Y. For the pair X..Y:
          queue.py     v1 v1 v2 v2   only master changed it                   not own
          foo.md       inert                                                  not listed at all
          marks.py     not in the X..Y diff                                   not listed at all
          merge.py     none a none b  edited after X                          own
          inert.py     v1 fix v1 v1   at X the branch had touched it          own (a reverted checked fix)
          bin.txt      both sides changed, git combined them                  own"""
        tmp = tempfile.mkdtemp(prefix="relay-own-")
        self.addCleanup(shutil.rmtree, tmp, True)
        main = os.path.join(tmp, "main")
        wt = os.path.join(main, ".worktrees", "x")
        os.makedirs(main)

        def git(cwd, *args):
            return subprocess.run(["git", "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@t", *args],
                                  capture_output=True, text=True, check=True).stdout.strip()

        def write(cwd, rel, text):
            path = os.path.join(cwd, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write(text)

        git(main, "init", "-q", "-b", "master")
        write(main, ".gitignore", ".worktrees/\n")
        write(main, "lib/relay_queue.py", "v1\n")
        write(main, "lib/relay_inert.py", "v1\n")
        write(main, "bin/relay", "1\n2\n3\n4\n5\n6\n")
        git(main, "add", "-A")
        git(main, "commit", "-q", "-m", "M0")
        m0 = git(main, "rev-parse", "HEAD")
        git(main, "worktree", "add", "-q", wt, "-b", "wt/x")
        write(wt, "lib/relay_marks.py", "a\n")
        write(wt, "plugins/relay/hooks/merge.py", "a\n")
        write(wt, "lib/relay_inert.py", "v1 fixed\n")
        write(wt, "bin/relay", "1a\n2\n3\n4\n5\n6\n")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "checked work")
        x = git(wt, "rev-parse", "HEAD")
        write(main, "lib/relay_queue.py", "v2\n")
        write(main, ".relay/queue/foo.md", "item\n")
        write(main, "bin/relay", "1\n2\n3\n4\n5\n6a\n")
        git(main, "add", "-A")
        git(main, "commit", "-q", "-m", "master moves")
        write(wt, "plugins/relay/hooks/merge.py", "b\n")
        write(wt, "lib/relay_inert.py", "v1\n")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "after the check")
        git(wt, "merge", "-q", "--no-edit", "master")
        env = dict(os.environ, RELAY_ROOT=ROOT)

        def listed(*args):
            run = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "changed", "-C", wt, *args],
                                 capture_output=True, text=True, env=env)
            self.assertEqual(run.returncode, 0, run.stderr)
            return sorted(run.stdout.split())

        self.assertEqual(listed("--own", x, "HEAD"), ["bin/relay", "lib/relay_inert.py", "plugins/relay/hooks/merge.py"])
        self.assertEqual(listed("--own", x), ["bin/relay", "lib/relay_inert.py", "plugins/relay/hooks/merge.py"])   # until defaults to HEAD
        self.assertEqual(listed(x), ["bin/relay", "lib/relay_inert.py", "lib/relay_queue.py", "plugins/relay/hooks/merge.py"])
        # without a merge from master B_U = B_S: --own lists what plain changed lists
        self.assertEqual(listed("--own", m0, x), listed(m0, x))
        self.assertEqual(listed(m0, x), ["bin/relay", "lib/relay_inert.py", "lib/relay_marks.py", "plugins/relay/hooks/merge.py"])
        # no default branch: --own cannot tell and says so
        git(main, "branch", "-m", "master", "trunk2")
        git(main, "branch", "-m", "trunk2", "other")
        run = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "relay"), "changed", "-C", wt, "--own", x],
                             capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 1)
        self.assertIn("cannot tell the default branch", run.stderr)

    def test_role_names_are_not_agent_or_skill_names(self):
        """A13: a role file `.claude/kit/<role>.md` must not also be the per-agent or per-skill file of a served plugin
        (one file would serve both); the map plugins/relay/lib/agent-roles.tsv is what the agents' base markers say."""
        import glob
        sys.path.insert(0, os.path.join(ROOT, "lib"))
        import relay_roles
        roles = {os.path.basename(f)[:-3] for f in glob.glob(os.path.join(ROOT, "roles", "*.md"))}
        self.assertEqual(roles, {"lookup", "run", "build", "fix", "think", "judge"})
        served = {"relay", "openspec", "delegate", "front"}
        names = {}
        for kind, pattern in (("agent", "plugins/*/agents/*.md"), ("skill", "plugins/*/skills/*/SKILL.md")):
            for path in glob.glob(os.path.join(ROOT, pattern)):
                plugin = os.path.relpath(path, ROOT).split(os.sep)[1]
                if plugin in served:
                    stem = os.path.basename(path)[:-3] if kind == "agent" else os.path.basename(os.path.dirname(path))
                    names[stem] = kind + " " + plugin
        self.assertGreater(len(names), 15)
        for role in sorted(roles):
            self.assertNotIn(role, names, "role %s is also the name of %s" % (role, names.get(role)))
        with open(os.path.join(ROOT, relay_roles.MAP_FILE), encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        self.assertEqual(len(lines), len(glob.glob(os.path.join(ROOT, "plugins", "*", "agents", "*.md"))))
        for line in lines:
            self.assertRegex(line, r"^[a-z]+:[a-z-]+\t(lookup|run|build|fix|think|judge)$")
        self.assertEqual("".join(l + "\n" for l in lines), relay_roles.role_map(ROOT))


    def test_timeout_line_is_in_every_limits_carrier(self):
        """A runner wrapped a command in `timeout` and got exit 127 on macOS. Every agent that carries the Limits part
        says so (one shared source, roles/parts/limits.md), and the skill points at that recipe."""
        carriers = []
        for path in sorted(glob.glob(os.path.join(ROOT, "plugins", "*", "agents", "*.md"))):
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            if "<!-- relay:part limits -->" in text:
                carriers.append(path)
                self.assertIn("macOS has no `timeout` program", text, path)
                self.assertEqual(text.count("nohup <command>"), 1, path)
        self.assertGreaterEqual(len(carriers), 9)
        with open(os.path.join(ROOT, "roles", "parts", "limits.md"), encoding="utf-8") as handle:
            self.assertEqual(handle.read().count("macOS has no `timeout` program"), 1)
        with open(os.path.join(ROOT, "plugins/delegate/skills/delegate/SKILL.md"), encoding="utf-8") as handle:
            skill = handle.read()
        self.assertIn("macOS has no `timeout` program", skill)
        self.assertIn("Limits", skill)

    def test_timeout_free_recipe_runs(self):
        """The documented start line and wait loop, run on a 1-second job in a temp dir, end with its output and
        never call timeout."""
        with open(os.path.join(ROOT, "roles", "parts", "limits.md"), encoding="utf-8") as handle:
            lines = [l.strip() for l in handle.read().splitlines()]
        start = next(l for l in lines if l.startswith("cd <path> && mkdir -p <logs> && nohup"))
        wait = next(l for l in lines if l.startswith("i=0; while kill -0"))
        self.assertNotIn("timeout", start + wait)
        with tempfile.TemporaryDirectory() as tmp:
            start = start.replace("<path>", tmp).replace("<logs>", tmp + "/logs").replace("<command>", "sh -c 'echo hi; sleep 1'")
            out = subprocess.run(["sh", "-c", start], capture_output=True, text=True, check=True).stdout.split()[-1]
            wait = wait.replace("<pid>", out).replace("<logs>", tmp + "/logs")
            done = subprocess.run(["sh", "-c", wait], capture_output=True, text=True, check=True).stdout
            self.assertIn("hi", done)  # worked: the loop ended before 230 s and tailed the log


if __name__ == "__main__":
    unittest.main(verbosity=1)
