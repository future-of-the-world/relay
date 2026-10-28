"""Spec steps are opt-in steps around relay's one change cycle; the plugin once named `sdd` is named `openspec`.

Every case runs on scratch folders (no network, nothing under ~ or the repo): the design is
docs/flows.md and the queue item spec-writing-leaves-the-main-pipeline-sdd-become (Q1 below)."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relay_testbase import load_hook  # noqa: E402
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
OLD = "sd" + "d"   # the old plugin name, written so that this file's own text stays readable to the scan below

KIT_TOML = """[project]
name = "{name}"
default_branch = "master"
worktrees = ".worktrees"

[gate]
wt = "bin/wt"
check = "bin/check"
ci = "bin/ci"
ci_log = ".ci/ci.log"
{extra}"""


class Scratch(unittest.TestCase):
    """A temp dir, with the environment variables relay reads pointed into it and restored afterwards."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="spec-steps-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.claude = os.path.join(self.tmp, "claude")
        os.makedirs(self.claude)
        self.projects = os.path.join(self.tmp, "projects.toml")
        self.write(self.projects, '[global]\nfile = "%s"\ntitle = "T"\nload = []\nskip = ["openspec"]\n' % os.path.join(self.tmp, "g", "CLAUDE.md"))
        for key, value in (("CLAUDE_CONFIG_DIR", self.claude), ("RELAY_PROJECTS", self.projects), ("RELAY_HOME", os.path.join(self.tmp, "home"))):
            self.setenv(key, value)
        import relay_rules
        import relay_setup
        self.rules, self.setup = relay_rules, relay_setup

    def setenv(self, key, value):
        old = os.environ.get(key)
        os.environ[key] = value
        self.addCleanup(lambda: os.environ.pop(key, None) if old is None else os.environ.__setitem__(key, old))

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def project(self, name, specs=None, extra="", openspec_dir=False, old_flow=None):
        """A git folder with a kit.toml; `specs` writes [specs] method, `old_flow` writes the old [flow] forms."""
        root = os.path.join(self.tmp, name)
        os.makedirs(root)
        subprocess.run(["git", "init", "-q", root], check=True, env=GIT_ENV)
        body = KIT_TOML.format(name=name, extra=extra)
        if old_flow:
            body += old_flow
        if specs is not None:
            body += '\n[specs]\nmethod = "%s"\n' % specs
        self.write(os.path.join(root, ".claude", "kit.toml"), body)
        if openspec_dir:
            self.write(os.path.join(root, "openspec", "specs", "a", "spec.md"), "# a\n")
        return root

    def render(self, root, load=(), read=()):
        spec = {"file": os.path.join(root, "CLAUDE.local.md"), "load": list(load), "read": list(read)}
        return self.rules.render_target(os.path.basename(root), spec, self.rules.rules(), {})

    def registry(self, entries):
        self.write(os.path.join(self.claude, "plugins", "installed_plugins.json"), json.dumps({"version": 2, "plugins": entries}))

    def registry_entries(self):
        with open(os.path.join(self.claude, "plugins", "installed_plugins.json"), encoding="utf-8") as handle:
            return json.load(handle)["plugins"]

    def runners(self, root):
        """(calls, install, uninstall): fake runners that keep the scratch registry as Claude Code would."""
        calls = []

        def install(r, key):
            calls.append(("install", key))
            entries = self.registry_entries() if os.path.isfile(os.path.join(self.claude, "plugins", "installed_plugins.json")) else {}
            entries.setdefault(key, []).append({"scope": "project", "projectPath": os.path.realpath(r)})
            self.registry(entries)
            return True, ""

        def uninstall(r, key):
            calls.append(("uninstall", key))
            entries = self.registry_entries()
            entries[key] = [e for e in entries.get(key, []) if os.path.realpath(e.get("projectPath", "")) != os.path.realpath(r)]
            self.registry({k: v for k, v in entries.items() if v})
            return True, ""
        return calls, install, uninstall

    def run_setup(self, root, **kw):
        calls, install, uninstall = getattr(self, "_calls", None) or self.runners(root)
        self._calls = (calls, install, uninstall)
        self.setup.setup(root, relay_dir=False, install_runner=install, uninstall_runner=uninstall, **kw)
        return calls

    def tree_hash(self, folder):
        digest = hashlib.sha256()
        for base, dirs, files in sorted(os.walk(folder)):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(base, name)
                digest.update(os.path.relpath(path, folder).encode() + open(path, "rb").read())
        return digest.hexdigest()


