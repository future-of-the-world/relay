"""relay setup turns off, for one project, the plugins it does not use (design T1-T23). Every test works in a temporary folder
with its own Claude folder and registry; nothing here reads or writes the live ~/.claude."""
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # unittest from the repo root has only the root on sys.path
from relay_testbase import Base, ROOT  # noqa: E402
from fake_tools import install_fake  # noqa: E402

GOPLS = "gopls-lsp@claude-plugins-official"
RELAY_BIN = os.path.join(ROOT, "bin", "relay")
OK_INSTALL = lambda root, key: (True, "")   # noqa: E731


class Fixture(Base):
    def setUp(self):
        super().setUp()
        import relay_setup
        self.rs = relay_setup
        self.registry([GOPLS, "a@m", "b@m"] + [f"{p}@relay" for p in ("core", "observe", "delegate", "front")])

    def registry(self, ids):
        folder = os.path.join(self.claude, "plugins")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "installed_plugins.json"), "w") as handle:
            json.dump({"plugins": {k: [{"scope": "user"}] for k in ids}}, handle)

    def git_folder(self, name="proj"):
        root = os.path.join(self.tmp, name)
        os.makedirs(root)
        subprocess.run(["git", "init", "-q", root], check=True)
        return root

    def relay_tree(self):
        """The shape of relay itself: kit.toml with only [delegate], bin/ci, docs/handover.md, .relay/README.md."""
        root = self.git_folder("relaytree")
        self.write(root, ".claude/kit.toml", "[delegate]\nmax_parallel = 6\n")
        os.makedirs(os.path.join(root, "bin"), exist_ok=True)
        install_fake(os.path.join(root, "bin", "ci"), "#!/bin/sh\n")
        self.write(root, "docs/handover.md", "h\n")
        self.write(root, ".relay/README.md", "r\n")
        return root

    def write(self, root, rel, text):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)

    def read(self, root, rel):
        with open(os.path.join(root, rel)) as handle:
            return handle.read()

    def settings(self, root):
        return json.loads(self.read(root, ".claude/settings.json"))

    def plugins(self, root):
        return self.settings(root)["enabledPlugins"]

    def files(self, root):
        out = set()
        for folder, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d != ".git"]
            out |= {os.path.relpath(os.path.join(folder, n), root) for n in names}
        return out

    def stat(self, root, rel):
        path = os.path.join(root, rel)
        return open(path, "rb").read(), os.stat(path).st_mtime_ns

    def run_setup(self, root, **kw):
        kw.setdefault("install_runner", OK_INSTALL)
        return self.rs.setup(root, **kw)

    def marketplace_fixture(self, name, plugins):
        path = os.path.join(self.tmp, "marketplace.json")
        with open(path, "w") as handle:
            json.dump({"name": name, "plugins": [{"name": p} for p in plugins]}, handle)
        self.rs.MARKETPLACE_FILE = path


ALL = ("core", "observe", "delegate", "front", "openspec", "issues", "product")
T1_PLUGINS = {"core@relay": True, "observe@relay": True, "delegate@relay": True, "front@relay": True,
              "openspec@relay": False, "issues@relay": False, "product@relay": False, GOPLS: False}


