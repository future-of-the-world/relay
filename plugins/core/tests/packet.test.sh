#!/usr/bin/env bash
# Tests for `kit packet` over a small synthetic change in a temporary repo, with
# Kartoteka's real bindings (tests/profiles/kartoteka.toml), then the Rust and
# Elixir module refs, smoke tests and fenced code with profiles of their own.
#   plugins/core/tests/packet.test.sh     prints each case and exits 1 on any failure
#
# `module` refs of the typescript kind run the TypeScript compiler, so the
# temporary repo links a node_modules with it. That is this folder's own
# ts-deps/ (package.json and bun.lock pin TypeScript); the first run installs it
# with `bun install --frozen-lockfile`. $KIT_TEST_NODE_MODULES overrides it. If
# no compiler can be had this file FAILS (exit 1): a skipped test would pass a
# gate that checked nothing.
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd -P)"
kit="$here/../bin/kit"
packet=("$kit" packet)
bindings="$here/profiles/kartoteka.toml"
modules="${KIT_TEST_NODE_MODULES:-$here/ts-deps/node_modules}"
if [ ! -x "$modules/.bin/tsc" ] && [ -z "${KIT_TEST_NODE_MODULES:-}" ]; then
  (cd "$here/ts-deps" && bun install --frozen-lockfile >/dev/null 2>&1)
fi
if [ ! -x "$modules/.bin/tsc" ]; then
  echo "FAIL packet.test: no TypeScript compiler at $modules/.bin/tsc." >&2
  echo "  Install it: cd $here/ts-deps && bun install --frozen-lockfile (needs bun and, on a" >&2
  echo "  first run, network or bun's package cache), or set KIT_TEST_NODE_MODULES=<dir>/node_modules." >&2
  exit 1
fi
tmp="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT
cd "$tmp" && git init -q .
ln -s "$modules" node_modules
mkdir -p .claude && cp "$bindings" .claude/kit.toml

c=openspec/changes/demo
mkdir -p "$c/specs/widgets" src/widget src/ui/parts src-tauri/src docs

cat >tsconfig.json <<'EOF'
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "jsxImportSource": "preact",
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true
  },
  "include": ["src"]
}
EOF

cat >"$c/design.md" <<'EOF'
# Design

## Decisions

### D1. Widgets spin

Widgets spin clockwise. D1-MARKER

### D2. Unrelated

D2-MARKER must not appear.

## Interfaces

spin returns the new angle. IFACE-MARKER
EOF

cat >"$c/specs/widgets/spec.md" <<'EOF'
## ADDED Requirements

### Requirement: Spinning
Widgets SHALL spin. SPIN-MARKER

#### Scenario: Fast spin
- **WHEN** asked
- **THEN** it spins

#### Scenario: Corrupt data
- **WHEN** the stored angle is garbage
- **THEN** it starts from zero

### Requirement: Stopping
Widgets SHALL stop. STOP-MARKER

#### Scenario: Corrupt data
- **WHEN** the stored angle is garbage
- **THEN** it stops
EOF

cat >src/widget/gear.ts <<'EOF'
/** The gear's state. GEAR-DOC-MARKER */
export interface Gear {
  /** Number of teeth. */
  readonly teeth: number;
}

/** Spins the gear once and returns the new angle. SPIN-DOC-MARKER */
export function spin(gear: Gear, angle: number): number {
  const bodyMarker = 'BODY_MARKER';
  return angle + gear.teeth + bodyMarker.length;
}

function freePrivate(): number {
  return 7;
}

/** A box of gears. */
export class GearBox {
  /** PRIVATE-DOC-MARKER */
  private secretCount = freePrivate();
  private secretHelper(): string {
    return 'private_must_not_appear';
  }
  /** How many gears it holds. */
  size(): number {
    return this.secretCount + this.secretHelper().length;
  }
}

export const MAX_TEETH = 64;
EOF

# A stub that does not type-check still has a contract.
cat >src/widget/stub.ts <<'EOF'
/** Not written yet. STUB-DOC-MARKER */
export function later(count: number): string {
  return count;
}
EOF

cat >src/ui/Panel.tsx <<'EOF'
export interface PanelProps {
  readonly title: string;
}

/** Shows a title. PANEL-DOC-MARKER */
export function Panel({ title }: PanelProps) {
  return <h1 class="PANEL_BODY_MARKER">{title}</h1>;
}
EOF