# --- case 1 and 12: no live old name ------------------------------------------------------------------------------

# Paths that keep an old name on purpose, each with its reason (a new entry needs one).
EXEMPT = (
    ("evals/plugin/", "recorded/", "recorded model outputs: rewriting them falsifies the record"),
    ("evals/judge-measure/", "/judged/", "recorded model outputs: rewriting them falsifies the record"),
    ("evals/plugin/baseline/aggregate-result.json", "", "recorded model outputs: rewriting them falsifies the record"),
    ("lib/relay_old_names.toml", "", "the migration must name the old forms to find them; they live in this one data file"),
    ("tests/test_spec_steps.py", "", "writes the old forms into scratch projects to test the migration"),
    ("docs/handover.md", "", "dated history; the front rewrites the current-state lines"),
    ("docs/plans/", "", "dated history"),
    (".relay/", "", "dated records of the work queue and the gates; they quote the owner's words and the old names they describe"),
)


def exempt(path, text):
    if text.lstrip().startswith(">"):   # a markdown quote line: the owner's words stay verbatim
        return True
    for prefix, inside, _why in EXEMPT:
        if path.startswith(prefix) and inside in path:
            return True
    return False


def grep_tree(args):
    out = subprocess.run(["git", "-C", ROOT, "grep", "-nI"] + args + ["--", "."], capture_output=True, text=True, env=GIT_ENV).stdout
    found = []
    for line in out.splitlines():
        path, _, rest = line.partition(":")
        _n, _, text = rest.partition(":")
        if not exempt(path, text):
            found.append(line[:200])
    return found


class NoOldName(unittest.TestCase):
    def test_no_live_old_plugin_name_in_the_tree(self):
        # The word `sdd` (as a whole word) is named nowhere but in the exempt places.
        self.assertEqual(grep_tree(["-w", OLD]), [])

    def test_exemptions_each_carry_a_reason_and_the_scan_can_fail(self):
        self.assertTrue(all(why for _p, _i, why in EXEMPT))
        self.assertFalse(exempt("plugins/openspec/skills/plan/SKILL.md", "use " + OLD + ":worker"))   # a live use is found
        self.assertFalse(exempt("plugins/openspec/flow.json", '"kind": "' + OLD + '"'))
        self.assertTrue(exempt("docs/design.md", "> " + OLD + " is OpenSpec"))                          # a quote line is not
        self.assertTrue(exempt("lib/relay_old_names.toml", OLD + "@relay"))                              # the data file is not

    def test_nothing_names_the_old_orchestrator_skill(self):
        self.assertEqual(grep_tree(["-l", "openspec-apply-orchestrator"]), [])


# --- cases 2, 3, 4 and Q1: what a project's rules carry -----------------------------------------------------------