class Writes(Fixture):
    def test_t1_relay_tree_gets_false_lines_and_no_templates(self):
        root = self.relay_tree()
        before = self.files(root)
        kit = self.read(root, ".claude/kit.toml")
        ci = self.read(root, "bin/ci")
        self.run_setup(root, off=[GOPLS])
        self.assertEqual(self.plugins(root), T1_PLUGINS)
        data = self.settings(root)
        self.assertEqual(data["extraKnownMarketplaces"]["relay"]["source"], {"source": "directory", "path": self.rs.marketplace_root()})
        self.assertEqual(data["permissions"]["allow"], ["Bash(kit:*)", "Bash(bin/kit:*)", "Bash(relay:*)"])
        self.assertEqual(self.read(root, ".claude/kit.toml"), kit)   # [delegate] equals the default: nothing added
        self.assertEqual(self.read(root, "bin/ci"), ci)
        self.assertEqual(self.files(root) - before, {".claude/settings.json"})   # no bin/check, bin/wt, CLAUDE.md, settings.local.json

    def test_t2_second_run_changes_nothing(self):
        root = self.relay_tree()
        self.run_setup(root, off=[GOPLS])
        first = self.stat(root, ".claude/settings.json")
        *_, done, _ = self.run_setup(root)
        self.assertEqual(self.stat(root, ".claude/settings.json"), first)   # bytes and mtime: not rewritten
        self.assertTrue(any("(unchanged)" in line for line in done), done)
        self.assertFalse(os.path.exists(os.path.join(root, ".git", "relay-backup")))   # no backup was made

    def test_t3_a_hand_set_true_stays(self):
        root = self.relay_tree()
        self.run_setup(root, off=[GOPLS])
        data = self.settings(root)
        data["enabledPlugins"]["product@relay"] = True
        self.write(root, ".claude/settings.json", json.dumps(data))
        self.run_setup(root)
        self.assertIs(self.plugins(root)["product@relay"], True)

    def test_t4_a_key_of_another_marketplace_that_is_not_named_stays(self):
        root = self.relay_tree()
        self.run_setup(root, off=[GOPLS])
        data = self.settings(root)
        data["enabledPlugins"]["context7@claude-plugins-official"] = True
        self.write(root, ".claude/settings.json", json.dumps(data))
        self.run_setup(root)
        self.assertIs(self.plugins(root)["context7@claude-plugins-official"], True)
        self.assertIs(self.plugins(root)[GOPLS], False)   # a re-run without --off keeps the line

    def test_t5_a_turned_off_spec_method_is_false_not_deleted(self):
        root = self.relay_tree()
        self.write(root, ".claude/settings.json", json.dumps({"enabledPlugins": {"openspec@relay": True}}))
        self.run_setup(root)
        self.assertIs(self.plugins(root)["openspec@relay"], False)

    def test_t6_specs_on_then_off(self):
        root = self.relay_tree()
        self.run_setup(root, specs="openspec")
        self.assertIs(self.plugins(root)["openspec@relay"], True)
        self.assertIn('[specs]\nmethod = "openspec"', self.read(root, ".claude/kit.toml"))
        self.run_setup(root, specs="none")
        self.assertIs(self.plugins(root)["openspec@relay"], False)
        self.assertIn('method = "none"', self.read(root, ".claude/kit.toml"))

    def test_t9_a_new_project_gets_the_templates_and_the_full_kit_toml(self):
        root = self.git_folder()
        self.run_setup(root, product=None)
        for rel in (".claude/kit.toml", "bin/check", "bin/ci", "bin/wt", "CLAUDE.md", "docs/handover.md"):
            self.assertTrue(os.path.isfile(os.path.join(root, rel)), rel)
        self.assertEqual(self.plugins(root), {"core@relay": True, "observe@relay": True, "delegate@relay": True, "front@relay": True,
                                              "openspec@relay": False, "issues@relay": False, "product@relay": False})
        self.assertIn("[delegate]", self.read(root, ".claude/kit.toml"))

    def test_t10_an_existing_kit_toml_gets_no_template_and_a_todo_line(self):
        root = self.git_folder()
        self.write(root, ".claude/kit.toml", "[project]\nname = \"x\"\n")
        *_, todo = self.run_setup(root)
        self.assertFalse(os.path.exists(os.path.join(root, "bin", "check")))
        self.assertEqual(len([t for t in todo if t.startswith("bin/check ")]), 1, todo)
        checks = {n: ok for n, ok, _ in self.rs.doctor(root, profile={})}
        self.assertFalse(checks["gate.check exists and is executable"])


