#!/usr/bin/env bash
# Tests for `kit spec-check` over synthetic spec deltas in a temporary git repo whose
# .claude/kit.toml is Kartoteka's (tests/profiles/kartoteka.toml). Ported from
# ~/kartoteka/bin/spec-check.test.sh.
#   plugins/core/tests/spec-check.test.sh     prints each case and exits 1 on any failure
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd -P)"
kit="$here/../bin/kit"
check=("$kit" spec-check)
tmp="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT
cd "$tmp" && git init -q .
mkdir -p .claude && cp "$here/profiles/kartoteka.toml" .claude/kit.toml
mkdir -p "$tmp/specs/settings" "$tmp/specs/shell" "$tmp/specs/dial" "$tmp/specs/main"

cat >"$tmp/specs/settings/spec.md" <<'EOF'
## ADDED Requirements

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
EOF

cat >"$tmp/specs/shell/spec.md" <<'EOF'
## ADDED Requirements

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
EOF

cat >"$tmp/specs/dial/spec.md" <<'EOF'
## MODIFIED Requirements

### Requirement: The dial turns
A press SHALL turn the dial one step.

#### Scenario: One press
- **WHEN** the dial is at 3 and is pressed once
- **THEN** it is at 4

### Requirement: Colour states
The dial turns red near the end.

#### Scenario: Near the end
- **WHEN** the dial is past nine tenths
EOF

# A main spec has no delta headers and is checked whole.
cat >"$tmp/specs/main/spec.md" <<'EOF'
# Main

### Requirement: Keep the last tab
The app SHALL save the last tab.

#### Scenario: Reopened
- **WHEN** the app is reopened
- **THEN** the last tab is selected
EOF

out="$("${check[@]}" --path "$tmp/specs")"
status=$?
fails=0
pass() { echo "ok   $1"; }
flunk() { echo "FAIL $1"; fails=$((fails + 1)); }
expect() { grep -qF -- "$1" <<<"$out" && pass "$1" || flunk "expected: $1"; }
refute() { grep -qF -- "$1" <<<"$out" && flunk "unexpected: $1" || pass "no $1"; }

[ "$status" -eq 1 ] && pass "exits 1 on problems" || flunk "exits 1 on problems (got $status)"
refute '"Save the settings"'
expect '"Restore the theme": missing failure scenario: Corrupt data; missing failure scenario: Older data; missing failure scenario: Storage unavailable'
expect '"Persist the counter": missing failure scenario: Storage unavailable'
expect '"Keep the last position": missing failure scenario: Older data'
expect '"Migrate the settings": missing failure scenario: Corrupt data'
refute '"Skipped cases"'
refute '"Partial skip"'
grep -F '"Bad skip"' <<<"$out" | grep -qF 'skip without a reason' \
  && pass '"Bad skip": skip without a reason' || flunk 'expected: "Bad skip": skip without a reason'
refute '"A loading line"'
refute '"Old storage"'
refute '"Haptic feedback"'
expect '"Status bar style": missing failure scenario: Plain browser'
expect '"Native save": missing failure scenario: Corrupt data; missing failure scenario: Older data; missing failure scenario: Storage unavailable; missing failure scenario: Plain browser'
refute '"The dial turns"'
expect '"Colour states": no SHALL/MUST statement'
expect 'scenario "Near the end" lacks WHEN or THEN'
expect 'main/spec.md: "Keep the last tab": missing failure scenario: Corrupt data'
expect 'spec-check: 15 requirement(s), 12 touching stored data or the native shell, 9 with problems'

# A change: the deltas, then its tasks through kit packet --check.
c=openspec/changes/demo
mkdir -p "$c/specs/dial" docs
cp "$tmp/specs/dial/spec.md" "$c/specs/dial/spec.md"
printf '# Guide\n' >docs/guide.md
out="$("${check[@]}" demo 2>&1)"; status=$?
[ "$status" -eq 1 ] && pass "a change with form problems exits 1" || flunk "a change with form problems exits 1 (got $status)"
refute "packet:"

cat >"$c/specs/dial/spec.md" <<'EOF'
## ADDED Requirements

### Requirement: The dial turns
A press SHALL turn the dial one step.

#### Scenario: One press
- **WHEN** the dial is at 3 and is pressed once
- **THEN** it is at 4
EOF
printf '## 1. G\n\n- [ ] 1.1 Dial. Reads: dial "The dial turns"; file docs/guide.md. Tests: dial "One press". Files: src/widget/dial.ts. Check: `true`\n' >"$c/tasks.md"
out="$("${check[@]}" demo 2>&1)"; status=$?
[ "$status" -eq 0 ] && pass "a clean change exits 0" || flunk "a clean change exits 0 (got $status): $out"
expect "spec-check: 1 requirement(s), 0 touching stored data or the native shell, 0 with problems"
expect "packet: 1 open task(s), 0 problem(s)"

printf '## 1. G\n\n- [ ] 1.1 Dial. Reads: dial "The dial turns". Tests: dial "No such". Files: src/widget/dial.ts.\n' >"$c/tasks.md"
out="$("${check[@]}" demo 2>&1)"; status=$?
[ "$status" -eq 1 ] && pass "a task problem fails the change" || flunk "a task problem fails the change (got $status)"
expect "task 1.1: Check: missing"
expect 'has no scenario "No such"'

"${check[@]}" >/dev/null 2>&1
[ $? -eq 2 ] && pass "no arguments prints usage and exits 2" || flunk "no arguments prints usage and exits 2"
"${check[@]}" nochange >/dev/null 2>&1
[ $? -eq 2 ] && pass "a change without spec deltas exits 2" || flunk "a change without spec deltas exits 2"

echo
[ "$fails" -eq 0 ] && echo "spec-check.test: all passed" || echo "spec-check.test: $fails failed"
[ "$fails" -eq 0 ]