class RenderedRules(Scratch):
    def test_global_target_carries_no_openspec_rule(self):
        self.setenv("RELAY_PROJECTS", os.path.join(ROOT, "projects.toml"))
        spec = self.rules.targets()["global"]
        text = self.rules.render_target("global", spec, self.rules.rules(), {})
        self.assertNotIn("rules/openspec.md", text)   # neither in full nor in the "read when they apply" list
        self.assertNotIn("## OpenSpec", text)
        for method in self.rules.spec_methods():
            self.assertIn(method, spec["skip"])   # every spec method's rule is skipped globally

    def test_project_with_specs_off_or_unset_gets_none_of_it(self):
        for name, specs in (("off", "none"), ("unset", None)):
            text = self.render(self.project(name, specs=specs, openspec_dir=True))
            for word in ("## OpenSpec", "openspec:", "Spec steps in the change cycle"):
                self.assertNotIn(word, text, name)
            # a project with no explicit `read` list does not get the rule in its "read when they apply" list either
            spec = {"file": os.path.join(self.tmp, name, "CLAUDE.local.md"), "load": []}
            self.assertNotIn("rules/openspec.md", self.rules.render_target(name, spec, self.rules.rules(), {}))

    def test_q1_without_spec_steps_no_openspec_rule_and_with_them_the_steps(self):
        # Q1 of spec-writing-leaves-the-main-pipeline-sdd-become. Failing case: ~/.claude/CLAUDE.md told every project
        # "A behaviour change goes through an OpenSpec change before code". Pass: the global text and a project
        # without spec steps have no OpenSpec rule and no spec step; a project that turns them on gets them.
        self.setenv("RELAY_PROJECTS", os.path.join(ROOT, "projects.toml"))
        global_text = self.rules.render_target("global", self.rules.targets()["global"], self.rules.rules(), {})
        without = self.render(self.project("plain"))
        for text in (global_text, without):
            self.assertNotIn("goes through an OpenSpec change before code", text)
            self.assertNotIn("openspec:plan", text)
        # a project that turns the steps on gets them from the openspec plugin's hook (tests/test_openspec_hook.py), not from sync
        self.assertNotIn("openspec:plan", self.render(self.project("steps", specs="openspec")))

    def test_stored_spec_rule_is_refused_and_setup_removes_it(self):
        root = self.project("alpha", specs="openspec")
        self.write(self.projects, open(self.projects, encoding="utf-8").read()
                   + '\n[alpha]\nfile = "%s"\ntitle = "T"\nload = ["openspec", "quality-gate"]\nread = []\n' % os.path.join(root, "CLAUDE.local.md"))
        results = self.rules.sync({}, only={"alpha"}, dry=True)
        self.assertTrue(self.rules.refused(results), results)   # sync stops naming the entry
        self.assertIn("spec rules come from kit.toml [specs]", results[0][2])
        with mock.patch.object(self.setup, "dep_checks", lambda: []):
            names = {n: (ok, detail) for n, ok, detail in self.setup.doctor(root, profile={})}
        self.assertFalse(names["no stored spec rule in projects.toml"][0])   # doctor names it
        self.assertIn("load names openspec", names["no stored spec rule in projects.toml"][1])
        self.run_setup(root, specs="none")
        with open(self.projects, "rb") as handle:
            self.assertEqual(tomllib.load(handle)["alpha"]["load"], ["quality-gate"])
        self.assertNotIn("## OpenSpec", self.render(root, load=["quality-gate"]))


# --- cases 5 and 6: plugins and turning the steps on and off ------------------------------------------------------

class TurnOnAndOff(Scratch):
    def test_plugins_follow_the_specs_setting(self):
        self.assertIn("openspec", self.setup.relay_plugins_for("openspec"))
        self.assertNotIn("openspec", self.setup.relay_plugins_for("none"))
        self.assertNotIn("no-such-method", self.setup.relay_plugins_for("no-such-method"))

    def test_specs_on_then_off_adds_then_removes_the_plugin_and_leaves_the_folder(self):
        root = self.project("beta", openspec_dir=True)
        before = self.tree_hash(os.path.join(root, "openspec"))
        calls = self.run_setup(root, specs="openspec")
        settings = json.load(open(os.path.join(root, ".claude", "settings.json")))
        self.assertTrue(settings["enabledPlugins"]["openspec@amidman"])
        self.assertEqual(calls, [("install", "openspec@amidman")])
        self.assertIn('method = "openspec"', open(os.path.join(root, ".claude", "kit.toml")).read())
        self.run_setup(root, specs="none")
        settings = json.load(open(os.path.join(root, ".claude", "settings.json")))
        self.assertIs(settings["enabledPlugins"]["openspec@amidman"], False)   # turned off: kept as false, not deleted (design T6)
        self.assertEqual(calls, [("install", "openspec@amidman"), ("uninstall", "openspec@amidman")])
        self.assertIn('method = "none"', open(os.path.join(root, ".claude", "kit.toml")).read())
        self.assertEqual(self.tree_hash(os.path.join(root, "openspec")), before)   # byte for byte

    def test_a_project_found_with_an_openspec_folder_gets_the_steps_on_and_is_told(self):
        # The owner's decision (24 Oct, "2. b"): found with openspec/ and no [specs]: on; turning off is explicit.
        root = self.project("gamma", openspec_dir=True)
        os.remove(os.path.join(root, ".claude", "kit.toml"))
        d, flow, done, todo = self.setup.setup(root, relay_dir=False,
                                                          install_runner=self.runners(root)[1])
        self.assertIn('method = "openspec"', open(os.path.join(root, ".claude", "kit.toml")).read())
        told = [line for line in done if "spec steps are ON" in line]
        self.assertEqual(len(told), 1)
        self.assertIn("--specs none", told[0])
        # explicitly off stays off on the next setup
        self.setup.setup(root, specs="none", relay_dir=False, install_runner=self.runners(root)[1])
        again = self.setup.setup(root, relay_dir=False, install_runner=self.runners(root)[1])
        self.assertIn('method = "none"', open(os.path.join(root, ".claude", "kit.toml")).read())
        self.assertFalse([line for line in again[3] if "spec steps are ON" in line])


