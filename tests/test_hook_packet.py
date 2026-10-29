"""Port of plugins/relay/tests/packet.test.sh: `kit packet` over a small synthetic change in a temporary repo, with
Kartoteka's real bindings (tests/profiles/kartoteka.toml).

`module` refs of the typescript kind run the TypeScript compiler, so the temporary repo links a node_modules with it: the
tests folder's ts-deps/ (package.json and bun.lock pin TypeScript); the first run installs it with `bun install
--frozen-lockfile`. $KIT_TEST_NODE_MODULES overrides it. With no compiler to be had this suite FAILS: a skipped test would
pass a gate that checked nothing."""
import os
import shutil
import subprocess
import tempfile
import unittest
from typing import Tuple

from hook_helpers import ROOT, SoftCases

CORE = os.path.join(ROOT, "plugins", "relay")
KIT = os.path.join(CORE, "bin", "kit")
BINDINGS = os.path.join(CORE, "tests", "profiles", "kartoteka.toml")
TS_DEPS = os.path.join(CORE, "tests", "ts-deps")
CHANGE = "openspec/changes/demo"

TSCONFIG = r'''{
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
'''

DESIGN = r'''# Design

## Decisions

### D1. Widgets spin

Widgets spin clockwise. D1-MARKER

### D2. Unrelated

D2-MARKER must not appear.

## Interfaces

spin returns the new angle. IFACE-MARKER
'''

SPEC = r'''## ADDED Requirements

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
'''

GEAR_TS = r'''/** The gear's state. GEAR-DOC-MARKER */
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
'''

STUB_TS = r'''/** Not written yet. STUB-DOC-MARKER */
export function later(count: number): string {
  return count;
}
'''

PANEL_TSX = r'''export interface PanelProps {
  readonly title: string;
}

/** Shows a title. PANEL-DOC-MARKER */
export function Panel({ title }: PanelProps) {
  return <h1 class="PANEL_BODY_MARKER">{title}</h1>;
}
'''

GUIDE = r'''# Guide

## Setup

GUIDE-SETUP-MARKER

## Other

GUIDE-OTHER-MARKER
'''

TASKS = r'''# Tasks

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
'''

SKETCH = "".join("LINE-%d-MARKER\n" % i for i in range(1, 7))


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


