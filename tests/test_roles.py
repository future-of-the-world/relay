"""Library tests: roles and the texts they carry."""
import json
import os
import sys
import unittest

from relay_testbase import Base, ROOT


class Roles(Base):
    """Assembly of the role bases (lib/relay_roles.py) on fixture trees; the real agent files are checked at the end."""

    JUDGE = "---\nrole: judge\nneeds-tools: Read, Bash\nnever-tools: Edit\n---\nJudge body.\nTurns: {maxTurns}.\n"
    LIMITS = "## Limits\n- No long commands.\n"
    TESTS = "## Tests\n- Expected values by hand.\n"

    def fixture(self, agent_tools="Read, Bash", markers=None, max_turns=60):
        """A tree with roles/ and one agent plugins/x/agents/a.md; returns its root."""
        root = os.path.join(self.tmp, "fx")
        for sub in ("roles/parts", "plugins/x/agents", "rules"):
            os.makedirs(os.path.join(root, sub), exist_ok=True)
        files = {"roles/judge.md": self.JUDGE, "roles/parts/limits.md": self.LIMITS, "roles/parts/tests.md": self.TESTS,
                 "roles/build.md": "---\nrole: build\n---\nBuild.\n\n<!-- relay:include tests -->\n\nEnd.\n"}
        for name, text in files.items():
            with open(os.path.join(root, name), "w") as handle:
                handle.write(text)
        markers = markers if markers is not None else (
            "<!-- relay:base judge -->\nstale\n<!-- relay:end judge -->\n\nFlow text.\n\n"
            "<!-- relay:part limits -->\n<!-- relay:end limits -->\n")
        with open(os.path.join(root, "plugins/x/agents/a.md"), "w") as handle:
            handle.write("---\nname: a\ntools: %s\nmaxTurns: %d\n---\n\n%s" % (agent_tools, max_turns, markers))
        return root

    def agent(self, root):
        return os.path.join(root, "plugins/x/agents/a.md")

    def lib(self):
        import relay_roles
        return relay_roles

    def test_assembled_agents_are_current(self):
        """A1: assembly fills the regions (maxTurns of the agent, the include expanded, the frontmatter of the base
        stripped); a hand edit inside a region is reported with the file and the base; the real tree is current."""
        rr = self.lib()
        root = self.fixture(markers="<!-- relay:base judge -->\nstale\n<!-- relay:end judge -->\n\nFlow text.\n")
        self.assertEqual(rr.check(root), [(self.agent(root), "judge", "base")])
        rr.assemble(root)
        text = open(self.agent(root)).read()
        # worked out by hand: the base body, its {maxTurns} = 60 from this agent's frontmatter, between the markers
        want = "<!-- relay:base judge -->\nJudge body.\nTurns: 60.\n<!-- relay:end judge -->\n\nFlow text.\n"
        self.assertTrue(text.endswith(want), text)
        self.assertEqual(rr.check(root), [])
        with open(self.agent(root), "w") as handle:
            handle.write(text.replace("Judge body.", "Judge body, edited."))
        self.assertEqual(rr.check(root), [(self.agent(root), "judge", "base")])
        self.assertEqual(rr.describe(self.agent(root), "judge", root),
                         "plugins/x/agents/a.md: text in relay:base judge differs from roles/judge.md: "
                         "edit roles/judge.md, then run bin/relay sync agents from this checkout")
        # F5: an edit inside a part names the part and its file, and sync says which region of which file it rewrote
        root = self.fixture()   # an agent with a base and the limits part
        rr.assemble(root)
        with open(self.agent(root)) as handle:
            text = handle.read()
        with open(self.agent(root), "w") as handle:
            handle.write(text.replace("No long commands.", "Long commands are fine."))
        (found,) = rr.check(root)
        self.assertEqual(found, (self.agent(root), "limits", "part"))
        self.assertEqual(rr.describe(*found[:2], root, found[2]),
                         "plugins/x/agents/a.md: text in relay:part limits differs from roles/parts/limits.md: "
                         "edit roles/parts/limits.md, then run bin/relay sync agents from this checkout")
        self.assertEqual(rr.assemble_detail(root, dry=True), [(self.agent(root), [("part", "limits")])])
        self.assertEqual(rr.assemble_detail(root), [(self.agent(root), [("part", "limits")])])
        self.assertEqual(rr.check(root), [])
        # on the real tree a stale region fails with the describe() message, not a tuple
        self.assertEqual([rr.describe(p, n, ROOT, k) for p, n, k in rr.check(ROOT)], [])   # the real agent files are what their bases say
        with open(os.path.join(ROOT, rr.MAP_FILE), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), rr.role_map(ROOT))   # and the role map is what their markers say

    def test_assembly_writes_the_role_map(self):
        """F2: assembly writes plugins/core/lib/agent-roles.tsv (one line per marked agent, sorted), leaves it alone
        when current, leaves a stale one alone on a dry run, and writes none when the checkout has no core plugin."""
        rr = self.lib()
        root = self.fixture()
        self.assertFalse(os.path.exists(os.path.join(root, rr.MAP_FILE)))
        rr.assemble(root)
        self.assertFalse(os.path.exists(os.path.join(root, rr.MAP_FILE)))   # no plugins/core/lib: no map
        os.makedirs(os.path.join(root, "plugins/core/lib"))
        with open(os.path.join(root, "plugins/x/agents/b.md"), "w") as handle:
            handle.write("---\nname: b\nmaxTurns: 80\n---\n\n<!-- relay:base build -->\n<!-- relay:end build -->\n")
        mapfile = os.path.join(root, rr.MAP_FILE)
        rr.assemble(root, dry=True)
        self.assertFalse(os.path.exists(mapfile))   # dry: nothing written
        rr.assemble(root)
        with open(mapfile) as handle:
            self.assertEqual(handle.read(), "x:a\tjudge\nx:b\tbuild\n")
        before = (open(mapfile).read(), os.stat(mapfile).st_mtime_ns)
        rr.assemble(root)
        self.assertEqual((open(mapfile).read(), os.stat(mapfile).st_mtime_ns), before)   # current: untouched
        with open(mapfile, "w") as handle:
            handle.write("stale\n")
        rr.assemble(root, dry=True)
        with open(mapfile) as handle:
            self.assertEqual(handle.read(), "stale\n")
        rr.assemble(root)
        with open(mapfile) as handle:
            self.assertEqual(handle.read(), "x:a\tjudge\nx:b\tbuild\n")

    def test_include_is_expanded_one_level(self):
        rr = self.lib()
        root = self.fixture(markers="<!-- relay:base build -->\n<!-- relay:end build -->\n")
        rr.assemble(root)
        self.assertIn("Build.\n\n## Tests\n- Expected values by hand.\n\nEnd.\n", open(self.agent(root)).read())
        with open(os.path.join(root, "roles/parts/tests.md"), "a") as handle:
            handle.write("<!-- relay:include limits -->\n")
        with self.assertRaises(rr.RolesError) as caught:
            rr.assemble(root)
        self.assertIn("includes are one level", str(caught.exception))

    def test_every_agent_has_one_base(self):
        """A2 on fixtures: no base, two bases, an unknown base or part, unbalanced, nested and wrongly closed markers."""
        rr = self.lib()
        cases = {
            "none": ("<!-- relay:part limits -->\n<!-- relay:end limits -->\n", "0 relay:base regions"),
            "two": ("<!-- relay:base judge -->\n<!-- relay:end judge -->\n<!-- relay:base build -->\n<!-- relay:end build -->\n", "2 relay:base regions"),
            "unknown base": ("<!-- relay:base nope -->\n<!-- relay:end nope -->\n", "roles/nope.md missing"),
            "unknown part": ("<!-- relay:base judge -->\n<!-- relay:end judge -->\n<!-- relay:part nope -->\n<!-- relay:end nope -->\n", "roles/parts/nope.md missing"),
            "unclosed": ("<!-- relay:base judge -->\ntext\n", "never closed"),
            "stray end": ("<!-- relay:end judge -->\n", "no open marker"),
            "nested": ("<!-- relay:base judge -->\n<!-- relay:part limits -->\n<!-- relay:end limits -->\n<!-- relay:end judge -->\n", "no nesting"),
            "wrong end": ("<!-- relay:base judge -->\n<!-- relay:end build -->\n", "closes region 'judge'"),
        }
        for label, (markers, message) in cases.items():
            root = self.fixture(markers=markers)
            found = " | ".join(rr.problems(root))
            self.assertIn(message, found, label)
        root = self.fixture(markers="<!-- relay:base judge -->\n<!-- relay:end judge -->\n")
        self.assertEqual(rr.problems(root), [])
        self.assertEqual(rr.problems(self.fixture(markers="no markers at all\n")), [])
        self.assertIn("no relay:base region", " ".join(rr.problems(self.fixture(markers="no markers at all\n"), require_base=True)))

    def test_base_tools(self):
        """A3: a judge whose tools lack Bash, or hold Edit, is reported."""
        rr = self.lib()
        marker = "<!-- relay:base judge -->\n<!-- relay:end judge -->\n"
        self.assertEqual(rr.problems(self.fixture(agent_tools="Read, Bash, Grep", markers=marker)), [])
        self.assertIn("tools lack Bash", " ".join(rr.problems(self.fixture(agent_tools="Read, Grep", markers=marker))))
        self.assertIn("tools hold Edit", " ".join(rr.problems(self.fixture(agent_tools="Read, Bash, Edit", markers=marker))))

    def test_base_placeholders(self):
        """A4: only {maxTurns} is a placeholder, in bases, parts and (after assembly) never in an agent file."""
        rr = self.lib()
        root = self.fixture(markers="<!-- relay:base judge -->\n<!-- relay:end judge -->\n")
        self.assertEqual(rr.problems(root), [])
        with open(os.path.join(root, "roles/parts/limits.md"), "a") as handle:
            handle.write("Wait {seconds} seconds.\n")
        self.assertIn("placeholder {seconds}", " ".join(rr.problems(root)))
        rr.assemble(root)
        self.assertNotIn("{maxTurns}", open(self.agent(root)).read())
        with open(self.agent(root), "a") as handle:
            handle.write("\nleft {maxTurns} outside a region\n")
        self.assertIn("holds {maxTurns} after assembly", " ".join(rr.problems(root)))
        # the real bases and parts hold no other placeholder
        self.assertEqual([p for p in rr.problems(ROOT) if "placeholder" in p], [])

    def test_assembly_touches_only_source(self):
        """A5: a fake installed copy (registered in the config dir) and a bench candidate's copy stay as they are."""
        rr = self.lib()
        root = self.fixture(markers="<!-- relay:base judge -->\nstale\n<!-- relay:end judge -->\n")
        copies = [os.path.join(self.claude, "plugins", "cache", "x"), os.path.join(root, "profiles", "candidates", "c", "plugins", "x")]
        for copy in copies:
            os.makedirs(os.path.join(copy, "agents"))
            with open(os.path.join(copy, "agents", "a.md"), "w") as handle:
                handle.write("---\nname: a\nmaxTurns: 60\n---\n<!-- relay:base judge -->\nstale\n<!-- relay:end judge -->\n")
        with open(os.path.join(self.claude, "plugins", "installed_plugins.json"), "w") as handle:
            json.dump({"plugins": {"x@relay": [{"installPath": copies[0]}]}}, handle)
        before = [open(os.path.join(c, "agents", "a.md")).read() for c in copies]
        self.assertEqual(rr.assemble(root), [self.agent(root)])
        self.assertEqual([open(os.path.join(c, "agents", "a.md")).read() for c in copies], before)

    def test_sync_agents_writes_only_this_checkout(self):
        """A7: with RELAY_ROOT a fixture copy, sync(only={"agents"}) writes inside its plugins/*/agents and nowhere else
        (no CLAUDE.md in the config dir, nothing else in the fixture)."""
        root = self.fixture(markers="<!-- relay:base judge -->\nstale\n<!-- relay:end judge -->\n")
        os.environ["RELAY_ROOT"] = root
        for m in list(sys.modules):
            if m.startswith("relay_"):
                del sys.modules[m]
        import relay_rules

        def snapshot(folder, skip):
            seen = {}
            for here, _, names in os.walk(folder):
                for name in names:
                    path = os.path.join(here, name)
                    if not path.startswith(skip):
                        seen[path] = open(path, "rb").read()
            return seen
        skip = os.path.join(root, "plugins", "x", "agents")
        before_root, before_claude = snapshot(root, skip), snapshot(self.claude, "")
        results = relay_rules.sync({}, only={"agents"})
        self.assertEqual(snapshot(root, skip), before_root)
        self.assertEqual(snapshot(self.claude, ""), before_claude)
        self.assertFalse(os.path.exists(os.path.join(self.claude, "CLAUDE.md")))
        self.assertIn("Judge body.", open(self.agent(root)).read())
        self.assertEqual(results[-1][2], "assembled 1, set model/effort in 0")

    def test_dry_sync_counts_agents(self):
        """A8: --dry says how many agent files it would assemble and how many get model/effort, and writes nothing."""
        root = self.fixture(markers="<!-- relay:base judge -->\nstale\n<!-- relay:end judge -->\n")
        with open(self.agent(root), "a") as handle:
            handle.write("")
        text = open(self.agent(root)).read().replace("maxTurns: 60\n", "maxTurns: 60\nrelay-tier: fix\nmodel: opus\n")
        with open(self.agent(root), "w") as handle:
            handle.write(text)
        with open(os.path.join(root, "plugins/x/agents/b.md"), "w") as handle:    # no markers, a tier whose model differs
            handle.write("---\nname: b\nrelay-tier: fix\nmodel: opus\n---\nPlain.\n")
        os.environ["RELAY_ROOT"] = root
        for m in list(sys.modules):
            if m.startswith("relay_"):
                del sys.modules[m]
        import relay_rules
        before = open(self.agent(root)).read()
        profile = {"models": {"fix": "sonnet"}}
        # worked out by hand: a.md has a stale region (1 to assemble); a.md and b.md both have tier fix on opus, profile says sonnet (2 to set)
        self.assertEqual(relay_rules.sync(profile, only={"agents"}, dry=True)[-1][2], "would assemble 1, would set model/effort in 2")
        self.assertEqual(open(self.agent(root)).read(), before)

    def test_assembly_is_idempotent(self):
        """A9: a second run changes nothing; one run restores an edited region."""
        rr = self.lib()
        root = self.fixture()
        rr.assemble(root)
        once = open(self.agent(root)).read()
        self.assertEqual(rr.assemble(root), [])
        self.assertEqual(open(self.agent(root)).read(), once)
        with open(self.agent(root), "w") as handle:
            handle.write(once.replace("No long commands.", "Edited."))
        self.assertEqual(rr.assemble(root), [self.agent(root)])
        self.assertEqual(open(self.agent(root)).read(), once)

    def test_every_real_agent_has_one_base(self):
        """A2 on the real tree: every agent file of every plugin has exactly one relay:base region, known parts and the tools
        its base needs; the bases of the 11 agents are the ones the design names (the checker is a judge)."""
        rr = self.lib()
        self.assertEqual(rr.problems(ROOT, require_base=True), [])
        by_base = {}
        for path in rr.agent_files(ROOT):
            text = open(path).read()
            base = [r["name"] for r in rr.parse_regions(text) if isinstance(r, dict) and r["kind"] == "base"][0]
            by_base.setdefault(base, []).append(os.path.relpath(path, ROOT))
        self.assertEqual(by_base, {
            "lookup": ["plugins/delegate/agents/scout.md"],
            "run": ["plugins/delegate/agents/runner.md"],
            "build": ["plugins/delegate/agents/worker.md"],
            "fix": ["plugins/delegate/agents/fixer.md"],
            "think": ["plugins/delegate/agents/thinker.md", "plugins/openspec/agents/author.md"],
            "judge": ["plugins/delegate/agents/checker.md", "plugins/delegate/agents/critic.md",
                      "plugins/openspec/agents/spec-conformance.md", "plugins/openspec/agents/spec-reviewer.md",
                      "plugins/product/agents/ui-reviewer.md"]})

    def test_judges_cannot_edit_and_check_mode_does_not_need_part_two(self):
        """The judge base forbids Edit tools (A3) and names no part-2 thing as a given: marks, merge refusal and queue
        items appear only as 'when the project has' them. A judge that gained Edit, or a base that states a queue as fact, fails."""
        rr = self.lib()
        for path in rr.agent_files(ROOT):
            text = open(path).read()
            meta, _ = rr.split_frontmatter(text)
            if "relay:base judge" in text:
                for tool in ("Edit", "MultiEdit", "NotebookEdit"):
                    self.assertNotIn(tool, [x.strip() for x in meta["tools"].split(",")], path)
        judge = open(os.path.join(ROOT, "roles", "judge.md")).read()
        flat = " ".join(judge.split())
        self.assertIn("When the record has a `Q1`, it is `MET` only when", flat)   # the queue appears only as a record's Q1, never as a given
        # review F8: the owner's move is data (an owner entry with `queue`), not a `Owner: <id> moved to queue item` prompt line
        self.assertIn("a finding the owner moved to a queue item is data: an `owner` entry with `queue`", flat)
        self.assertNotIn("Owner: <id> moved to queue item", flat)
        self.assertIn("relay changed -C <path> <sha>` lists no file", flat)
        checker = open(os.path.join(ROOT, "plugins", "delegate", "agents", "checker.md")).read()
        self.assertIn("where the project has check marks", " ".join(checker.split()))

    def test_judge_base_part2(self):
        """A15: the judge base names `relay changed --own` in check step 1 and the linter line in "Each finding"; the
        checker's flow part and the delegate skill name `relay gate`."""
        judge = " ".join(open(os.path.join(ROOT, "roles", "judge.md")).read().split())
        self.assertIn("List the files with `relay changed --own -C <path> <since>`", judge)
        each = judge[judge.index("## Each finding"):judge.index("## The rating is yours")]
        self.assertIn("<path>:<line>: <SEVERITY>: F<n> <what goes wrong>", each)
        self.assertIn("relay changed -C <path> <sha>` lists no file", judge)     # the gate rule has no --own
        self.assertIn("F2 MET tests/test_inert.py:88", judge)
        # F5: agents without Write get a quoted heredoc, never an unquoted one, in the base and in every synced copy
        self.assertIn("with a quoted heredoc `cat > <file> <<'EOF'` when you have no Write tool", judge)
        rr = self.lib()
        for path in rr.agent_files(ROOT):
            text = " ".join(open(path).read().split())
            if "relay:base judge" in text:
                self.assertIn("with a quoted heredoc `cat > <file> <<'EOF'` when you have no Write tool", text, path)
        checker = " ".join(open(os.path.join(ROOT, "plugins", "delegate", "agents", "checker.md")).read().split())
        self.assertIn("written by `relay gate`", checker)
        self.assertIn("never `Brief: <file>`", checker)
        skill = " ".join(open(os.path.join(ROOT, "plugins", "delegate", "skills", "delegate", "SKILL.md")).read().split())
        self.assertIn("runs `relay gate`", skill)
        self.assertIn("never `git rebase`", skill)
        self.assertIn("`relay check show <branch>`", skill)
        front = " ".join(open(os.path.join(ROOT, "plugins", "front", "skills", "front", "SKILL.md")).read().split())
        self.assertIn("## A change ready to merge", front)
        self.assertIn("No page and no Artifact", front)
        self.assertNotIn("relay check page", front)
        # F1: no text describes the removed page as printing the owner's words
        self.assertNotIn("and the page print", skill)
        # F2: the main review point has a named source, the critic's hand-back
        self.assertIn("main review point is the critic's hand-back line on the finding that matters most", front)
        self.assertNotIn("the runner also names the main review point", front)

    def test_a_job_longer_than_a_runner_s_turns_runs_in_the_front_s_background(self):
        """A runner (12 turns, waits of at most 230 s) covers about 40 min; the full paid bin/ci takes 38-47 min and
        the runner ran out of turns mid-wait four times. The front starts such a job itself, in the background."""
        front = " ".join(open(os.path.join(ROOT, "plugins", "front", "skills", "front", "SKILL.md")).read().split())
        self.assertIn("`run_in_background`", front)
        self.assertIn("full paid `bin/ci`", front)
        self.assertIn("never a runner", front)
        delegate = " ".join(open(os.path.join(ROOT, "plugins", "delegate", "skills", "delegate", "SKILL.md")).read().split())
        self.assertIn("longer than about 30 minutes", delegate)
        self.assertIn("is not a runner's", delegate)
        for name in ("delegation", "front"):
            rule = " ".join(open(os.path.join(ROOT, "rules", name + ".md")).read().split())
            self.assertIn("is the front's: Bash `run_in_background`", rule, name)
            self.assertIn("a job over about 30 minutes", rule if name == "delegation" else rule.replace("A job", "a job"), name)

    def test_missing_base_names_the_checkout_rule(self):
        rr = self.lib()
        root = self.fixture(markers="<!-- relay:base judge -->\n<!-- relay:end judge -->\n")
        os.remove(os.path.join(root, "roles", "judge.md"))
        with self.assertRaises(rr.RolesError) as caught:
            rr.assemble(root)
        self.assertEqual(str(caught.exception), "roles/judge.md missing (run from the checkout that has roles/)")


if __name__ == "__main__":
    unittest.main(verbosity=1)
