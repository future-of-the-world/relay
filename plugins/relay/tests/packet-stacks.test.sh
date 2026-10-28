#!/usr/bin/env bash
# Tests for the parts of `kit packet` that depend on a project's stack
# binding: Rust and Elixir module refs, smoke tests (a required test kind with
# a command), fenced code, and the `body` ref. They need no compiler.
#   plugins/relay/tests/packet-stacks.test.sh
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd -P)"
kit="$here/../bin/kit"
packet=("$kit" packet)
tmp="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT
fails=0
pass() { echo "ok   $1"; }
flunk() { echo "FAIL $1"; fails=$((fails + 1)); }
has() { grep -qF -- "$2" <<<"$1" && pass "$3" || flunk "$3"; }
hasnt() { grep -qF -- "$2" <<<"$1" && flunk "$3" || pass "$3"; }

spec() { # <change dir>: the shared widgets spec
  mkdir -p "$1/specs/widgets"
  cat >"$1/specs/widgets/spec.md" <<'EOS'
## ADDED Requirements

### Requirement: Spinning
Widgets SHALL spin. SPIN-MARKER

#### Scenario: Fast spin
- **WHEN** asked
- **THEN** it spins

#### Scenario: Stale feed
- **WHEN** the feed is stale
- **THEN** it holds
EOS
  printf '# Design\n\n## Decisions\n\n### D1. Spin\n\nD1-MARKER\n\n## Interfaces\n\nNone.\n' >"$1/design.md"
}

# ---------------------------------------------------------------- Rust
r="$tmp/rust"; mkdir -p "$r/.claude" "$r/src/widget" "$r/src/cli" "$r/crates/my-core/src/walk" && cd "$r" && git init -q .
cat >.claude/kit.toml <<'EOS'
[packet]
module = "rust"
source = ['^(crates/[^/]+/)?src/.+\.rs$']

[[packet.required_test]]
kind = "smoke"
files = ['^(?:crates/[^/]+/)?src/cli/(?!mod\.rs$)([a-z0-9_]+)\.rs$']
name_dash = true
command = "sight {name}"
missing = 'Tests: no smoke test for sight {name}: add smoke "sight {name} <args>"'
brief = '- smoke: `{title}` as the built binary in its own OS process'
EOS
c=openspec/changes/demo; spec "$c"
cat >src/widget/gear.rs <<'EOS'
//! A gear. MODULEDOC-MARKER

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
EOS
printf '//! Walking a repository. WALK-MARKER\npub fn walk(root: &str) -> Vec<String> {\n    vec![]\n}\n' >crates/my-core/src/walk/mod.rs
cat >"$c/tasks.md" <<'EOS'
# Tasks

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
EOS
b="$("${packet[@]}" demo 1.1 2>&1)"
for m in MODULEDOC-MARKER "pub struct Gear {" "pub teeth: u32," "fn spin(&mut self) -> Result<(), String>;" \
  "pub fn spin(&mut self) -> Result<(), String>" "pub const MAX_TEETH: u32 = 64;" "(src/widget/gear.rs)"; do
  has "$b" "$m" "rust: brief has $m"
done
for m in BODY_MARKER private_must_not_appear private_helper free_private DISPLAY_BODY_MARKER; do
  hasnt "$b" "$m" "rust: brief leaves out $m"
done
has "$("${packet[@]}" demo 1.2 2>&1)" "WALK-MARKER" "rust: a crate path my_core::walk resolves to crates/my-core/src/walk/mod.rs"
b="$("${packet[@]}" demo 1.4 2>&1)"
has "$b" '- smoke: `sight extract tests/fixtures/elixir` as the built binary in its own OS process' "smoke: brief lists the smoke test"
out="$("${packet[@]}" --check demo)"
has "$out" "task 1.3: Tests: no smoke test for sight extract" "smoke: a subcommand without a smoke test"
hasnt "$out" "task 1.4:" "smoke: a subcommand with its smoke test"
has "$out" "task 1.5: Tests: no smoke test for sight extract" "smoke: a smoke test of another command does not count"
hasnt "$out" "task 1.6:" "smoke: check_refs.rs is covered by a check-refs command; mod.rs is no command"
has "$out" "no file for module crate::nope" "rust: an unknown crate path"
has "$out" "no file for module src/widget/none.rs" "rust: an unknown file"
has "$out" "task 1.8: lists 5 source files" "source files counted by the binding"

# ---------------------------------------------------------------- Elixir
x="$tmp/elixir"; mkdir -p "$x/.claude" "$x/lib/app/widget" "$x/lib/mix/tasks" "$x/test/support" && cd "$x" && git init -q .
cat >.claude/kit.toml <<'EOS'
[packet]
module = "elixir"
max_source_files = 4
source = ['^lib/']

[[packet.required_test]]
kind = "smoke"
files = ['^lib/mix/tasks/(.+)\.ex$']
command = "mix {name}"
missing = 'Tests: no smoke test for mix {name}: add smoke "mix {name} <args>"'
brief = '- smoke: `{title}` as its own OS process through `System.cmd` (not in the test VM)'
EOS
spec "$c"
cat >lib/app/widget/gear.ex <<'EOS'
defmodule App.Widget.Gear do
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
EOS
printf 'defmodule App.Test.WidgetFixture do\n  @spec build() :: map()\n  def build, do: %%{}\nend\n' >test/support/fixture_file.ex
cat >"$c/tasks.md" <<'EOS'
# Tasks

## 1. Widgets

Wave 1 · depends on: none