printf 'fn main() {}\n' >src-tauri/src/lib.rs
printf '.gear { color: red; }\n' >src/widget/gear.css

cat >docs/guide.md <<'EOF'
# Guide

## Setup

GUIDE-SETUP-MARKER

## Other

GUIDE-OTHER-MARKER
EOF

# A file with no headings, read by line range.
printf 'LINE-1-MARKER\nLINE-2-MARKER\nLINE-3-MARKER\nLINE-4-MARKER\nLINE-5-MARKER\nLINE-6-MARKER\n' >docs/sketch.html

cat >"$c/tasks.md" <<'EOF'
# Tasks

NOTES-MARKER for every task.

## 1. Widgets

Wave 1 · depends on: none

GROUP-MARKER

- [x] 1.1 Done already, no fields needed.
- [ ] 1.2 Build spinning. Reads: design D1; design "Interfaces"; widgets "Spinning"; module src/widget/gear.ts; file docs/guide.md "Setup". Tests: widgets "Fast spin", "Spinning / Corrupt data". Files: src/widget/gear.ts, src/widget/gear.test.ts. Check: `bun run test src/widget`
- [ ] 1.3 Missing fields. Files: src/a.ts. Check: `true`
- [ ] 1.4 Bad refs. Reads: design D9; nosuch "Thing"; module src/widget/nope.ts; module src/widget/gear.css; file docs/none.md. Tests: widgets "No such scenario". Files: src/a.ts. Check: `true`
- [ ] 1.5 Ambiguous. Reads: design D1. Tests: widgets "Corrupt data". Files: src/a.ts. Check: `true`
- [ ] 1.6 Qualified. Reads: design D1. Tests: widgets "Stopping / Corrupt data". Files: src/a.ts. Check: `true`
- [ ] 1.7 Too big. Reads: design D1. Tests: none (config only). Files: src/a.ts, src/b.tsx, src/c.ts, src-tauri/src/lib.rs, src/e.ts. Check: `true`
- [ ] 1.8 Big but mechanical. Reads: design D1. Tests: none (config only). Size: mechanical (one call renamed in each). Files: src/a.ts, src/b.ts, src/c.ts, src/d.ts, src/e.ts. Check: `true`
- [ ] 1.9 Tests and styles don't count. Reads: design D1. Tests: none (config only). Files: src/a.ts, src/a.test.ts, src/b.tsx, src/b.test.tsx, src/c.ts, src/d.ts, src/ui/styles.css, docs/guide.md, vite.config.ts. Check: `true`
- [ ] 1.10 Component without e2e. Reads: design D1. Tests: widgets "Fast spin". Files: src/ui/Panel.tsx, src/ui/Panel.test.tsx. Check: `true`
- [ ] 1.11 Nested component, none. Reads: design D1. Tests: none (a component). Files: src/ui/parts/Dial.tsx. Check: `true`
- [ ] 1.12 Component with e2e. Reads: design D1; module src/ui/Panel.tsx. Tests: widgets "Fast spin"; e2e "the panel shows its title", "the panel fits a phone". Files: src/ui/Panel.tsx, e2e/panel.spec.ts. Check: `true`
- [ ] 1.13 Component, e2e waived. Reads: design D1. Tests: none (copy only; nothing to assert); e2e none (covered by "the panel shows its title"). Files: src/ui/Panel.tsx. Check: `true`
- [ ] 1.14 Spec file without e2e. Reads: design D1. Tests: none (a helper). Files: e2e/panel.spec.ts. Check: `true`
- [ ] 1.15 A component's test, a style sheet and a plain module are not components. Reads: design D1. Tests: none (a test). Files: src/ui/Panel.test.tsx, src/ui/styles.css, src/ui/services.ts. Check: `true`
- [ ] 1.16 Bad e2e entry. Reads: design D1. Tests: e2e the panel. Files: src/ui/Panel.tsx. Check: `true`
- [ ] 1.17 Stub contract. Reads: module src/widget/stub.ts. Tests: e2e none (no component). Files: src/widget/stub.ts. Check: `true`
- [ ] 1.18 Scenarios and none. Reads: design D1. Tests: widgets "Fast spin"; none (nothing). Files: src/a.ts. Check: `true`
- [ ] 1.19 Lines of a file. Reads: design D1; file docs/sketch.html:2-4; file docs/sketch.html:6-6. Tests: none (docs). Files: docs/guide.md. Check: `true`
- [ ] 1.20 Bad line ranges. Reads: file docs/sketch.html:5-9; file docs/sketch.html:4-2; file docs/sketch.html:0-2; file docs/none.html:1-2; file docs/guide.md:1-2 "Setup". Tests: none (docs). Files: docs/guide.md. Check: `true`
EOF

