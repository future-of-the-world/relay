"""Port of plugins/relay/tests/packet-stacks.test.sh: the parts of `kit packet` that depend on a project's stack binding:
Rust and Elixir module refs, smoke tests (a required test kind with a command), fenced code, and the `body` ref.
They need no compiler."""
import os
import shutil
import subprocess
import tempfile
import unittest
from typing import Tuple

from hook_helpers import ROOT, SoftCases

KIT = os.path.join(ROOT, "plugins", "relay", "bin", "kit")
DESIGN = "# Design\n\n## Decisions\n\n### D1. Spin\n\nD1-MARKER\n\n## Interfaces\n\nNone.\n"

SPEC = r'''## ADDED Requirements

### Requirement: Spinning
Widgets SHALL spin. SPIN-MARKER

#### Scenario: Fast spin
- **WHEN** asked
- **THEN** it spins

#### Scenario: Stale feed
- **WHEN** the feed is stale
- **THEN** it holds
'''

RUST_TOML = r'''[packet]
module = "rust"
source = ['^(crates/[^/]+/)?src/.+\.rs$']

[[packet.required_test]]
kind = "smoke"
files = ['^(?:crates/[^/]+/)?src/cli/(?!mod\.rs$)([a-z0-9_]+)\.rs$']
name_dash = true
command = "sight {name}"
missing = 'Tests: no smoke test for sight {name}: add smoke "sight {name} <args>"'
brief = '- smoke: `{title}` as the built binary in its own OS process'
'''

ELIXIR_TOML = r'''[packet]
module = "elixir"
max_source_files = 4
source = ['^lib/']

[[packet.required_test]]
kind = "smoke"
files = ['^lib/mix/tasks/(.+)\.ex$']
command = "mix {name}"
missing = 'Tests: no smoke test for mix {name}: add smoke "mix {name} <args>"'
brief = '- smoke: `{title}` as its own OS process through `System.cmd` (not in the test VM)'
'''

GEAR_RS = r'''//! A gear. MODULEDOC-MARKER

use std::fmt;

/// The gear's state.
#[derive(Debug, Clone)]
pub struct Gear {
    /// Number of teeth.
    pub teeth: u32,
    hidden: bool,
}

/// What a gear can do.
pub trait Spin {
    /// Spins once.
    fn spin(&mut self) -> Result<(), String>;
}

impl Gear {
    /// Spins the gear.
    pub fn spin(&mut self) -> Result<(), String> {
        let body_marker = "BODY_MARKER";
        let _ = body_marker;
        Ok(())
    }

    fn private_helper(&self) -> &'static str {
        "private_must_not_appear"
    }
}

fn free_private() -> u8 {
    7
}

impl fmt::Display for Gear {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "DISPLAY_BODY_MARKER")
    }
}

pub const MAX_TEETH: u32 = 64;
'''

RUST_TASKS = r'''# Tasks

## 1. Widgets

Wave 1 · depends on: none

- [ ] 1.1 Rust path. Reads: design D1; module src/widget/gear.rs. Tests: widgets "Fast spin". Files: src/widget/gear.rs. Check: `true`
- [ ] 1.2 Crate path. Reads: module my_core::walk. Tests: none (a walker). Files: crates/my-core/src/walk/mod.rs. Check: `true`
- [ ] 1.3 Subcommand without smoke. Reads: design D1. Tests: widgets "Fast spin". Files: src/cli/extract.rs. Check: `true`
- [ ] 1.4 Subcommand with smoke. Reads: design D1. Tests: widgets "Fast spin"; smoke "sight extract tests/fixtures/elixir". Files: src/cli/extract.rs. Check: `true`
- [ ] 1.5 Smoke names another command. Reads: design D1. Tests: smoke "sight extractor ." Files: src/cli/extract.rs. Check: `true`
- [ ] 1.6 Underscore file, dashed command. Reads: design D1. Tests: widgets "Fast spin"; smoke "sight check-refs ." Files: crates/my-core/src/cli/check_refs.rs, src/cli/mod.rs. Check: `true`
- [ ] 1.7 Bad refs. Reads: module crate::nope; module src/widget/none.rs. Tests: widgets "Fast spin". Files: src/a.rs. Check: `true`
- [ ] 1.8 Too many files. Reads: design D1. Tests: none (config only). Files: src/a.rs, src/b.rs, src/c.rs, src/d.rs, src/e.rs. Check: `true`
'''

GEAR_EX = r'''defmodule App.Widget.Gear do
  @moduledoc """
  A gear. MODULEDOC-MARKER
  """

  defstruct teeth: 0

  @type t :: %__MODULE__{teeth: non_neg_integer()}

  @doc "Spins the gear."
  @spec spin(t()) :: :ok
  def spin(_gear) do
    BODY_MARKER = :must_not_appear
    :ok
  end

  defp private_helper, do: :private_must_not_appear
end
'''

