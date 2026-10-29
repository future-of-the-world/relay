# Variants: the scripts and hooks in `core`

Read 2026-10-19: each project's `bin/packet`, `bin/spec-check` and
`.claude/hooks/guard-main.sh`, compared line by line with Kartoteka's copy
(`diff | grep -c '^[<>]'`). Shared files: `plugins/relay/lib/kit_packet.py`
(`kit packet`), `plugins/relay/lib/kit_spec_check.py` (`kit spec-check`),
`plugins/relay/hooks/guard-main.sh`. Everything a project did differently is
now a binding in its `.claude/kit.toml` (keys: `plugins/relay/README.md`).
`migration/kartoteka/kit.toml` is the worked, tested example; the snippets
below are what the other projects add when they migrate. Kartoteka's own
copy is the base because Clean's is the same.

## `kit packet` (task brief and `--check`)

| Copy | Lines unlike Kartoteka | What it has that Kartoteka lacks |
|---|---|---|
| Clean | 2 (an example filename) | nothing |
| Mind | 80 | screens-only e2e rule, "player" wording; no `file <path>:<from>-<to>` |
| ALIX | 401 | Elixir `module <App.Module>`, mix-task smoke test |
| Sight | 507 | Rust `module <path.rs\|crate::a::b>`, CLI smoke test; no size budgets |

Taken for the shared file:

- Core of the brief, fields `Reads/Tests/Size/Files/Check`, ref kinds,
  `file <path>:<from>-<to>` line ranges, the size budgets (design 60 KB,
  tasks 40 KB, task 1 KB, group 2 KB): Kartoteka = Clean (Mind and Sight
  predate the ranges; Sight has no budgets; ALIX has the budgets).
- `module <ref>` for TypeScript (compiler declarations): Kartoteka, Clean, Mind.
  Rust: Sight. Elixir: ALIX. Chosen by `packet.module`.
- Smoke tests for a command-line tool or a task: Sight and ALIX, as the
  general `[[packet.required_test]]` with `command` (tested by
  `tests/test_hook_packet_stacks.py`).
- The e2e rule (a component or end-to-end spec must name an e2e test or
  `e2e none (<reason>)`): Kartoteka and Clean, as a `required_test` kind.

What each project puts in its `kit.toml` to keep its old behaviour:

- **Kartoteka, Clean**: `migration/kartoteka/kit.toml` as it stands.
- **Mind**: the same `[packet]` with its own e2e kind: `files =
  ['^src/ui/screens/[^/]+\.tsx$', '^e2e/.+\.spec\.ts$']`, `files_exclude =
  ['\.test\.tsx$']`, and `missing` / `brief` texts that say "the player sees"
  and "read the problem off the screen, work out the answer independently, and
  play it" (copy them from `~/mind/bin/packet`).
- **ALIX**: `module = "elixir"`, `source = ['^lib/']`, and
  `[[packet.required_test]] kind = "smoke"`, `files =
  ['^lib/mix/tasks/(.+)\.ex$']`, `command = "mix {name}"` (the exact block in
  `tests/test_hook_packet_stacks.py`); `module_dirs = ["lib", "test/support"]`.
- **Sight**: `module = "rust"`, `source = ['^(crates/[^/]+/)?src/.+\.rs$']`,
  and the smoke kind with `files =
  ['^(?:crates/[^/]+/)?src/cli/(?!mod\.rs$)([a-z0-9_]+)\.rs$']`,
  `name_dash = true`, `command = "sight {name}"` (same test file).
- Differences that are gone on purpose: Sight now has the size budgets; Mind,
  Sight and ALIX gain line ranges.

## `kit spec-check` (failure scenarios of a requirement)

Clean's copy is identical to Kartoteka's; the others differ only in their
groups of words, which are now `[[spec_check.group]]` bindings. Sight and
ALIX had no fence masking, no "Native shell" group and one fixed set of
cases; the shared file has fence masking (Kartoteka) and any number of groups.