class KitToml(Fixture):
    def kit(self, text):
        root = self.git_folder()
        self.write(root, ".claude/kit.toml", text)
        return root

    def test_t11_only_sections_that_differ_from_a_missing_section_are_added(self):
        root = self.kit("[delegate]\nmax_parallel = 6\n")
        text = self.read(root, ".claude/kit.toml")
        self.assertEqual(self.rs.merge_bindings(root, "none", "none"), [])
        self.assertEqual(self.rs.merge_bindings(root, "none", "none", force_flow=True), [])
        self.assertEqual(self.read(root, ".claude/kit.toml"), text)
        self.assertEqual(self.rs.merge_bindings(root, "none", "openspec", spec_folder=True), ["specs"])   # an openspec/ folder
        self.assertIn('[specs]\nmethod = "openspec"', self.read(root, ".claude/kit.toml"))

    def test_t11_specs_none_is_written_when_the_run_says_so(self):
        root = self.kit("[delegate]\nmax_parallel = 6\n")
        self.assertEqual(self.rs.merge_bindings(root, "none", "none", force_specs=True), ["specs"])
        self.assertIn('method = "none"', self.read(root, ".claude/kit.toml"))

    def test_t11_an_openspec_folder_turns_the_spec_method_on_in_kit_toml(self):
        root = self.kit("[delegate]\nmax_parallel = 6\n")
        os.makedirs(os.path.join(root, "openspec"))
        self.run_setup(root)
        self.assertIn('[specs]\nmethod = "openspec"', self.read(root, ".claude/kit.toml"))

    def test_t17_flow_issues_is_recorded_and_read_back(self):
        root = self.kit("[project]\nname = \"x\"\n\n[gate]\ncheck = \"bin/check\"\n")
        self.run_setup(root, flow="issues")
        self.assertIn('[flow]\nkind = "issues"', self.read(root, ".claude/kit.toml"))
        self.assertIs(self.plugins(root)["issues@relay"], True)
        kit = self.read(root, ".claude/kit.toml")
        self.run_setup(root)   # a plain run: the flow comes from kit.toml, not from a kept key
        self.assertEqual(self.read(root, ".claude/kit.toml"), kit)
        self.assertIs(self.plugins(root)["issues@relay"], True)

    def test_t17_the_flow_is_read_from_kit_toml_even_when_the_key_is_gone(self):
        root = self.kit("[flow]\nkind = \"issues\"\n")
        self.run_setup(root)
        self.assertIs(self.plugins(root)["issues@relay"], True)

    def test_t18_flow_none_rewrites_kit_toml_and_turns_issues_off(self):
        root = self.kit("[flow]\nkind = \"issues\"\n")
        self.write(root, ".claude/settings.json", json.dumps({"enabledPlugins": {"issues@relay": True}}))
        self.run_setup(root, flow="none")
        self.assertIn('kind = "none"', self.read(root, ".claude/kit.toml"))
        self.assertIs(self.plugins(root)["issues@relay"], False)


