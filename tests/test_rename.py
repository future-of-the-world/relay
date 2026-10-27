"""relay's plugins are X@amidman, the core plugin is `relay`, and relay's own repo turns its plugins on (28 Oct rename)."""
import json
import os
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
        self.assertFalse(os.path.exists(os.path.join(ROOT, "plugins", "core")))

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


if __name__ == "__main__":
    unittest.main()