- **Kartoteka, Clean**: stored data (without "load": in a media app it means
  media arriving) and the native shell (Plain browser) groups, in
  `migration/kartoteka/kit.toml`; tested by
  `tests/test_hook_spec_check.py` (ported from
  `~/kartoteka/bin/spec-check.test.sh`).
- **Mind**: the stored-data group with two changes: trigger adds
  `load(?:s|ed|ing)?` and `profile version` (all of its stored data goes
  through `restoreProfile`, and "load" there means reading the profile), and
  the "Older data" case adds `old(er)? profile` and
  `skill (that )?(was |is )?added (later|after)`. Native-shell group as
  Kartoteka.
- **ALIX**: one group, name `orders, funds and keys`, trigger
  `\b(orders?|fill(s|ed)?|balances?|funds?|equity|positions?|stop[- ]loss|protective stops?|sell(s|ing)?|buy(s|ing)?|entr(y|ies)|exits?|risk|kill switch|api keys?|secrets?|credentials?|withdraw\w*|wallet)\b`;
  cases `Exchange down`, `Jev down`, `Partial fill`, `Stale feed` with the
  regexes in `~/alix/bin/spec-check` (`CASES`).
- **Sight**: one group, name `files and parsing`, trigger from `TOUCHES` in
  `~/sight/bin/spec-check`; cases `Unparseable file`, `No grammar`,
  `Stale ref`, `Empty or huge repo`.
- Weak point: the ALIX and Sight groups are described here, not yet written
  into a tested `kit.toml`; they are checked when those projects migrate
  (Kartoteka's file is the only one run today).

## `guard-main` (the main-checkout hook)

| Copy | Lines unlike Kartoteka | What it blocks in the main checkout |
|---|---|---|
| Clean | 17 | as Kartoteka |
| Mind | 19 | also `cargo` and `tauri` subcommands except info, dev, build, help; knows `--manifest-path` |
| Sight | 63 | every `cargo` command |
| ALIX | 84 | every `mix` command |
| Glyph | 83 | every `bun`, `bunx`, `acton`, `npm`, `npx`, `node` command |

Taken for the shared file: the mutating-git list, the `git merge --ff-only`
exception, bare `git stash` / `stash pop`, shell tracing, and verbose curl on
an authenticated request (all projects); path resolution and
`project.worktrees` (Kartoteka, Clean, Mind); a `[[guard.block]]` list for
the stack's commands (Kartoteka, Mind: bun). Kartoteka's rules for what
`bun` may do (add, remove, update, link, `install` without
`--frozen-lockfile`, `run format`, `--write/--fix/--update/-u`) are in
`migration/kartoteka/kit.toml`.

What each project puts in its `kit.toml`:

- **Mind**: Kartoteka's bun blocks plus
  `[[guard.block]] pattern = '{start}cargo([[:space:]]|$)'`, reason "it writes
  Cargo.lock and src-tauri/target"; and one for tauri:
  `pattern = '{start}(bun[[:space:]]+run|bunx|bun)[[:space:]]+tauri[[:space:]]+[a-z]'`,
  `unless = 'tauri[[:space:]]+(info|dev|build|help)([[:space:]]|$)'`.
- **ALIX**: `pattern = '{start}mix([[:space:]]|$)'`, reason "it writes _build/
  and deps/". ALIX blocked every `mix` command, not only mutating ones; keep
  that.
- **Sight**: `pattern = '{start}cargo([[:space:]]|$)'`, reason "it writes
  target/ and Cargo.lock".
- **Glyph**: `pattern = '{start}(bun|bunx|acton|npm|npx|node)([[:space:]]|$)'`,
  reason "it writes node_modules/ and build output".
- **Mind** also sets `[guard] target_flags = ["--cwd", "--manifest-path"]`
  (the hook turns a file target such as `Cargo.toml` into its folder).
- **Weak points**: the Mind `--manifest-path` and tauri blocks above are not
  yet covered by `tests/test_hook_guard_main.py` (only the bun and cargo cases are); the
  hook catches slips, not a determined bypass, as before.