# --- case 7: the migration -----------------------------------------------------------------------------------------

class Migration(Scratch):
    def test_old_flow_binding_becomes_specs_and_a_second_run_changes_nothing(self):
        root = self.project("zeta", old_flow='\n[flow]\nkind = "openspec"\nplugin = "%s"\n' % OLD)
        self.write(os.path.join(root, ".claude", "settings.json"), json.dumps({"enabledPlugins": {OLD + "@relay": True}}))
        self.registry({OLD + "@relay": [{"scope": "project", "projectPath": root}]})
        calls = self.run_setup(root)
        cfg = tomllib.load(open(os.path.join(root, ".claude", "kit.toml"), "rb"))
        self.assertEqual(cfg["flow"]["kind"], "none")
        self.assertNotIn("plugin", cfg["flow"])
        self.assertEqual(cfg["specs"]["method"], "openspec")   # the project had the steps on; it keeps them
        enabled = json.load(open(os.path.join(root, ".claude", "settings.json")))["enabledPlugins"]
        self.assertTrue(enabled["openspec@amidman"])
        self.assertNotIn(OLD + "@relay", enabled)
        self.assertEqual(calls, [("uninstall", OLD + "@relay"), ("install", "openspec@amidman")])
        snapshot = {f: open(os.path.join(root, f), "rb").read() for f in (".claude/kit.toml", ".claude/settings.json")}
        calls.clear()
        self.run_setup(root)
        self.assertEqual({f: open(os.path.join(root, f), "rb").read() for f in snapshot}, snapshot)
        self.assertEqual(calls, [])

    def test_old_names_file_passes_its_schema_check_and_a_bad_one_fails(self):
        data = self.setup.load_old_names()
        self.assertEqual(data["plugin_key"][OLD + "@relay"], "openspec@amidman")
        bad = os.path.join(self.tmp, "bad.toml")
        self.write(bad, '[plugin_key]\n"x" = "y"\n')
        with self.assertRaises(ValueError):
            self.setup.load_old_names(bad)


# --- case 8: migration_plan ---------------------------------------------------------------------------------------

class MigrationPlan(Scratch):
    def plan(self, specs):
        root = self.project("p", specs=specs, openspec_dir=True)
        for agent in ("worker", "spec-reviewer"):
            self.write(os.path.join(root, ".claude", "agents", "p-%s.md" % agent), "x\n")
        for skill in ("apply-review", "plan"):
            self.write(os.path.join(root, ".claude", "skills", "p-%s" % skill, "SKILL.md"), "x\n")
        _d, items = self.setup.migration_plan(root)
        return {path.split("/")[-1].replace(".md", ""): target for _kind, path, target, _note in items}

    def test_targets_follow_the_specs_method(self):
        on = self.plan("openspec")
        self.assertEqual(on["p-spec-reviewer"], "openspec:spec-reviewer")
        self.assertEqual(on["p-worker"], "delegate:worker")
        self.assertEqual(on["p-plan"], "openspec:plan")
        self.assertEqual(on["p-apply-review"], "the change cycle's step 4")   # never a skill that no longer exists
        self.assertNotIn(OLD, " ".join(on.values()))
        self.assertNotIn("openspec:apply-review", on.values())

    def test_with_specs_off_spec_agents_have_no_target(self):
        shutil.rmtree(os.path.join(self.tmp, "p"), ignore_errors=True)
        off = self.plan("none")
        self.assertEqual(off["p-spec-reviewer"], "no target: spec steps are off")
        self.assertEqual(off["p-plan"], "no target: spec steps are off")
        self.assertEqual(off["p-worker"], "delegate:worker")


# --- case 9: doctor -----------------------------------------------------------------------------------------------