class Packet(SoftCases):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = os.environ.get("KIT_TEST_NODE_MODULES") or os.path.join(TS_DEPS, "node_modules")
        tsc = os.path.join(cls.modules, ".bin", "tsc")
        if not os.access(tsc, os.X_OK) and not os.environ.get("KIT_TEST_NODE_MODULES"):
            subprocess.run(["bun", "install", "--frozen-lockfile"], cwd=TS_DEPS, capture_output=True)
        if not os.access(tsc, os.X_OK):
            raise AssertionError("no TypeScript compiler at %s. Install it: cd %s && bun install --frozen-lockfile (needs bun and, on a first run, "
                                 "network or bun's package cache), or set KIT_TEST_NODE_MODULES=<dir>/node_modules." % (tsc, TS_DEPS))
        cls.tmp = os.path.realpath(tempfile.mkdtemp())
        cls.root = cls.tmp
        subprocess.run(["git", "init", "-q", "."], cwd=cls.root, check=True)
        os.symlink(cls.modules, os.path.join(cls.root, "node_modules"))
        write(os.path.join(cls.root, ".claude", "kit.toml"), open(BINDINGS).read())
        for rel, text in (("tsconfig.json", TSCONFIG), (CHANGE + "/design.md", DESIGN), (CHANGE + "/specs/widgets/spec.md", SPEC),
                          ("src/widget/gear.ts", GEAR_TS), ("src/widget/stub.ts", STUB_TS), ("src/ui/Panel.tsx", PANEL_TSX),
                          ("src-tauri/src/lib.rs", "fn main() {}\n"), ("src/widget/gear.css", ".gear { color: red; }\n"),
                          ("docs/guide.md", GUIDE), ("docs/sketch.html", SKETCH), (CHANGE + "/tasks.md", TASKS)):
            write(os.path.join(cls.root, rel), text)
        os.makedirs(os.path.join(cls.root, "src", "ui", "parts"), exist_ok=True)
        cls.check_rc, cls.check_out = cls.packet("--check", "demo")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def packet(cls, *args: str, root: str = "") -> Tuple[int, str]:
        done = subprocess.run([KIT, "packet"] + list(args), cwd=root or cls.root, capture_output=True, text=True, encoding="utf-8")
        return done.returncode, done.stdout + done.stderr

    def test_brief_for_one_task(self) -> None:
        rc, brief = self.packet("demo", "1.2")
        self.assertEqual(rc, 0, brief)
        for m in ("NOTES-MARKER", "GROUP-MARKER", "1.2 Build spinning", "D1-MARKER", "IFACE-MARKER", "SPIN-MARKER", "GUIDE-SETUP-MARKER",
                  "GEAR-DOC-MARKER", "SPIN-DOC-MARKER", "export declare function spin(gear: Gear, angle: number): number;",
                  "readonly teeth: number;", "size(): number;", "export declare const MAX_TEETH = 64;",
                  'widgets: "Spinning" / "Corrupt data"', "the stored angle is garbage", "(brief: "):
            self.assertIn(m, brief)
        for m in ("D2-MARKER", "STOP-MARKER", "BODY_MARKER", "private_must_not_appear", "secretCount", "secretHelper", "PRIVATE-DOC-MARKER",
                  "freePrivate", "GUIDE-OTHER-MARKER", "export {};"):
            self.assertNotIn(m, brief)

    def test_tests_section_prints_scenario_text_without_reads(self) -> None:
        out = self.packet("demo", "1.6")[1]
        section = out[out.index("## Tests to write"):out.index("## What the task reads")]
        self.assertIn("- **THEN** it stops", section)
        self.assertNotIn("it starts from zero", section)  # the scenario text stays with its own requirement

    def test_e2e_waiver_none_stub_and_line_ranges(self) -> None:
        e2e = self.packet("demo", "1.12")[1]
        self.assertIn('- e2e: "the panel shows its title" in e2e/, black-box: drive the built app through what is on the screen', e2e)
        self.assertIn('- e2e: "the panel fits a phone" in e2e/', e2e)
        self.assertIn("PANEL-DOC-MARKER", e2e)
        self.assertIn("export declare function Panel(", e2e)
        self.assertNotIn("PANEL_BODY_MARKER", e2e)  # a .tsx module gives its contract
        out = self.packet("demo", "1.13")[1]
        waived = out[out.index("## Tests to write"):out.index("## What the task reads")]
        self.assertIn("- none (copy only; nothing to assert)", waived)
        self.assertIn('- e2e: none (covered by "the panel shows its title")', waived)
        stub = self.packet("demo", "1.17")[1]  # a stub that does not type-check still has a contract
        self.assertIn("STUB-DOC-MARKER", stub)
        self.assertIn("export declare function later(count: number): string;", stub)
        rc, ranged = self.packet("demo", "1.19")
        self.assertEqual(rc, 0, ranged)
        for m in ("### docs/sketch.html, lines 2 to 4", "LINE-2-MARKER", "LINE-3-MARKER", "LINE-4-MARKER", "### docs/sketch.html, lines 6 to 6", "LINE-6-MARKER"):
            self.assertIn(m, ranged)
        for m in ("LINE-1-MARKER", "LINE-5-MARKER"):
            self.assertNotIn(m, ranged)

    def test_exit_codes(self) -> None:
        self.assertEqual(self.packet("demo", "1.4")[0], 1)  # bad refs: no brief
        self.assertEqual(self.packet("demo", "9.9")[0], 2)
        self.assertEqual(self.packet()[0], 2)
        self.assertEqual(self.packet("--check", "nochange")[0], 2)

    def test_check_reports(self) -> None:
        self.assertEqual(self.check_rc, 1)
        out = self.check_out
        for m in ("task 1.3: Reads: missing", "task 1.3: Tests: missing", 'no heading "D9"', "unknown ref 'nosuch \"Thing\"'",
                  "no file for module src/widget/nope.ts",
                  'module src/widget/gear.css: a module ref names a .ts or .tsx file; use `file src/widget/gear.css`', "no file docs/none.md",
                  'has no scenario "No such scenario"', 'scenario "Corrupt data" is in 2 requirements', "task 1.7: lists 5 source files",
                  'task 1.10: Tests: src/ui/Panel.tsx changes what the user sees: add e2e "<test title>"',
                  "task 1.11: Tests: src/ui/parts/Dial.tsx changes what the user sees",
                  "task 1.14: Tests: e2e/panel.spec.ts changes what the user sees",
                  "task 1.16: bad Tests entry 'e2e the panel': use e2e \"<test title>\" or e2e none (<reason>)",
                  "task 1.18: Tests: names scenarios and says none",
                  "task 1.20: Reads: no lines 5-9 in docs/sketch.html: it has 6 lines",
                  "task 1.20: Reads: bad line range docs/sketch.html:4-2", "task 1.20: Reads: bad line range docs/sketch.html:0-2",
                  "task 1.20: Reads: no file docs/none.html", "a line range and a heading don't go together", "packet: 19 open task(s)"):
            self.assertIn(m, out)
        for ok in ("1.1", "1.2", "1.6", "1.8", "1.9", "1.12", "1.13", "1.15", "1.17", "1.19"):
            self.assertNotIn("task %s:" % ok, out)
        self.assertNotIn('no "Interfaces" section', out)

    def test_bare_change_and_group_briefs(self) -> None:
        bare = os.path.join(self.root, "openspec", "changes", "bare")
        write(os.path.join(bare, "tasks.md"), '## 1. G\n\nWave 1 · depends on: none\n\n- [ ] 1.1 X. Reads: file docs/guide.md. Tests: none (docs). Files: docs/guide.md. Check: `true`\n')
        write(os.path.join(bare, "design.md"), "# Design\n")
        self.assertNotIn('no "Interfaces" section', self.packet("--check", "bare")[1])  # a bare design.md passes
        write(os.path.join(bare, "design.md"), "# Design\n\n## Interfaces\n\nNone.\n")
        rc, out = self.packet("--check", "bare")
        self.assertEqual(rc, 0, out)
        rc, refused = self.packet("demo", "1")
        self.assertEqual(rc, 1)  # a group with a bad task gets no brief
        self.assertIn("task 1.3: Reads: missing", refused)
        with open(os.path.join(bare, "tasks.md"), "a") as handle:
            handle.write("- [ ] 1.2 Second small task. Reads: file docs/guide.md. Tests: none (docs). Files: docs/x.md. Check: `true`\n")
        rc, brief = self.packet("bare", "1")
        self.assertEqual(rc, 0, brief)
        for m in ("## Task 1.1", "## Task 1.2", "in order, in one"):
            self.assertIn(m, brief)
        self.assertEqual(brief.count("GUIDE-SETUP-MARKER"), 1)  # a shared Reads ref once

    def test_artifact_budgets(self) -> None:
        fat = os.path.join(self.root, "openspec", "changes", "fat")
        write(os.path.join(fat, "design.md"), "# Design\n\n## Interfaces\n\nNone.\n## D1. Filler\n\n" + "filler " * 9000 + "\n")
        write(os.path.join(fat, "tasks.md"),
              '# Tasks\n\n## 1. G\n\nWave 1 · depends on: none\n\n- [ ] 1.1 Fat task. Reads: file docs/guide.md. Tests: none (fat). Files: docs/x.md. Check: `true` '
              + "prose " * 400 + "\n\n## 2. Wide notes\n\nWave 1 · depends on: none\n\n" + "notes " * 500
              + "\n\n- [ ] 2.1 Thin task. Reads: file docs/guide.md. Tests: none (fat). Files: docs/y.md. Check: `true`\n\n" + "task " * 9000 + "\n")
        rc, out = self.packet("--check", "fat")
        self.assertEqual(rc, 1)
        for m in ("over the ~60 KB budget", "over the ~1 KB budget", "over the ~2 KB budget", "over the ~40 KB budget"):
            self.assertIn(m, out)
        self.assertNotIn("over the ~", self.thin()[1])  # a thin change is left alone

    def thin(self) -> Tuple[int, str]:
        thin = os.path.join(self.root, "openspec", "changes", "thin")
        write(os.path.join(thin, "tasks.md"), '## 1. G\n\nWave 1 · depends on: none\n\n- [ ] 1.1 X. Reads: file docs/guide.md. Tests: none (docs). Files: docs/guide.md. Check: `true`\n')
        write(os.path.join(thin, "design.md"), "# Design\n\n## Interfaces\n\nNone.\n")
        return self.packet("--check", "thin")

    def test_module_ref_without_node_modules_and_uncovered_file(self) -> None:
        bare = os.path.join(self.tmp, "bare-repo")
        write(os.path.join(bare, ".claude", "kit.toml"), open(BINDINGS).read())
        subprocess.run(["git", "init", "-q", "."], cwd=bare, check=True)
        write(os.path.join(bare, "src", "one.ts"), "export const one = 1;\n")
        write(os.path.join(bare, "openspec", "changes", "demo", "tasks.md"),
              "## 1. G\n\n- [ ] 1.1 X. Reads: module src/one.ts. Tests: none (demo). Files: src/one.ts. Check: `true`\n")
        self.assertIn("run `bun install --frozen-lockfile`", self.packet("--check", "demo", root=bare)[1])
        # a file the project's tsconfig does not cover emits nothing
        os.symlink(self.modules, os.path.join(bare, "node_modules"))
        write(os.path.join(bare, "tsconfig.json"), '{ "compilerOptions": { "strict": true, "noEmit": true }, "include": ["lib"] }\n')
        write(os.path.join(bare, "lib", "two.ts"), "export const two = 2;\n")
        self.assertIn("no declaration emitted for module src/one.ts", self.packet("--check", "demo", root=bare)[1])


if __name__ == "__main__":
    unittest.main()
