"""relay's plugins are X@amidman, the core plugin is `relay`, and relay's own repo turns its plugins on (28 Oct rename)."""
import json
import os
import subprocess
import unittest

from relay_testbase import Base, ROOT

PLUGINS = ("relay", "delegate", "front", "observe", "openspec")


def load(*parts: str) -> dict:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return json.load(handle)


class Layout(unittest.TestCase):
    def test_the_marketplace_is_amidman_and_lists_the_five_plugins_with_matching_folders(self) -> None:
        market = load(".claude-plugin", "marketplace.json")
        self.assertEqual(market["name"], "amidman")
        self.assertEqual(sorted(p["name"] for p in market["plugins"]), sorted(PLUGINS))
        for entry in market["plugins"]:
            self.assertEqual(entry["source"], "./plugins/" + entry["name"])   # the folder is the plugin's name
            manifest = load("plugins", entry["name"], ".claude-plugin", "plugin.json")
            self.assertEqual(manifest["name"], entry["name"])

    def test_the_merge_hook_loads_from_the_relay_plugin_in_the_new_layout(self) -> None:
        # Claude Code runs "${CLAUDE_PLUGIN_ROOT}/hooks/merge.sh" of plugin relay@amidman: that file must be at plugins/relay/hooks.
        hooks = load("plugins", "relay", "hooks", "hooks.json")
        commands = [h["command"] for g in hooks["hooks"]["PreToolUse"] for h in g["hooks"]]
        self.assertIn('"${CLAUDE_PLUGIN_ROOT}/hooks/merge.sh"', commands)
        self.assertTrue(os.access(os.path.join(ROOT, "plugins", "relay", "hooks", "merge.sh"), os.X_OK))
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "plugins", "relay", "hooks", "merge.py")))
        # git ships no plugins/core; ignored leftovers (__pycache__, node_modules) of an old checkout may remain on disk
        tracked = subprocess.run(["git", "-C", ROOT, "ls-files", "--", "plugins/core"], capture_output=True, text=True, check=True)
        self.assertEqual(tracked.stdout.strip(), "")

    def test_relays_own_repo_turns_on_its_plugins_and_off_the_ones_it_does_not_use(self) -> None:
        enabled = load(".claude", "settings.json")["enabledPlugins"]
        self.assertEqual(enabled, {
            "relay@amidman": True, "delegate@amidman": True, "front@amidman": True, "observe@amidman": True,
            "openspec@amidman": False, "gopls-lsp@claude-plugins-official": False})


class GlobalSettings(Base):
    def test_setup_global_writes_the_new_ids_and_removes_the_old_ones(self) -> None:
        import relay_setup
        user = os.path.join(self.claude, "settings.json")
        os.makedirs(self.claude, exist_ok=True)
        old = {f"{p}@relay": True for p in ("core", "observe", "delegate", "front")}
        with open(user, "w", encoding="utf-8") as handle:
            json.dump({"enabledPlugins": {**old, "other@m": True},
                       "extraKnownMarketplaces": {"relay": {"source": {"source": "directory", "path": "/x"}}, "m": {}}}, handle)
        relay_setup.merge_user_settings(list(relay_setup.ALWAYS_ON))
        data = json.load(open(user, encoding="utf-8"))
        self.assertEqual(sorted(data["enabledPlugins"]),
                         ["delegate@amidman", "front@amidman", "observe@amidman", "other@m", "relay@amidman"])
        self.assertEqual(sorted(data["extraKnownMarketplaces"]), ["amidman", "m"])


class RegistryLeftovers(Base):
    """F1: Claude Code's own registry keeps marketplace `relay` and the X@relay user installs until setup removes them."""

    def registry(self, installs: dict, markets: dict) -> None:
        folder = os.path.join(self.claude, "plugins")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "installed_plugins.json"), "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "plugins": installs}, handle)
        with open(os.path.join(folder, "known_marketplaces.json"), "w", encoding="utf-8") as handle:
            json.dump(markets, handle)

    def fake_claude(self) -> str:
        """A `claude` on PATH that appends its argv to a log; returns the log's path."""
        log = os.path.join(self.tmp, "calls.log")
        bindir = os.path.join(self.tmp, "fakebin")
        os.makedirs(bindir)
        exe = os.path.join(bindir, "claude")
        with open(exe, "w", encoding="utf-8") as handle:
            handle.write('#!/bin/sh\necho "$*" >> "%s"\n' % log)
        os.chmod(exe, 0o755)
        os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]
        return log

    def calls(self, log: str) -> list[str]:
        return open(log, encoding="utf-8").read().splitlines() if os.path.exists(log) else []

    def test_old_installs_and_marketplace_are_removed_before_the_new_marketplace_is_added(self) -> None:
        import relay_setup
        old = {f"{p}@relay": [{"scope": "user"}] for p in ("core", "observe", "delegate", "front")}
        self.registry(old, {"relay": {"source": {"source": "directory", "path": "/x"}}})
        log = self.fake_claude()
        relay_setup.install(run_claude=True)
        calls = self.calls(log)
        add = f"plugin marketplace add {relay_setup.marketplace_root()}"
        self.assertIn(add, calls)
        # four uninstalls and the marketplace removal, all before the add; then the four installs of X@amidman
        before = calls[:calls.index(add)]
        self.assertEqual(sorted(before), sorted([f"plugin uninstall {p}@relay --scope user" for p in ("core", "observe", "delegate", "front")] + ["plugin marketplace remove relay"]))
        after = calls[calls.index(add) + 1:]
        self.assertEqual(after, [f"plugin install {p}@amidman --scope user" for p in relay_setup.ALWAYS_ON])

    def test_a_clean_registry_gets_no_uninstall_or_remove(self) -> None:
        import relay_setup
        self.registry({}, {})
        log = self.fake_claude()
        relay_setup.install(run_claude=True)
        calls = self.calls(log)
        self.assertEqual([c for c in calls if " uninstall " in c or "marketplace remove" in c], [])
        self.assertEqual(len([c for c in calls if c.startswith("plugin install ")]), 4)
        self.assertIn(f"plugin marketplace add {relay_setup.marketplace_root()}", calls)

    def test_without_claude_the_todo_names_the_removal_steps(self) -> None:
        import relay_setup
        self.registry({"observe@relay": [{"scope": "user"}]}, {"relay": {}})
        _, todo = relay_setup.install(run_claude=False)
        self.assertIn("run: claude plugin uninstall observe@relay --scope user", todo)
        self.assertIn("run: claude plugin marketplace remove relay", todo)

    def test_doctor_names_a_user_scope_old_install_and_the_command_that_removes_it(self) -> None:
        import relay_setup
        self.registry({"observe@relay": [{"scope": "user"}]}, {})
        lines = relay_setup.unshipped_installs()
        self.assertEqual(len(lines), 1)
        self.assertIn("observe@relay", lines[0])
        self.assertIn("claude plugin uninstall observe@relay --scope user", lines[0])


if __name__ == "__main__":
    unittest.main()