class Doctor(Scratch):
    def checks(self, root):
        with mock.patch.object(self.setup, "dep_checks", lambda: []):
            return {n: (ok, detail) for n, ok, detail in self.setup.doctor(root, profile={})}

    def test_old_binding_is_named(self):
        root = self.project("eta", old_flow='\n[flow]\nkind = "openspec"\n')
        good, detail = self.checks(root)["no old binding"]
        self.assertFalse(good)
        self.assertIn("old binding", detail)

    def test_method_on_without_the_plugin_is_drift(self):
        root = self.project("theta", specs="openspec")
        good, detail = self.checks(root)["spec steps and openspec@amidman agree"]
        self.assertFalse(good)
        self.assertIn("not enabled", detail)
        self.write(os.path.join(root, ".claude", "settings.json"), json.dumps({"enabledPlugins": {"openspec@amidman": True}}))
        self.assertNotIn("spec steps and openspec@amidman agree", self.checks(root))

    def test_plugin_on_with_the_steps_off_is_drift_too(self):
        root = self.project("iota", specs="none")
        self.write(os.path.join(root, ".claude", "settings.json"), json.dumps({"enabledPlugins": {"openspec@amidman": True}}))
        self.assertFalse(self.checks(root)["spec steps and openspec@amidman agree"][0])

    def test_unknown_method_is_named(self):
        root = self.project("kappa", specs="nonesuch")
        good, detail = self.checks(root)["spec method 'nonesuch' known"]
        self.assertFalse(good)
        self.assertIn("no spec method", detail)

    def test_project_scope_install_of_a_plugin_no_longer_shipped_is_listed_until_setup(self):
        root = self.project("lambda1", specs="openspec")
        self.registry({OLD + "@relay": [{"scope": "project", "projectPath": root}]})
        lines = self.setup.unshipped_installs()
        self.assertEqual(len(lines), 1)
        self.assertIn("run relay setup " + root, lines[0])
        self.run_setup(root)
        self.assertEqual(self.setup.unshipped_installs(), [])

    def test_additions_for_removed_stages_and_files_naming_the_old_plugin_are_listed(self):
        root = self.project("mu", specs="openspec")
        self.write(os.path.join(root, ".claude", "kit", "parallel-apply.md"), "rules\n")
        self.write(os.path.join(root, ".claude", "agents", "x.md"), "use " + OLD + ":worker\n")
        checks = self.checks(root)
        self.assertIn("addition for a removed stage", checks["no addition for a removed stage"][1])
        self.assertIn(".claude/agents/x.md:1", checks["no file names the old plugin"][1])


# --- case 10: the stage hook --------------------------------------------------------------------------------------

class StageHook(Scratch):
    def say(self, root, prompt, hook=("relay", "flow-stage.py")):
        data = json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": root, "prompt": prompt})
        run = subprocess.run([sys.executable, os.path.join(ROOT, "plugins", hook[0], "hooks", hook[1])], input=data,
                             capture_output=True, text=True,
                             env={**os.environ, "RELAY_ROOT": ROOT, "CLAUDE_PLUGIN_ROOT": os.path.join(ROOT, "plugins", hook[0])})
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)["hookSpecificOutput"]["additionalContext"] if run.stdout.strip() else ""

    def test_stage_lines_of_the_spec_method(self):
        root = self.project("nu", specs="openspec")
        spec = ("openspec", "spec-rule.py")   # the spec method's line is the openspec plugin's hook; core's stays silent
        apply_line = self.say(root, "/opsx:apply add-x", spec)
        self.assertIn("step 2 of the change cycle", apply_line)
        self.assertIn("kit packet", apply_line)
        self.assertIn("openspec:spec-conformance", self.say(root, "/opsx:verify add-x", spec))
        self.assertIn("openspec:plan", self.say(root, "/opsx:propose add-x: do it", spec))
        self.assertIn("openspec:archive", self.say(root, "/opsx:archive add-x", spec))
        self.assertEqual(self.say(root, "/opsx:apply add-x"), "")

    def test_nothing_without_the_setting_and_nothing_for_the_old_flow_form(self):
        self.assertEqual(self.say(self.project("xi"), "/opsx:apply x"), "")
        self.assertEqual(self.say(self.project("omicron", old_flow='\n[flow]\nkind = "openspec"\n'), "/opsx:apply x"), "")
        self.assertEqual(self.say(self.project("pi"), "/opsx:apply x", ("openspec", "spec-rule.py")), "")

    def test_no_two_shipped_manifests_share_a_trigger(self):
        seen = {}
        for plugin in sorted(os.listdir(os.path.join(ROOT, "plugins"))):
            path = os.path.join(ROOT, "plugins", plugin, "flow.json")
            if os.path.isfile(path):
                for stage in json.load(open(path, encoding="utf-8"))["stages"]:
                    for trigger in stage.get("triggers", []):
                        self.assertNotIn(trigger, seen, "%s and %s share %s" % (seen.get(trigger), plugin, trigger))
                        seen[trigger] = plugin