fails=0
pass() { echo "ok   $1"; }
flunk() { echo "FAIL $1"; fails=$((fails + 1)); }

brief="$("${packet[@]}" demo 1.2 2>&1)"
status=$?
[ "$status" -eq 0 ] && pass "brief builds" || flunk "brief builds (exit $status): $brief"
for m in NOTES-MARKER GROUP-MARKER "1.2 Build spinning" D1-MARKER IFACE-MARKER SPIN-MARKER GUIDE-SETUP-MARKER \
  GEAR-DOC-MARKER SPIN-DOC-MARKER "export declare function spin(gear: Gear, angle: number): number;" \
  "readonly teeth: number;" "size(): number;" "export declare const MAX_TEETH = 64;" \
  'widgets: "Spinning" / "Corrupt data"' "the stored angle is garbage" "(brief: "; do
  grep -qF -- "$m" <<<"$brief" && pass "brief has $m" || flunk "brief has $m"
done
for m in D2-MARKER STOP-MARKER BODY_MARKER private_must_not_appear secretCount secretHelper PRIVATE-DOC-MARKER \
  freePrivate GUIDE-OTHER-MARKER "export {};"; do
  grep -qF -- "$m" <<<"$brief" && flunk "brief leaves out $m" || pass "brief leaves out $m"
done

# The scenario text is printed under its Tests entry although 1.6 does not read "Stopping".
tests_section="$("${packet[@]}" demo 1.6 2>&1 | sed -n '/^## Tests to write/,/^## What the task reads/p')"
grep -qF -- '- **THEN** it stops' <<<"$tests_section" \
  && pass "Tests to write prints the scenario text without Reads" || flunk "Tests to write prints the scenario text without Reads"
grep -qF -- 'it starts from zero' <<<"$tests_section" \
  && flunk "scenario text stays with its own requirement" || pass "scenario text stays with its own requirement"

e2e_brief="$("${packet[@]}" demo 1.12 2>&1)"
# Only the parts of the brief template that come from the engine; the wording after the title is the project's.
grep -qF -- '- e2e: "the panel shows its title" in e2e/, black-box: drive the built app through what is on the screen' <<<"$e2e_brief" \
  && grep -qF -- '- e2e: "the panel fits a phone" in e2e/' <<<"$e2e_brief" \
  && pass "brief lists each e2e test" || flunk "brief lists each e2e test: $e2e_brief"
grep -qF -- "PANEL-DOC-MARKER" <<<"$e2e_brief" && grep -qF -- "export declare function Panel(" <<<"$e2e_brief" \
  && ! grep -qF -- "PANEL_BODY_MARKER" <<<"$e2e_brief" \
  && pass "a .tsx module gives its contract" || flunk "a .tsx module gives its contract"

waived="$("${packet[@]}" demo 1.13 2>&1 | sed -n '/^## Tests to write/,/^## What the task reads/p')"
grep -qF -- '- none (copy only; nothing to assert)' <<<"$waived" \
  && grep -qF -- '- e2e: none (covered by "the panel shows its title")' <<<"$waived" \
  && pass "brief prints none and the e2e waiver with their reasons" || flunk "brief prints none and the e2e waiver: $waived"

stub="$("${packet[@]}" demo 1.17 2>&1)"
grep -qF -- "STUB-DOC-MARKER" <<<"$stub" && grep -qF -- "export declare function later(count: number): string;" <<<"$stub" \
  && pass "a stub that does not type-check still has a contract" || flunk "a stub that does not type-check still has a contract: $stub"

ranged="$("${packet[@]}" demo 1.19 2>&1)"
status=$?
[ "$status" -eq 0 ] && pass "a brief with line ranges builds" || flunk "a brief with line ranges builds (exit $status): $ranged"
for m in "### docs/sketch.html, lines 2 to 4" LINE-2-MARKER LINE-3-MARKER LINE-4-MARKER \
  "### docs/sketch.html, lines 6 to 6" LINE-6-MARKER; do
  grep -qF -- "$m" <<<"$ranged" && pass "line range has $m" || flunk "line range has $m"
