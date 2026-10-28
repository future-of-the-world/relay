"""Port of plugins/relay/tests/flow-stage.test.sh: the flow-stage hook stays silent without a binding, for openspec, and for kind none."""
import json
import os
import tempfile
import unittest

from hook_helpers import ROOT, run_hook, SoftCases

HOOK = os.path.join(ROOT, "plugins", "relay", "hooks", "flow-stage.py")


class FlowStage(SoftCases):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = self.tmp.name
        os.makedirs(os.path.join(self.proj, ".claude"))

    def out(self) -> str:
        event = {"hook_event_name": "UserPromptSubmit", "cwd": self.proj, "prompt": "/opsx:apply x"}
        return run_hook(HOOK, json.dumps(event), {"RELAY_ROOT": ROOT})

    def write_kit(self, text: str) -> None:
        with open(os.path.join(self.proj, ".claude", "kit.toml"), "w") as handle:
            handle.write(text)

    def test_no_binding_silent(self) -> None:
        self.assertEqual(self.out(), "")

    def test_openspec_core_stays_silent_on_opsx_apply(self) -> None:
        # the spec method's line is the openspec plugin's hook now; core cannot know the plugin is loaded
        self.write_kit('[specs]\nmethod = "openspec"\n')
        self.assertEqual(self.out(), "")

    def test_kind_none_silent(self) -> None:
        self.write_kit('[flow]\nkind = "none"\n')
        self.assertEqual(self.out(), "")


if __name__ == "__main__":
    unittest.main()
