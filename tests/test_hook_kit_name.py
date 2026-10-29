"""Port of plugins/relay/tests/kit-name.test.sh. The helper is called `kit`, a common command name (KitOps ships one).
Claude Code puts a plugin's bin/ on the Bash tool's PATH AFTER the user's own entries, so another `kit` on this machine's PATH
would silently take over every agent's `kit` call. This test fails when one exists, and says what to do."""
import filecmp
import os
import tempfile
import unittest

from hook_helpers import ROOT, SoftCases

OURS = os.path.join(ROOT, "plugins", "relay", "bin", "kit")


def is_ours(candidate: str) -> bool:
    """Is it a copy of this plugin's bin/kit (this checkout, another checkout or worktree of it, an install)?"""
    real = os.path.realpath(candidate)
    if real.endswith("/plugins/relay/bin/kit"):
        return True
    return filecmp.cmp(candidate, OURS, shallow=False)


class KitName(SoftCases):
    def test_old_core_folder_is_not_exempt(self) -> None:
        # a kit under the pre-rename folder plugins/core/bin differs in path and (here) in content, so it is another kit
        with tempfile.TemporaryDirectory() as tmp:
            old = os.path.join(tmp, "plugins", "core", "bin")
            os.makedirs(old)
            fake = os.path.join(old, "kit")
            with open(fake, "w") as handle:
                handle.write("#!/bin/sh\necho other\n")
            self.assertFalse(is_ours(fake))

    def test_no_other_kit_on_path(self) -> None:
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            candidate = os.path.join(directory, "kit")
            if directory and os.path.isfile(candidate) and os.access(candidate, os.X_OK) and not is_ours(candidate):
                self.fail("'%s' is on PATH and would shadow the plugin's kit helper inside Claude's Bash tool. Rename this plugin's "
                          "helper (bin/kit and every 'kit ' call in agents, skills, docs, Bash(kit:*) permissions) or remove that program." % candidate)


if __name__ == "__main__":
    unittest.main()