# --- case 11 and 13: one answer per question; the manifests name real files --------------------------------------

class OneAnswer(unittest.TestCase):
    def skill_files(self):
        out = []
        for base, _dirs, files in os.walk(os.path.join(ROOT, "plugins")):
            if "/skills/" in base + "/" and "SKILL.md" in files:
                out.append(os.path.join(base, "SKILL.md"))
        return sorted(out)

    def test_no_skill_gives_a_second_answer(self):
        wrong = ['model: "', 'subagent_type: "Explore"', "/clear", "bin/packet", "at most 6", "alix-lead", "coordination.mode", "perl -pi"]
        skills = self.skill_files()
        self.assertGreater(len(skills), 5)   # was 10 before the issues and product plugins (6 skills) were removed
        for path in skills:
            text = open(path, encoding="utf-8").read()
            for phrase in wrong:
                self.assertNotIn(phrase, text, "%s: %s" % (os.path.relpath(path, ROOT), phrase))

    def test_delegate_skill_escalates_once_and_never_names_openspec(self):
        text = open(os.path.join(ROOT, "plugins", "delegate", "skills", "delegate", "SKILL.md"), encoding="utf-8").read()
        self.assertEqual(text.count("`Escalated: <reason>`"), 1)
        self.assertNotIn("openspec", text.lower())

    def test_every_name_in_a_manifest_exists_and_a_spec_method_has_no_build_roles(self):
        for plugin in sorted(os.listdir(os.path.join(ROOT, "plugins"))):
            path = os.path.join(ROOT, "plugins", plugin, "flow.json")
            if not os.path.isfile(path):
                continue
            manifest = json.load(open(path, encoding="utf-8"))
            named = [s["skill"] for s in manifest.get("stages", []) if s.get("skill")]
            named += [s[k] for s in manifest.get("steps", []) for k in ("skill", "agent") if s.get(k)]
            named += list(manifest.get("roles", {}).values())
            for full in named:
                owner, _, name = full.partition(":")
                found = [os.path.join(ROOT, "plugins", owner, "skills", name, "SKILL.md"), os.path.join(ROOT, "plugins", owner, "agents", name + ".md")]
                self.assertTrue(any(os.path.isfile(f) for f in found), "%s names %s, which does not exist" % (plugin, full))
            if manifest.get("slot") == "specs":
                self.assertFalse({"build", "fix"} & set(manifest.get("roles", {})), plugin)


# --- case 14: the packet --------------------------------------------------------------------------------------------

class Packet(Scratch):
    TASK = "- [ ] %s Do it. Reads: file docs/guide.md. Tests: none (docs). Files: docs/guide.md. Check: `true`\n"

    def change(self, tasks):
        root = self.project("packet")
        self.write(os.path.join(root, "docs", "guide.md"), "# Guide\n")
        self.write(os.path.join(root, "openspec", "changes", "c", "design.md"), "# D\n")
        self.write(os.path.join(root, "openspec", "changes", "c", "tasks.md"), tasks)
        return root

    def kit(self, root, *args):
        return subprocess.run([os.path.join(ROOT, "plugins", "relay", "bin", "kit"), "packet", *args], cwd=root, capture_output=True, text=True)

    def test_every_packet_ends_with_the_building_rules(self):
        rules = open(os.path.join(ROOT, "plugins", "relay", "lib", "kit_packet_rules.md"), encoding="utf-8").read().strip()
        root = self.change("## 1. A\n\n" + self.TASK % "1.1")
        for target in ("1", "1.1"):   # a group packet and a task packet
            run = self.kit(root, "c", target)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn(rules, run.stdout, target)
            body = run.stdout.split("(brief:")[0].rstrip()
            self.assertTrue(body.endswith(rules), target)

    def test_check_passes_tasks_without_wave_lines(self):
        root = self.change("## 1. A\n\n" + self.TASK % "1.1" + "\n## 2. B\n\n" + self.TASK % "2.1")
        run = self.kit(root, "--check", "c")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


