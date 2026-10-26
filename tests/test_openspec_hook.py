"""The openspec plugin answers for the spec method itself: its one hook (plugins/openspec/hooks/spec-rule.py) gives the
rule and the steps table at SessionStart and SubagentStart and the stage line on /opsx:* prompts, each only where the
project's kit.toml has [specs] method = "openspec". Every case runs on a temp project; nothing under ~ or the repo is written."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "plugins", "openspec")
HOOK = os.path.join(PLUGIN, "hooks", "spec-rule.py")
FLOW_STAGE = os.path.join(ROOT, "plugins", "core", "hooks", "flow-stage.py")
sys.path.insert(0, os.path.join(ROOT, "evals", "plugin"))
import system_rules  # noqa: E402

# The stage line master's flow-stage hook gave /opsx:propose, written out by hand from the line's template and flow.json
# (stage plan, skill openspec:plan, no note, no roles).
PROPOSE_LINE = ("Stage `plan` of the spec steps: load the `openspec:plan` skill with the Skill tool before the first step "
                "and follow it; where it differs from a command's own text, `openspec:plan` wins.")


class Project(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)
        os.makedirs(os.path.join(self.root, ".claude"))

    def kit(self, text):
        with open(os.path.join(self.root, ".claude", "kit.toml"), "w", encoding="utf-8") as handle:
            handle.write(text)

    def run_hook(self, script, event, **extra):
        data = dict({"hook_event_name": event, "cwd": self.root}, **extra)
        env = {k: v for k, v in os.environ.items() if k != "RELAY_ROOT"}
        env["CLAUDE_PLUGIN_ROOT"] = PLUGIN if script == HOOK else os.path.join(ROOT, "plugins", "core")
        done = subprocess.run([sys.executable, script], input=json.dumps(data), capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)["hookSpecificOutput"] if done.stdout else None

    def text(self, event, **extra):
        out = self.run_hook(HOOK, event, **extra)
        self.assertEqual(out["hookEventName"], event)
        return out["additionalContext"]


class MethodOn(Project):
    def setUp(self):
        super().setUp()
        self.kit('[specs]\nmethod = "openspec"\n')

    def test_propose_gets_the_plan_stage_line(self):
        self.assertEqual(self.text("UserPromptSubmit", prompt="/opsx:propose add-x: do it"), PROPOSE_LINE)

    def test_apply_gets_the_note_and_a_plain_prompt_nothing(self):
        self.assertIn("step 2 of the change cycle", self.text("UserPromptSubmit", prompt="/opsx:apply add-x"))
        self.assertIsNone(self.run_hook(HOOK, "UserPromptSubmit", prompt="hello"))
        self.assertIsNone(self.run_hook(HOOK, "UserPromptSubmit", prompt="/opsx:apply x", agent_id="a"))

    def test_session_start_gives_the_rule_and_the_six_step_table(self):
        text = self.text("SessionStart")
        self.assertTrue(text.startswith("## OpenSpec\n\nThis project has OpenSpec spec steps turned on"))
        self.assertLess(text.index("## OpenSpec"), text.index("### Spec steps in the change cycle"))
        self.assertNotIn("# OpenSpec\n> ", text)   # the rule file's title and gist lines are not repeated
        rows = [line for line in text.splitlines() if line.startswith("| ") and "`" in line]
        # flow.json lists six steps: before 1, 1, 2, 4, 5, after 7
        self.assertEqual([r.split("|")[1].strip() for r in rows], ["before 1", "1", "2", "4", "5", "after 7"])

    def test_a_started_thinker_gets_the_same_text(self):
        main = self.text("SessionStart")
        self.assertEqual(self.text("SubagentStart", agent_type="delegate:thinker", agent_id="a1"), main)

    def test_F2_the_spec_step_evals_get_the_rule_only_from_the_hook(self):
        # the cases load the openspec plugin and their scaffold turns the method on; a copy of the rule in
        # append_system_prompt would make the paid run pass without the hook's SessionStart text ever arriving
        for case in ("spec-step-on", "spec-step-on-en", "spec-step-on-ru", "spec-step-on-typo", "spec-step-on-bugfix"):
            self.assertNotIn(case, system_rules.CASES)
            self.assertIsNone(system_rules.current(case), case)
            with open(os.path.join(ROOT, "evals", "plugin", case, "case.yaml"), encoding="utf-8") as handle:
                self.assertIn("plugins/openspec", handle.read(), case)

    def test_the_hook_runs_in_a_subfolder_of_the_project(self):
        # the project root is the git top level of cwd, else cwd itself: a plain folder is its own root
        sub = os.path.join(self.root, "src")
        os.makedirs(sub)
        out = self.run_hook(HOOK, "SessionStart", cwd=sub)
        self.assertIsNone(out)   # no kit.toml in src and no git: src is the root, so the method is unset there

    def test_F4_a_subfolder_of_a_git_project_finds_the_root_kit_toml(self):
        subprocess.run(["git", "init", "-q", self.root], check=True)
        sub = os.path.join(self.root, "src")
        os.makedirs(sub)
        self.assertEqual(self.text("SessionStart", cwd=sub), self.text("SessionStart"))
        self.assertIn("## OpenSpec", self.text("SessionStart", cwd=self.root))


class Docs(unittest.TestCase):
    def test_F1_flows_md_binding_names_the_plugins_hook_not_sync(self):
        with open(os.path.join(ROOT, "docs", "flows.md"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("rules/openspec.md` in the project", text)
        self.assertNotIn("The core plugin's stage hook reads both", text)
        for word in ("plugins/openspec/rules/openspec.md", "SessionStart and SubagentStart", "`[flow] kind` only", "`/<trigger> 42`"):
            self.assertIn(word, text)


class KitReader(unittest.TestCase):
    """F3: [specs] method is read by relay's shared TOML reader, on tomllib and on its Python 3.9 fallback alike."""
    FORMS = (('[specs]\nmethod = "openspec"   # comment\n', "openspec"),
             ('[specs]\nmethod_old = "openspec"\nmethod = "none"\n', "none"),
             ('specs.method = "openspec"\n', "openspec"),
             ('[specs]\nmethod = "openspec#1"\n', "openspec#1"),
             ('[specs\nmethod =', "none"))

    def test_F3_both_readers_agree_on_every_form(self):
        import importlib.util
        found = importlib.util.spec_from_file_location("openspec_spec_rule_kit", HOOK)
        hook = importlib.util.module_from_spec(found)
        found.loader.exec_module(hook)
        saved = hook.relay_toml._tomllib
        self.addCleanup(setattr, hook.relay_toml, "_tomllib", saved)
        for tomllib_on in (True, False):
            hook.relay_toml._tomllib = saved if tomllib_on else None
            for text, want in self.FORMS:
                with tempfile.TemporaryDirectory() as root:
                    os.makedirs(os.path.join(root, ".claude"))
                    with open(os.path.join(root, ".claude", "kit.toml"), "w", encoding="utf-8") as handle:
                        handle.write(text)
                    self.assertEqual(hook.project_method(root), want, (tomllib_on, text))


