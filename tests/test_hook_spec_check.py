"""Port of plugins/relay/tests/spec-check.test.sh: `kit spec-check` over synthetic spec deltas in a temporary git repo
whose .claude/kit.toml is Kartoteka's (tests/profiles/kartoteka.toml)."""
import os
import shutil
import subprocess
import tempfile
import unittest
from typing import Tuple

from hook_helpers import ROOT, SoftCases

CORE = os.path.join(ROOT, "plugins", "relay")
KIT = os.path.join(CORE, "bin", "kit")

SPEC_SETTINGS = """## ADDED Requirements

### Requirement: Save the settings
The app SHALL save the settings after every change.

#### Scenario: Setting changed
- **WHEN** the theme is changed to dark
- **THEN** the dark theme is shown after a reload

#### Scenario: Corrupt data
- **WHEN** the saved text is not valid JSON
- **THEN** the app starts with the default settings

#### Scenario: Older data
- **WHEN** the settings were saved before the text size existed and have a missing field
- **THEN** the text size is the default and the rest is kept

#### Scenario: Storage unavailable
- **WHEN** storage is blocked, as in a private window
- **THEN** the change still applies and lasts for the session

### Requirement: Restore the theme
The app SHALL restore the chosen theme on start.

#### Scenario: Theme kept
- **WHEN** the user chose dark and reopens the app
- **THEN** dark is selected

### Requirement: Persist the counter
The counter MUST persist between sessions.

#### Scenario: Hand-edited count
- **WHEN** the count was hand-edited to a negative number
- **THEN** the counter is 0

#### Scenario: Old data
- **WHEN** an older version of the data has no counter
- **THEN** the counter is 0

### Requirement: Keep the last position
The app SHALL store the last position of the dial.

#### Scenario: Garbage position
- **WHEN** the position is garbage
- **THEN** the dial starts at zero

#### Scenario: Full storage
- **WHEN** the write throws because the quota is used up
- **THEN** the old position is kept

### Requirement: Migrate the settings
The app SHALL migrate version 1 settings to version 2.

#### Scenario: Unknown version
- **WHEN** the settings have an unknown version
- **THEN** they are treated as no data

#### Scenario: Cannot write
- **GIVEN** the app cannot write the migrated settings
- **WHEN** it starts
- **THEN** it goes on with the migrated settings in memory

### Requirement: Skipped cases
The help page SHALL show the help text stored in the bundle.
<!-- spec-check: skip all (the help text is bundled, nothing is read back) -->

#### Scenario: Help shown
- **WHEN** the user opens help
- **THEN** its title is shown

### Requirement: Partial skip
The app SHALL store the sound setting.
<!-- spec-check: skip Older data, Storage unavailable (a new boolean with a default; writes go through browserStore) -->

#### Scenario: Wrong type
- **WHEN** the stored value has the wrong type
- **THEN** sound is on

### Requirement: Bad skip
The app SHALL store the last tab.
<!-- spec-check: skip all -->

#### Scenario: Tab kept
- **WHEN** the app reopens
- **THEN** the last tab is selected

### Requirement: A loading line
The page SHALL show one line while its content is loading.

#### Scenario: Still loading
- **WHEN** the content has not arrived after 1 s
- **THEN** the line is shown

## REMOVED Requirements

### Requirement: Old storage
The app stored nothing.
"""

SPEC_SHELL = """## ADDED Requirements

### Requirement: Haptic feedback
A press on a disabled button SHALL give a short vibration on a phone.

#### Scenario: Press on a phone
- **WHEN** the user presses a disabled button in the iOS app
- **THEN** the phone vibrates once

#### Scenario: Plain browser
- **WHEN** the app runs in a plain browser
- **THEN** nothing happens

### Requirement: Status bar style
The app SHALL match the status bar to the theme.

#### Scenario: Dark theme
- **WHEN** the theme is dark
- **THEN** the status bar text is light

### Requirement: Native save
The app SHALL save the settings through a Tauri plugin.

#### Scenario: Saved
- **WHEN** a setting changes
- **THEN** the new value is there after a restart
"""

SPEC_DIAL = """## MODIFIED Requirements

### Requirement: The dial turns
A press SHALL turn the dial one step.

#### Scenario: One press
- **WHEN** the dial is at 3 and is pressed once
- **THEN** it is at 4

### Requirement: Colour states
The dial turns red near the end.

#### Scenario: Near the end
- **WHEN** the dial is past nine tenths
"""

SPEC_MAIN = """# Main

### Requirement: Keep the last tab
The app SHALL save the last tab.

#### Scenario: Reopened
- **WHEN** the app is reopened
- **THEN** the last tab is selected
"""