class ReviewFixes(unittest.TestCase):
    def read(self, *parts):
        return open(os.path.join(ROOT, *parts), encoding="utf-8").read()

    def test_F2_the_packet_rules_carry_the_removed_workers_build_rules(self):
        text = self.read("plugins", "relay", "lib", "kit_packet_rules.md")
        self.assertIn("black-box", text)
        self.assertIn("same-process test does not count", text)
        self.assertIn("whole", text)
        self.assertIn("incomplete `Reads:` line", text)

    def test_F3_no_interfaces_requirement_and_no_wave_plan_in_the_openspec_agents(self):
        reviewer = self.read("plugins", "openspec", "agents", "spec-reviewer.md")
        self.assertNotIn("Interfaces", reviewer)
        self.assertNotIn("wave plan", reviewer)
        self.assertNotIn("Interfaces", self.read("plugins", "openspec", "agents", "author.md"))

    def test_F4_no_look_line_and_no_lead_under_openspec(self):
        for base, _d, files in os.walk(os.path.join(ROOT, "plugins", "openspec")):
            for name in files:
                if not name.endswith(".md"):
                    continue
                text = open(os.path.join(base, name), encoding="utf-8").read()
                for phrase in ("the lead", "lead's", "`Look:`"):
                    self.assertNotIn(phrase, text, "%s: %s" % (os.path.join(base, name), phrase))
        self.assertIn("every task in `tasks.md` is ticked", self.read("plugins", "openspec", "skills", "archive", "SKILL.md"))

    def test_F6_no_alias_table_and_no_wave_in_kit_packet(self):
        self.assertNotIn("ALIASES", self.read("plugins", "relay", "hooks", "flow-stage.py"))
        self.assertNotIn("wave", self.read("plugins", "relay", "lib", "kit_packet.py").lower())

    def test_F5_the_spec_step_twins_carry_the_same_request(self):
        for suffix in ("en", "ru", "typo"):
            on = self.read("evals", "plugin", "spec-step-on-" + suffix, "prompt.md")
            off = self.read("evals", "plugin", "no-spec-step" + ("" if suffix == "en" else "-" + suffix), "prompt.md")
            self.assertEqual(on.split("---\n", 2)[2], off.split("---\n", 2)[2], suffix)
            for word in ("plan", "spec", "no code"):
                self.assertNotIn(word, on.split("---\n", 2)[2].lower(), suffix)


# --- case 15: the route guard --------------------------------------------------------------------------------------