done
for m in LINE-1-MARKER LINE-5-MARKER; do
  grep -qF -- "$m" <<<"$ranged" && flunk "line range leaves out $m" || pass "line range leaves out $m"
done

"${packet[@]}" demo 1.4 >/dev/null 2>&1
[ $? -eq 1 ] && pass "a task with bad refs gets no brief" || flunk "a task with bad refs gets no brief"
"${packet[@]}" demo 9.9 >/dev/null 2>&1
[ $? -eq 2 ] && pass "an unknown task exits 2" || flunk "an unknown task exits 2"
"${packet[@]}" >/dev/null 2>&1
[ $? -eq 2 ] && pass "no arguments prints usage and exits 2" || flunk "no arguments prints usage and exits 2"
"${packet[@]}" --check nochange >/dev/null 2>&1
[ $? -eq 2 ] && pass "--check of a change without tasks.md exits 2" || flunk "--check of a change without tasks.md exits 2"

out="$("${packet[@]}" --check demo)"
status=$?
[ "$status" -eq 1 ] && pass "--check fails" || flunk "--check fails (exit $status)"
expect() { grep -qF -- "$1" <<<"$out" && pass "--check: $1" || flunk "--check: $1"; }
refute() { grep -qF -- "$1" <<<"$out" && flunk "--check: no $1" || pass "--check: no $1"; }
refute "task 1.1:"
refute "task 1.2:"
expect "task 1.3: Reads: missing"
expect "task 1.3: Tests: missing"
expect 'no heading "D9"'
expect "unknown ref 'nosuch \"Thing\"'"
expect "no file for module src/widget/nope.ts"
expect 'module src/widget/gear.css: a module ref names a .ts or .tsx file; use `file src/widget/gear.css`'
expect "no file docs/none.md"
expect 'has no scenario "No such scenario"'
expect 'scenario "Corrupt data" is in 2 requirements'
refute "task 1.6:"
expect "task 1.7: lists 5 source files"
refute "task 1.8:"
refute "task 1.9:"
expect 'task 1.10: Tests: src/ui/Panel.tsx changes what the user sees: add e2e "<test title>"'
expect "task 1.11: Tests: src/ui/parts/Dial.tsx changes what the user sees"
refute "task 1.12:"
refute "task 1.13:"
expect "task 1.14: Tests: e2e/panel.spec.ts changes what the user sees"
refute "task 1.15:"
expect "task 1.16: bad Tests entry 'e2e the panel': use e2e \"<test title>\" or e2e none (<reason>)"
refute "task 1.17:"
expect "task 1.18: Tests: names scenarios and says none"
refute "task 1.19:"
expect "task 1.20: Reads: no lines 5-9 in docs/sketch.html: it has 6 lines"
expect "task 1.20: Reads: bad line range docs/sketch.html:4-2"
expect "task 1.20: Reads: bad line range docs/sketch.html:0-2"
expect "task 1.20: Reads: no file docs/none.html"
expect "a line range and a heading don't go together"
expect "packet: 19 open task(s)"

mkdir -p openspec/changes/bare
printf '## 1. G\n\nWave 1 · depends on: none\n\n- [ ] 1.1 X. Reads: file docs/guide.md. Tests: none (docs). Files: docs/guide.md. Check: `true`\n' \
  >openspec/changes/bare/tasks.md
printf '# Design\n' >openspec/changes/bare/design.md
out="$("${packet[@]}" --check bare)"
expect 'design.md: no "Interfaces" section'
printf '# Design\n\n## Interfaces\n\nNone.\n' >openspec/changes/bare/design.md
out="$("${packet[@]}" --check bare)"
status=$?
refute 'no "Interfaces" section'
[ "$status" -eq 0 ] && pass "--check passes a clean change" || flunk "--check passes a clean change (exit $status): $out"
out="$("${packet[@]}" --check demo)"
refute 'no "Interfaces" section'

# Group briefs: one context for a group's open tasks.

grefused="$("${packet[@]}" demo 1 2>&1)"
status=$?
[ "$status" -eq 1 ] && pass "a group with a bad task gets no brief" || flunk "a group with a bad task gets no brief (exit $status)"
grep -qF -- "task 1.3: Reads: missing" <<<"$grefused" \
  && pass "group refusal names the bad task" || flunk "group refusal names the bad task"