SPEC_DIAL_CLEAN = """## ADDED Requirements

### Requirement: The dial turns
A press SHALL turn the dial one step.

#### Scenario: One press
- **WHEN** the dial is at 3 and is pressed once
- **THEN** it is at 4
"""

GUIDE_TASK = "## 1. G\n\nWave 0 \u00b7 depends on: none\n\n- [ ] 1.1 Dial. Reads: dial \"The dial turns\"; file docs/guide.md. Tests: dial \"One press\". Files: src/widget/dial.ts. Check: `true`\n"
BAD_TASK = "## 1. G\n\n- [ ] 1.1 Dial. Reads: dial \"The dial turns\". Tests: dial \"No such\". Files: src/widget/dial.ts.\n"


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


class SpecCheck(SoftCases):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = os.path.realpath(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q", "."], cwd=cls.tmp, check=True)
        os.makedirs(os.path.join(cls.tmp, ".claude"))
        shutil.copy(os.path.join(CORE, "tests", "profiles", "kartoteka.toml"), os.path.join(cls.tmp, ".claude", "kit.toml"))
        for name, text in (("settings", SPEC_SETTINGS), ("shell", SPEC_SHELL), ("dial", SPEC_DIAL), ("main", SPEC_MAIN)):
            write(os.path.join(cls.tmp, "specs", name, "spec.md"), text)
        cls.rc, cls.out = cls.check("--path", os.path.join(cls.tmp, "specs"))

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def check(cls, *args: str) -> Tuple[int, str]:
        done = subprocess.run([KIT, "spec-check"] + list(args), cwd=cls.tmp, capture_output=True, text=True, encoding="utf-8")
        return done.returncode, done.stdout + done.stderr

    def has(self, text: str) -> None:
        self.assertIn(text, self.out)

    def test_specs_report(self) -> None:
        self.assertEqual(self.rc, 1)  # exits 1 on problems
        for req in ("Save the settings", "Skipped cases", "Partial skip", "A loading line", "Old storage", "Haptic feedback", "The dial turns"):
            self.assertNotIn('"%s"' % req, self.out, req)
        self.has('"Restore the theme": missing failure scenario: Corrupt data; missing failure scenario: Older data; missing failure scenario: Storage unavailable')
        self.has('"Persist the counter": missing failure scenario: Storage unavailable')
        self.has('"Keep the last position": missing failure scenario: Older data')
        self.has('"Migrate the settings": missing failure scenario: Corrupt data')
        bad = [line for line in self.out.splitlines() if '"Bad skip"' in line]
        self.assertTrue(bad and "skip without a reason" in bad[0], bad)
        self.has('"Status bar style": missing failure scenario: Plain browser')
        self.has('"Native save": missing failure scenario: Corrupt data; missing failure scenario: Older data; missing failure scenario: Storage unavailable; missing failure scenario: Plain browser')
        self.has('"Colour states": no SHALL/MUST statement')
        self.has('scenario "Near the end" lacks WHEN or THEN')
        self.has('main/spec.md: "Keep the last tab": missing failure scenario: Corrupt data')
        self.has("spec-check: 15 requirement(s), 12 touching stored data or the native shell, 9 with problems")

    def test_change_tasks_through_packet_check(self) -> None:
        c = os.path.join(self.tmp, "openspec", "changes", "demo")
        write(os.path.join(c, "specs", "dial", "spec.md"), SPEC_DIAL)
        write(os.path.join(self.tmp, "docs", "guide.md"), "# Guide\n")
        rc, out = self.check("demo")
        self.assertEqual(rc, 1)  # a change with form problems
        self.assertNotIn("packet:", out)
        write(os.path.join(c, "specs", "dial", "spec.md"), SPEC_DIAL_CLEAN)
        write(os.path.join(c, "tasks.md"), GUIDE_TASK)
        rc, out = self.check("demo")
        self.assertEqual(rc, 0, out)
        self.assertIn("spec-check: 1 requirement(s), 0 touching stored data or the native shell, 0 with problems", out)
        self.assertIn("packet: 1 open task(s), 0 problem(s)", out)
        write(os.path.join(c, "tasks.md"), BAD_TASK)
        rc, out = self.check("demo")
        self.assertEqual(rc, 1)
        self.assertIn("task 1.1: Check: missing", out)
        self.assertIn('has no scenario "No such"', out)

    def test_usage_and_change_without_deltas_exit_2(self) -> None:
        self.assertEqual(self.check()[0], 2)
        self.assertEqual(self.check("nochange")[0], 2)


if __name__ == "__main__":
    unittest.main()