class MethodOff(Project):
    EVENTS = (("SessionStart", {}), ("SubagentStart", {"agent_type": "delegate:thinker"}),
              ("UserPromptSubmit", {"prompt": "/opsx:propose x"}))

    def silent(self):
        for event, extra in self.EVENTS:
            self.assertIsNone(self.run_hook(HOOK, event, **extra), event)

    def test_no_kit_toml(self):
        self.silent()

    def test_method_none(self):
        self.kit('[specs]\nmethod = "none"\n')
        self.silent()

    def test_only_a_flow_kind(self):
        self.kit('[flow]\nkind = "other"\n')
        self.silent()

    def test_another_method(self):
        self.kit('[specs]\nmethod = "other"\n')
        self.silent()

    def test_a_broken_kit_toml_is_silent_not_an_error(self):
        self.kit("[specs\nmethod =")
        self.silent()


class CoreKeepsFlow(Project):
    def test_core_no_longer_answers_for_the_spec_method(self):
        self.kit('[specs]\nmethod = "openspec"\n')
        self.assertIsNone(self.run_hook(FLOW_STAGE, "UserPromptSubmit", prompt="/opsx:propose x"))


class Layout(unittest.TestCase):
    def test_the_rule_lives_in_the_plugin_only(self):
        self.assertTrue(os.path.isfile(os.path.join(PLUGIN, "rules", "openspec.md")))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "rules", "openspec.md")))

    def test_the_plugin_registers_the_three_events(self):
        with open(os.path.join(PLUGIN, "hooks", "hooks.json"), encoding="utf-8") as handle:
            hooks = json.load(handle)["hooks"]
        self.assertEqual(sorted(hooks), ["SessionStart", "SubagentStart", "UserPromptSubmit"])
        for event in hooks:
            self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/spec-rule.py", json.dumps(hooks[event]))

    def test_the_hook_reads_nothing_of_the_relay_checkout(self):
        with open(HOOK, encoding="utf-8") as handle:
            text = handle.read()
        # the one relay module it imports is the plugin's own copy of relay_toml (plugins/openspec/lib), never lib/
        self.assertEqual(re.findall(r"^(?:import|from) (relay_\w+)", text, re.M), ["relay_toml"])
        self.assertIn('"..", "lib"', text)
        self.assertTrue(os.path.isfile(os.path.join(PLUGIN, "lib", "relay_toml.py")))


if __name__ == "__main__":
    unittest.main()