ELIXIR_TASKS = r'''# Tasks

## 1. Widgets

Wave 1 · depends on: none

- [ ] 1.1 Module. Reads: design D1; module App.Widget.Gear. Tests: widgets "Fast spin". Files: lib/app/widget/gear.ex. Check: `true`
- [ ] 1.2 Support module. Reads: module App.Test.WidgetFixture. Tests: none (fixture). Files: test/support/fixture_file.ex. Check: `true`
- [ ] 1.3 Mix task without smoke. Reads: design D1. Tests: widgets "Fast spin". Files: lib/mix/tasks/app.widget.spin.ex. Check: `true`
- [ ] 1.4 Mix task with smoke. Reads: design D1. Tests: widgets "Fast spin"; smoke "mix app.widget.spin --fast". Files: lib/mix/tasks/app.widget.spin.ex. Check: `true`
- [ ] 1.5 Smoke names another task. Reads: design D1. Tests: smoke "mix app.widget.spinner". Files: lib/mix/tasks/app.widget.spin.ex. Check: `true`
- [ ] 1.6 Unknown module. Reads: module App.Nope. Tests: widgets "Fast spin". Files: lib/a.ex. Check: `true`
'''

FENCED_DESIGN = r'''# Design

## Interfaces

Shapes. IFACE2-MARKER

### D3. Fenced backticks

BEFORE3-MARKER

```sh
# a shell comment
## a second-level comment
echo hi
```

AFTER3-MARKER

### D4. Fenced tildes

BEFORE4-MARKER

~~~elixir
# an Elixir comment
~~~

AFTER4-MARKER

### D5. Unclosed

BEFORE5-MARKER

```
# never closed
AFTER5-MARKER
'''

FENCED_SPEC = r'''## ADDED Requirements

### Requirement: Fenced spin
Widgets SHALL spin. FSPEC-MARKER

#### Scenario: Fenced example
- **WHEN** asked
```sh
# comment in the scenario
## and a second-level one
```
- **THEN** FTHEN-MARKER

### Requirement: Next
Widgets SHALL stop. FNEXT-MARKER

#### Scenario: Other
- **WHEN** x
- **THEN** y

### Requirement: Fenced body
Widgets SHALL spin:
```
#### Scenario: Inside a fence
FENCEBODY-MARKER
```
Tail of the body. FENCETAIL-MARKER

#### Scenario: Real one
- **WHEN** REALSCEN-MARKER
- **THEN** y
'''

FENCED_TASKS = r'''# Tasks

## 1. Fenced

Wave 1 · depends on: none

```
## 9. Not a group
- [ ] 9.9 Not a task. Reads: nothing
```

- [ ] 1.1 Fenced reads. Reads: design D3; design D4; design D5; widgets "Fenced spin". Tests: widgets "Fenced example". Files: lib/a.ex. Check: `true`
- [ ] 1.2 Body only. Reads: widgets "Fenced body" body. Tests: widgets "Real one". Files: lib/a.ex. Check: `true`
'''


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