class RouteGuard(Scratch):
    def guard(self):
        return load_hook("route_guard_spec_steps", os.path.join(ROOT, "plugins", "delegate", "hooks", "route-guard.py"))

    def test_loading_the_guard_leaves_no_plugin_lib_copy_behind(self):
        """The hook's plugins/delegate/lib is put first on sys.path and its relay_config copy imported; if either stays,
        lib/relay_license later looks for data/licenses under plugins/delegate (the queue item's failing case)."""
        for name in [m for m in sys.modules if m.startswith("relay_")]:
            del sys.modules[name]       # nothing imported yet, so anything found afterwards came from the hook
        path_before = list(sys.path)
        try:
            self.guard()
            self.assertEqual(sys.path, path_before)
            self.assertEqual([m for m in sys.modules if m.startswith("relay_")], [])
        finally:
            sys.path[:] = path_before

    def probe(self, code: str) -> str:
        """Run code in a fresh interpreter with tests/ and lib/ on sys.path (as pytest collection leaves them)."""
        run = subprocess.run([sys.executable, "-S", "-c", code, ROOT], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        return run.stdout.strip()

    def test_F2_loading_a_hook_keeps_stdlib_modules(self):
        """A bare interpreter imports datetime, typing and tomllib only through the hook; they are not the hook's copies, so they stay."""
        out = self.probe(
            "import sys, os\nroot = sys.argv[1]\nsys.path[:0] = [os.path.join(root, 'tests'), os.path.join(root, 'lib')]\n"
            "import relay_testbase\nbefore = list(sys.path)\nassert not any(m in sys.modules for m in ('datetime', 'typing', 'tomllib'))\n"
            "relay_testbase.load_hook('g', os.path.join(root, 'plugins', 'delegate', 'hooks', 'route-guard.py'))\n"
            "print(all(m in sys.modules for m in ('datetime', 'typing', 'tomllib')), sys.path == before, "
            "[m for m in sys.modules if m.startswith('relay_') and m != 'relay_testbase'])")
        self.assertEqual(out, "True True []")

    def test_F1_core_hook_tests_leave_the_lib_queue_in_place(self):
        """Importing test_mark_attach (what collection does) must not make relay_queue come from plugins/relay/lib,
        where queue_ext is missing and extensions() is empty; lib/relay_queue lists json and table."""
        out = self.probe(
            "import sys, os\nroot = sys.argv[1]\nsys.path[:0] = [os.path.join(root, 'tests'), os.path.join(root, 'lib')]\n"
            "import test_mark_attach, test_check_record\n"
            "[sys.modules.pop(m) for m in list(sys.modules) if m.startswith('relay_')]\n"
            "import relay_queue\n"
            "print(os.path.relpath(relay_queue.__file__, root), relay_queue.extensions(), "
            "[p for p in sys.path if p.endswith(os.path.join('plugins', 'relay', 'lib'))])")
        self.assertEqual(out, "lib/relay_queue.py ['json', 'table'] []")

    def transcript(self, *entries):
        path = os.path.join(self.tmp, "t-%d.jsonl" % len(os.listdir(self.tmp)))
        self.write(path, "".join(json.dumps(e) + "\n" for e in entries))
        return path

    def call(self, root, transcript, **extra):
        data = {"tool_name": "Agent", "cwd": root, "session_id": "s1", "transcript_path": transcript,
                "tool_input": {"subagent_type": "delegate:worker", "prompt": "Implement the brief. Brief: x"}}
        data.update(extra)
        return self.guard().decide(data)

    USER = {"type": "user", "message": {"role": "user", "content": "do it"}}

    def test_no_skill_call_and_no_earlier_denial_is_refused_with_the_item_7_line(self):
        out = self.call(self.project("rg1"), self.transcript(self.USER))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("load the delegate skill first", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_one_earlier_denial_lets_the_call_through_with_a_note(self):
        denial = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "Routing: load the delegate skill first (brief files)"}]}}
        out = self.call(self.project("rg2"), self.transcript(self.USER, denial))
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])
        self.assertIn("delegate skill", out["hookSpecificOutput"]["additionalContext"])

    def test_the_skill_loaded_lets_the_call_through_silently(self):
        call = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "delegate:delegate"}}]}}
        self.assertIsNone(self.call(self.project("rg3"), self.transcript(self.USER, call)))
        typed = {"type": "user", "message": {"role": "user", "content": "/delegate:delegate"}}
        self.assertIsNone(self.call(self.project("rg3b"), self.transcript(typed)))

    def test_F1_a_slash_command_as_claude_code_stores_it_counts_as_loaded(self):
        # the real shape: <command-message> first, then <command-name>
        real = {"type": "user", "message": {"role": "user", "content": "<command-message>delegate:delegate</command-message>\n<command-name>/delegate:delegate</command-name>\n<command-args></command-args>"}}
        self.assertIsNone(self.call(self.project("rg8"), self.transcript(real)))
        other = {"type": "user", "message": {"role": "user", "content": "<command-message>front:front</command-message>\n<command-name>/front:front</command-name>"}}
        out = self.call(self.project("rg9"), self.transcript(other))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_F7_an_unknown_require_skill_value_denies_like_deny(self):
        bad = self.project("rg10", extra='\n[delegate]\nrequire_skill = "Bogus"\n')
        out = self.call(bad, self.transcript(self.USER))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_F7_the_docs_table_has_the_require_skill_row(self):
        text = open(os.path.join(ROOT, "docs", "delegation.md"), encoding="utf-8").read()
        self.assertIn("require_skill = deny|note|off", text)

    def test_the_setting_off_and_note_and_a_subagent_and_an_unreadable_transcript(self):
        off = self.project("rg4", extra='\n[delegate]\nrequire_skill = "off"\n')
        self.assertIsNone(self.call(off, self.transcript(self.USER)))
        note = self.project("rg5", extra='\n[delegate]\nrequire_skill = "note"\n')
        self.assertNotIn("permissionDecision", self.call(note, self.transcript(self.USER))["hookSpecificOutput"])
        self.assertIsNone(self.call(self.project("rg6"), self.transcript(self.USER), agent_id="a1"))   # a subagent is not checked
        self.assertIsNone(self.call(self.project("rg7"), os.path.join(self.tmp, "missing.jsonl")))      # cannot tell: fails open


if __name__ == "__main__":
    unittest.main()