- [ ] 1.1 Module. Reads: design D1; module App.Widget.Gear. Tests: widgets "Fast spin". Files: lib/app/widget/gear.ex. Check: `true`
- [ ] 1.2 Support module. Reads: module App.Test.WidgetFixture. Tests: none (fixture). Files: test/support/fixture_file.ex. Check: `true`
- [ ] 1.3 Mix task without smoke. Reads: design D1. Tests: widgets "Fast spin". Files: lib/mix/tasks/app.widget.spin.ex. Check: `true`
- [ ] 1.4 Mix task with smoke. Reads: design D1. Tests: widgets "Fast spin"; smoke "mix app.widget.spin --fast". Files: lib/mix/tasks/app.widget.spin.ex. Check: `true`
- [ ] 1.5 Smoke names another task. Reads: design D1. Tests: smoke "mix app.widget.spinner". Files: lib/mix/tasks/app.widget.spin.ex. Check: `true`
- [ ] 1.6 Unknown module. Reads: module App.Nope. Tests: widgets "Fast spin". Files: lib/a.ex. Check: `true`
EOS
b="$("${packet[@]}" demo 1.1 2>&1)"
for m in MODULEDOC-MARKER "@spec spin(t()) :: :ok" "defstruct teeth: 0" "(lib/app/widget/gear.ex)"; do
  has "$b" "$m" "elixir: brief has $m"
done
for m in BODY_MARKER private_must_not_appear private_helper; do
  hasnt "$b" "$m" "elixir: brief leaves out $m"
done
has "$("${packet[@]}" demo 1.2 2>&1)" "@spec build() :: map()" "elixir: a module in test/support found by its defmodule line"
b="$("${packet[@]}" demo 1.4 2>&1)"
has "$b" '- smoke: `mix app.widget.spin --fast` as its own OS process through `System.cmd`' "elixir: brief lists the smoke test"
has "$b" 'widgets: "Spinning" / "Fast spin"' "elixir: the scenario stays next to the smoke test"
out="$("${packet[@]}" --check demo)"
has "$out" "task 1.3: Tests: no smoke test for mix app.widget.spin" "elixir: a mix task without a smoke test"
hasnt "$out" "task 1.4:" "elixir: a mix task with its smoke test"
has "$out" "task 1.5: Tests: no smoke test for mix app.widget.spin" "elixir: a smoke test of another task does not count"
has "$out" "no file for module App.Nope" "elixir: an unknown module"

# ---------------------------------------------------------------- fences and body (no stack binding)
f="$tmp/fenced"; mkdir -p "$f/docs" "$f/.claude" && printf "[project]\nname = \"fenced\"\n" >"$f/.claude/kit.toml" && cd "$f" && git init -q .
c=openspec/changes/fenced; spec "$c"
cat >"$c/design.md" <<'EOS'
# Design

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
EOS
cat >"$c/specs/widgets/spec.md" <<'EOS'
## ADDED Requirements

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
EOS
cat >"$c/tasks.md" <<'EOS'
# Tasks

## 1. Fenced

Wave 1 · depends on: none

```
## 9. Not a group
- [ ] 9.9 Not a task. Reads: nothing
```

- [ ] 1.1 Fenced reads. Reads: design D3; design D4; design D5; widgets "Fenced spin". Tests: widgets "Fenced example". Files: lib/a.ex. Check: `true`
- [ ] 1.2 Body only. Reads: widgets "Fenced body" body. Tests: widgets "Real one". Files: lib/a.ex. Check: `true`
EOS
b="$("${packet[@]}" fenced 1.1 2>&1)"
for m in BEFORE3-MARKER AFTER3-MARKER BEFORE4-MARKER AFTER4-MARKER BEFORE5-MARKER AFTER5-MARKER FSPEC-MARKER FTHEN-MARKER; do
  has "$b" "$m" "fenced: brief has $m"
done
hasnt "$b" FNEXT-MARKER "fenced: brief leaves out the next requirement"
out="$("${packet[@]}" --check fenced)"; status=$?
has "$out" "packet: 2 open task(s), 0 problem(s)" "fenced: --check counts two tasks, not the fenced one"
[ "$status" -eq 0 ] && pass "fenced: --check passes" || flunk "fenced: --check passes: $out"
sec="$("${packet[@]}" fenced 1.2 2>&1 | sed -n '/^## What the task reads/,$p')"
has "$sec" "FENCETAIL-MARKER" "body: the text after a fenced pseudo-scenario is kept"
has "$sec" "FENCEBODY-MARKER" "body: the fence is part of the body"
hasnt "$sec" "REALSCEN-MARKER" "body: no real scenario in the body"

# ---------------------------------------------------------------- no bindings
n="$tmp/plain"; mkdir -p "$n/.claude" && printf "[project]\nname = \"plain\"\n" >"$n/.claude/kit.toml" && cd "$n" && git init -q .
c=openspec/changes/demo; spec "$c"
printf '## 1. G\n\n- [ ] 1.1 X. Reads: module src/a.ts. Tests: widgets "Fast spin". Files: src/a.ts, src/b.ts, src/c.ts, src/d.ts, src/e.ts, src/ui/Panel.tsx. Check: `true`\n' >"$c/tasks.md"
out="$("${packet[@]}" --check demo)"
has "$out" "module refs are not set up" "no bindings: a module ref says how to set it up"
hasnt "$out" "lists " "no bindings: size is not checked"
hasnt "$out" "e2e" "no bindings: no required test kinds"

echo
[ "$fails" -eq 0 ] && echo "packet-stacks.test: all passed" || echo "packet-stacks.test: $fails failed"
[ "$fails" -eq 0 ]