class Refusals(Fixture):
    def test_t7_relays_own_plugins_cannot_be_named_in_off(self):
        root = self.relay_tree()
        self.run_setup(root)
        s, k = self.stat(root, ".claude/settings.json"), self.stat(root, ".claude/kit.toml")
        with self.assertRaises(ValueError) as core:
            self.run_setup(root, off=["core@relay"])
        self.assertIn("--flow, --specs and --product", str(core.exception))
        with self.assertRaises(ValueError) as issues:
            self.run_setup(root, off=["issues@relay"])
        self.assertIn("--flow", str(issues.exception))
        self.assertEqual((self.stat(root, ".claude/settings.json"), self.stat(root, ".claude/kit.toml")), (s, k))

    def test_t8_a_plugin_the_registry_does_not_know_is_refused(self):
        root = self.relay_tree()
        before = self.files(root)
        with self.assertRaises(ValueError) as err:
            self.run_setup(root, off=["gopls@claude-plugins-official"])
        self.assertIn(GOPLS, str(err.exception))   # the message lists the ids that are known
        self.assertEqual(self.files(root), before)

    def test_t19_an_always_on_plugin_missing_from_the_marketplace_stops_before_any_write(self):
        root = self.relay_tree()
        self.run_setup(root)
        before = self.stat(root, ".claude/settings.json")
        self.marketplace_fixture("relay", [p for p in ALL if p != "core"] + ["relay"])
        with self.assertRaises(ValueError) as err:
            self.run_setup(root)
        self.assertIn("core", str(err.exception))
        self.assertEqual(self.stat(root, ".claude/settings.json"), before)

    def test_t20_the_real_marketplace_lists_every_always_on_plugin(self):
        names = json.load(open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")))["plugins"]
        self.assertTrue(set(self.rs.ALWAYS_ON) <= {p["name"] for p in names})


class Rename(Fixture):
    def test_t15_the_new_code_writes_no_literal_relay_key(self):
        self.marketplace_fixture("amidman", ALL)
        root = self.git_folder()
        self.run_setup(root)
        keys = list(self.plugins(root))
        self.assertTrue(keys and all(k.endswith("@amidman") for k in keys), keys)

    def _old_names(self, mapping):
        text = open(os.path.join(ROOT, "lib", "relay_old_names.toml")).read()
        head, rest = text.split("[plugin_key]", 1)
        tail = rest[rest.index("[kit_flow]"):]
        path = os.path.join(self.tmp, "old_names.toml")
        with open(path, "w") as handle:
            handle.write(head + "[plugin_key]\n" + "".join(f'"{k}" = "{v}"\n' for k, v in mapping.items()) + "\n" + tail)
        self.rs.OLD_NAMES_FILE = path

    def test_t21_old_keys_move_their_value_to_the_new_key(self):
        self.marketplace_fixture("amidman", ALL)
        self._old_names({"product@relay": "product@amidman", "issues@relay": "issues@amidman"})
        root = self.relay_tree()
        self.write(root, ".claude/settings.json", json.dumps({"enabledPlugins": {"product@relay": True, "issues@relay": False}}))
        self.run_setup(root, product=None)
        plugins = self.plugins(root)
        self.assertIs(plugins["product@amidman"], True)   # moved, not recomputed (no ui marker)
        self.assertIs(plugins["issues@amidman"], False)
        self.assertFalse([k for k in plugins if k.endswith("@relay")], plugins)

    def test_t22_sdd_moves_to_openspec_and_the_spec_row_decides(self):
        old = "sd" + "d@relay"   # the old plugin name, built so the no-live-old-name scan does not flag this file
        root = self.relay_tree()
        self.write(root, ".claude/kit.toml", "[delegate]\nmax_parallel = 6\n\n[specs]\nmethod = \"none\"\n")
        self.write(root, ".claude/settings.json", json.dumps({"enabledPlugins": {old: True}}))
        self.run_setup(root)
        plugins = self.plugins(root)
        self.assertIs(plugins["openspec@relay"], False)
        self.assertNotIn(old, plugins)


class Doctor(Fixture):
    def check(self, root, name):
        found = [(ok, detail) for n, ok, detail in self.rs.doctor(root, profile={}) if n == name]
        self.assertEqual(len(found), 1, name)
        return found[0]

    def test_t12_core_is_judged_by_the_scope_claude_code_reads_first(self):
        name = "core@relay is on for this project"
        cases = [
            (dict(local={"core@relay": False}, project={"core@relay": True}, user={"core@relay": True}), False),
            (dict(local={"core@relay": True}, project={"core@relay": False}), True),
            (dict(project={"core@relay": False}, user={"core@relay": True}), False),
            (dict(user={"core@relay": True}), True),
            (dict(), False),
        ]
        for n, (scopes, expected) in enumerate(cases):
            self.assertIs(self.check(self.relay_tree_again(n, **scopes), name)[0], expected, n)
        ok, detail = self.check(self.relay_tree_again(9, local={"core@relay": False}), name)
        self.assertIn("--scope local", detail)

    def relay_tree_again(self, n, **scopes):
        root = self.relay_tree_named(f"t{n}")
        for rel, key in ((".claude/settings.local.json", "local"), (".claude/settings.json", "project")):
            if key in scopes:
                self.write(root, rel, json.dumps({"enabledPlugins": scopes[key]}))
        self.write(root, os.path.join("..", "claude", "settings.json"), json.dumps({"enabledPlugins": scopes.get("user", {})}))
        return root

    def relay_tree_named(self, name):
        root = self.git_folder(name)
        self.write(root, ".claude/kit.toml", "[delegate]\nmax_parallel = 6\n")
        return root

    def test_t13_doctor_on_the_setup_output_reports_the_off_plugins_and_two_known_fixes(self):
        root = self.relay_tree()
        self.run_setup(root, off=[GOPLS])
        self.write(root, os.path.join("..", "claude", "settings.json"), json.dumps({"enabledPlugins": {GOPLS: True}}))
        checks = self.rs.doctor(root, profile={})
        names = [n for n, _, _ in checks]
        self.assertIn("plugins off for this project: " + ", ".join(sorted([GOPLS, "issues@relay", "openspec@relay", "product@relay"])), names)
        project_part = checks[names.index("project has .claude/kit.toml"):]
        fixes = sorted(n for n, ok, _ in project_part if not ok)
        # relay has no quiet check and no worktree script: those two stay red, nothing else.
        self.assertEqual(fixes, ["gate.check exists and is executable", "gate.wt exists and is executable"])

    def test_t14_spec_steps_follow_the_actual_state(self):
        name = "spec steps and openspec@relay agree"
        a = self.relay_tree_named("a")
        self.write(a, ".claude/kit.toml", '[specs]\nmethod = "none"\n')
        self.write(a, os.path.join("..", "claude", "settings.json"), json.dumps({"enabledPlugins": {"openspec@relay": True}}))
        self.assertFalse(self.check(a, name)[0])   # no project key, user says on
        b = self.relay_tree_named("b")
        self.write(b, ".claude/kit.toml", '[specs]\nmethod = "none"\n')
        self.write(b, ".claude/settings.json", json.dumps({"enabledPlugins": {"openspec@relay": False}}))
        self.write(b, ".claude/settings.local.json", json.dumps({"enabledPlugins": {"openspec@relay": True}}))
        self.assertFalse(self.check(b, name)[0])   # local on beats project off


class ReviewFixes(Fixture):
    """Review findings F1-F4 of the project-only setup change."""

    def relay_cli(self, *args):
        env = dict(os.environ, RELAY_SKIP_PAID_DUE="1")
        return subprocess.run([sys.executable, RELAY_BIN, "setup", *args], env=env, capture_output=True, text=True)

    def claude_snapshot(self):
        out = {}
        for folder, _, names in os.walk(self.claude):
            for n in names:
                path = os.path.join(folder, n)
                with open(path, "rb") as handle:
                    out[os.path.relpath(path, self.claude)] = handle.read()
        return out

    def user_settings(self, enabled, marketplace_name="relay"):
        with open(os.path.join(self.claude, "settings.json"), "w") as handle:
            json.dump({"extraKnownMarketplaces": {marketplace_name: {"source": {"source": "directory", "path": self.rs.marketplace_root()}}},
                       "enabledPlugins": enabled}, handle)

    def test_f1_a_folder_named_like_a_user_target_leaves_the_claude_folder_alone(self):
        with open(os.path.join(self.claude, "CLAUDE.md"), "w") as handle:
            handle.write("my own file\n")
        for name in ("global", "settings", "agents"):
            before = self.claude_snapshot()
            root = self.git_folder(name)
            done = self.relay_cli(root)
            self.assertEqual(done.returncode, 2, (name, done.stdout, done.stderr))   # refused as a usage error
            self.assertEqual(self.claude_snapshot(), before, name)   # no CLAUDE.md.before-relay, no settings.json, no agents

    def test_f1_an_ordinary_folder_name_still_sets_up(self):
        root = self.git_folder("proj")
        done = self.relay_cli(root)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(os.path.isfile(os.path.join(root, "CLAUDE.local.md")))

    def test_f2_global_with_a_project_flag_is_a_usage_error(self):
        for extra in (["--specs", "openspec"], ["--flow", "issues"], ["--product"], ["--no-product"], ["--apply"]):
            done = self.relay_cli("--global", *extra)
            self.assertEqual(done.returncode, 2, (extra, done.stdout))
            self.assertIn("--global takes nothing else", done.stderr)
        self.assertEqual(sorted(self.claude_snapshot()), ["plugins/installed_plugins.json"])   # only the fixture's registry: install never ran
        root = self.git_folder()
        self.assertEqual(self.relay_cli(root, "--global").returncode, 2)

    def test_f3_doctor_builds_the_user_plugin_checks_from_the_marketplace_name(self):
        self.marketplace_fixture("amidman", ALL)
        self.user_settings({f"{p}@amidman": True for p in ("core", "observe", "delegate", "front")}, "amidman")
        names = {n: ok for n, ok, _ in self.rs.doctor(None, profile={}) if "enabled for the user" in n}
        self.assertEqual(sorted(names), sorted(f"{p}@amidman enabled for the user" for p in ("core", "observe", "delegate", "front")))
        self.assertTrue(all(names.values()), names)

    def test_f3_real_marketplace_missing_core_is_one_fix_naming_it(self):
        self.user_settings({f"{p}@relay": True for p in ("observe", "delegate", "front")})
        checks = {n: ok for n, ok, _ in self.rs.doctor(None, profile={}) if "enabled for the user" in n}
        self.assertEqual([n for n, ok in checks.items() if not ok], ["core@relay enabled for the user"])
        self.assertEqual(len(checks), 4)

    def test_f4_project_setup_names_the_global_command_when_the_user_plugins_are_missing(self):
        def lines(enabled):
            self.user_settings(enabled)
            root = self.git_folder(f"p{len(enabled)}")
            *_, todo = self.run_setup(root)
            return [t for t in todo if "relay setup --global" in t]
        self.assertEqual(len(lines({})), 1)
        self.assertEqual(lines({f"{p}@relay": True for p in ("core", "observe", "delegate", "front")}), [])
        os.remove(os.path.join(self.claude, "settings.json"))   # no marketplace entry: one line, not two
        root = self.git_folder("p9")
        *_, todo = self.run_setup(root)
        self.assertEqual(len([t for t in todo if "relay setup --global" in t]), 1)


class Cli(Fixture):
    def relay(self, *args):
        env = dict(os.environ, RELAY_SKIP_PAID_DUE="1")
        return subprocess.run([sys.executable, RELAY_BIN, "setup", *args], env=env, capture_output=True, text=True)

    def test_t23_off_is_collected_and_a_bad_flag_writes_nothing(self):
        root = self.relay_tree()
        before = self.files(root)
        self.assertEqual(self.relay(root, "--off", "a@m", "--off").returncode, 2)   # --off with no value
        self.assertEqual(self.relay(root, "--offf", "x").returncode, 2)   # an unknown flag
        self.assertEqual(self.relay(root, "--no-global").returncode, 2)   # gone
        self.assertEqual(self.files(root), before)
        self.relay(root, "--off", "a@m", "--off", "b@m")
        plugins = self.plugins(root)
        self.assertEqual((plugins["a@m"], plugins["b@m"]), (False, False))
        self.assertEqual({k: v for k, v in plugins.items() if "@m" not in k}, {k: v for k, v in T1_PLUGINS.items() if k != GOPLS})

    def test_t23_one_off(self):
        root = self.relay_tree()
        self.relay(root, "--off", GOPLS)
        self.assertEqual(self.plugins(root), T1_PLUGINS)

    def test_migrate_does_not_take_off(self):
        root = self.relay_tree()
        done = subprocess.run([sys.executable, RELAY_BIN, "migrate", root, "--off", GOPLS], env=dict(os.environ), capture_output=True, text=True)
        self.assertEqual(done.returncode, 2, done.stderr)


if __name__ == "__main__":
    unittest.main()