printf -- '- [ ] 1.2 Second small task. Reads: file docs/guide.md. Tests: none (docs). Files: docs/x.md. Check: `true`\n' \
  >>openspec/changes/bare/tasks.md
gbrief="$("${packet[@]}" bare 1 2>&1)"
status=$?
[ "$status" -eq 0 ] && pass "group brief builds" || flunk "group brief builds (exit $status): $gbrief"
for m in "## Task 1.1" "## Task 1.2" "in order, in one"; do
  grep -qF -- "$m" <<<"$gbrief" && pass "group brief has $m" || flunk "group brief has $m"
done
[ "$(grep -cF -- GUIDE-SETUP-MARKER <<<"$gbrief")" -eq 1 ] \
  && pass "group brief lists a shared Reads ref once" || flunk "group brief lists a shared Reads ref once"

# Artifact budgets: --check names a design, a tasks.md, a task, or group notes over budget.

fat=openspec/changes/fat
mkdir -p "$fat"
printf '# Design\n\n## Interfaces\n\nNone.\n' >"$fat/design.md"
python3 - "$fat/design.md" <<'PY'
import sys
with open(sys.argv[1], "a") as f:
    f.write("## D1. Filler\n\n" + "filler " * 9000 + "\n")
PY
{ printf '# Tasks\n\n## 1. G\n\nWave 1 · depends on: none\n\n'; \
  printf -- '- [ ] 1.1 Fat task. Reads: file docs/guide.md. Tests: none (fat). Files: docs/x.md. Check: `true` '; \
  python3 -c 'print("prose " * 400)'; } >"$fat/tasks.md"
python3 - "$fat/tasks.md" <<'PY'
import sys
with open(sys.argv[1], "a") as f:
    f.write("\n## 2. Wide notes\n\nWave 1 · depends on: none\n\n" + "notes " * 500 + "\n\n- [ ] 2.1 Thin task. Reads: file docs/guide.md. Tests: none (fat). Files: docs/y.md. Check: `true`\n")
    f.write("\n" + "task " * 9000 + "\n")  # push tasks.md past its 40 KB budget
PY
out="$("${packet[@]}" --check fat)"
status=$?
[ "$status" -eq 1 ] && pass "--check fails a fat change" || flunk "--check fails a fat change (exit $status)"
grep -qF -- "over the ~60 KB budget" <<<"$out" \
  && pass "--check flags a fat design.md" || flunk "--check flags a fat design.md"
grep -qF -- "over the ~1 KB budget" <<<"$out" \
  && pass "--check flags a fat task" || flunk "--check flags a fat task"
grep -qF -- "over the ~2 KB budget" <<<"$out" \
  && pass "--check flags fat group notes" || flunk "--check flags fat group notes"
grep -qF -- "over the ~40 KB budget" <<<"$out" \
  && pass "--check flags a fat tasks.md" || flunk "--check flags a fat tasks.md"
out="$("${packet[@]}" --check bare)"
grep -qF -- "over the ~" <<<"$out" \
  && flunk "--check leaves a thin change alone" || pass "--check leaves a thin change alone"

# Without node_modules a module ref says how to get the compiler.
bare="$tmp/bare-repo"
mkdir -p "$bare/openspec/changes/demo" "$bare/src" "$bare/.claude" && cd "$bare" && git init -q . && cp "$bindings" .claude/kit.toml
printf 'export const one = 1;\n' >src/one.ts
printf '## 1. G\n\n- [ ] 1.1 X. Reads: module src/one.ts. Tests: none (demo). Files: src/one.ts. Check: `true`\n' \
  >openspec/changes/demo/tasks.md
out="$("${packet[@]}" --check demo)"
expect "run \`bun install --frozen-lockfile\`"
# A file the project's tsconfig does not cover emits nothing.
ln -s "$modules" node_modules
printf '{ "compilerOptions": { "strict": true, "noEmit": true }, "include": ["lib"] }\n' >tsconfig.json
mkdir -p lib && printf 'export const two = 2;\n' >lib/two.ts
out="$("${packet[@]}" --check demo)"
expect "no declaration emitted for module src/one.ts"

echo
[ "$fails" -eq 0 ] && echo "packet.test: all passed" || echo "packet.test: $fails failed"
[ "$fails" -eq 0 ]