class Packet(SoftCases):
    def setUp(self) -> None:
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def project(self, name: str, toml: str) -> str:
        root = os.path.join(self.tmp, name)
        write(os.path.join(root, ".claude", "kit.toml"), toml)
        subprocess.run(["git", "init", "-q", "."], cwd=root, check=True)
        return root

    def packet(self, root: str, *args: str) -> Tuple[int, str]:
        done = subprocess.run([KIT, "packet"] + list(args), cwd=root, capture_output=True, text=True, encoding="utf-8")
        return done.returncode, done.stdout + done.stderr

    def change(self, root: str, name: str = "demo", spec: str = SPEC, tasks: str = "", design: str = DESIGN) -> None:
        base = os.path.join(root, "openspec", "changes", name)
        write(os.path.join(base, "specs", "widgets", "spec.md"), spec)
        write(os.path.join(base, "design.md"), design)
        write(os.path.join(base, "tasks.md"), tasks)

    def test_rust(self) -> None:
        r = self.project("rust", RUST_TOML)
        write(os.path.join(r, "src", "widget", "gear.rs"), GEAR_RS)
        write(os.path.join(r, "crates", "my-core", "src", "walk", "mod.rs"),
              "//! Walking a repository. WALK-MARKER\npub fn walk(root: &str) -> Vec<String> {\n    vec![]\n}\n")
        self.change(r, tasks=RUST_TASKS)
        b = self.packet(r, "demo", "1.1")[1]
        for m in ("MODULEDOC-MARKER", "pub struct Gear {", "pub teeth: u32,", "fn spin(&mut self) -> Result<(), String>;",
                  "pub fn spin(&mut self) -> Result<(), String>", "pub const MAX_TEETH: u32 = 64;", "(src/widget/gear.rs)"):
            self.assertIn(m, b)
        for m in ("BODY_MARKER", "private_must_not_appear", "private_helper", "free_private", "DISPLAY_BODY_MARKER"):
            self.assertNotIn(m, b)
        # a crate path my_core::walk resolves to crates/my-core/src/walk/mod.rs
        self.assertIn("WALK-MARKER", self.packet(r, "demo", "1.2")[1])
        self.assertIn("- smoke: `sight extract tests/fixtures/elixir` as the built binary in its own OS process", self.packet(r, "demo", "1.4")[1])
        out = self.packet(r, "--check", "demo")[1]
        self.assertIn("task 1.3: Tests: no smoke test for sight extract", out)
        self.assertNotIn("task 1.4:", out)
        self.assertIn("task 1.5: Tests: no smoke test for sight extract", out)  # a smoke test of another command does not count
        self.assertNotIn("task 1.6:", out)  # check_refs.rs is covered by a check-refs command; mod.rs is no command
        self.assertIn("no file for module crate::nope", out)
        self.assertIn("no file for module src/widget/none.rs", out)
        self.assertIn("task 1.8: lists 5 source files", out)

    def test_elixir(self) -> None:
        x = self.project("elixir", ELIXIR_TOML)
        write(os.path.join(x, "lib", "app", "widget", "gear.ex"), GEAR_EX)
        write(os.path.join(x, "test", "support", "fixture_file.ex"), "defmodule App.Test.WidgetFixture do\n  @spec build() :: map()\n  def build, do: %{}\nend\n")
        self.change(x, tasks=ELIXIR_TASKS)
        b = self.packet(x, "demo", "1.1")[1]
        for m in ("MODULEDOC-MARKER", "@spec spin(t()) :: :ok", "defstruct teeth: 0", "(lib/app/widget/gear.ex)"):
            self.assertIn(m, b)
        for m in ("BODY_MARKER", "private_must_not_appear", "private_helper"):
            self.assertNotIn(m, b)
        self.assertIn("@spec build() :: map()", self.packet(x, "demo", "1.2")[1])  # a module in test/support, by its defmodule line
        b = self.packet(x, "demo", "1.4")[1]
        self.assertIn("- smoke: `mix app.widget.spin --fast` as its own OS process through `System.cmd`", b)
        self.assertIn('widgets: "Spinning" / "Fast spin"', b)
        out = self.packet(x, "--check", "demo")[1]
        self.assertIn("task 1.3: Tests: no smoke test for mix app.widget.spin", out)
        self.assertNotIn("task 1.4:", out)
        self.assertIn("task 1.5: Tests: no smoke test for mix app.widget.spin", out)
        self.assertIn("no file for module App.Nope", out)

    def test_fences_and_body(self) -> None:
        f = self.project("fenced", '[project]\nname = "fenced"\n')
        self.change(f, "fenced", spec=FENCED_SPEC, tasks=FENCED_TASKS, design=FENCED_DESIGN)
        b = self.packet(f, "fenced", "1.1")[1]
        for m in ("BEFORE3-MARKER", "AFTER3-MARKER", "BEFORE4-MARKER", "AFTER4-MARKER", "BEFORE5-MARKER", "AFTER5-MARKER", "FSPEC-MARKER", "FTHEN-MARKER"):
            self.assertIn(m, b)
        self.assertNotIn("FNEXT-MARKER", b)
        rc, out = self.packet(f, "--check", "fenced")
        self.assertIn("packet: 2 open task(s), 0 problem(s)", out)  # not the fenced "task"
        self.assertEqual(rc, 0, out)
        full = self.packet(f, "fenced", "1.2")[1]
        sec = full[full.index("## What the task reads"):]
        self.assertIn("FENCETAIL-MARKER", sec)  # the text after a fenced pseudo-scenario is kept
        self.assertIn("FENCEBODY-MARKER", sec)
        self.assertNotIn("REALSCEN-MARKER", sec)

    def test_no_bindings(self) -> None:
        n = self.project("plain", '[project]\nname = "plain"\n')
        self.change(n, tasks='## 1. G\n\n- [ ] 1.1 X. Reads: module src/a.ts. Tests: widgets "Fast spin". Files: src/a.ts, src/b.ts, src/c.ts, '
                             'src/d.ts, src/e.ts, src/ui/Panel.tsx. Check: `true`\n')
        out = self.packet(n, "--check", "demo")[1]
        self.assertIn("module refs are not set up", out)
        self.assertNotIn("lists ", out)  # size is not checked
        self.assertNotIn("e2e", out)  # no required test kinds


if __name__ == "__main__":
    unittest.main()
