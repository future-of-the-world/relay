# Design: a wrong value in project settings passes unnoticed (revised after review)

Queue item `a-wrong-value-in-project-settings-passes-unnotic` (fix, ip 86, agent-chosen).
Worktree: ~/relay/.worktrees/a-wrong-value-in-project-settings-passes (head 87c338ee: the queue commit only; nothing built yet).

Terms used below:
- **kit.toml**: a project's settings file, `<project>/.claude/kit.toml`, tracked in git. Sections such as `[delegate]` hold keys such as `build_tier_opus`.
- **reader**: any code that opens kit.toml and acts on a value (a hook, a `relay` command, the `kit get` helper that skill texts call).
- **problem**: one thing wrong in the file or in an override: the file does not parse, a section is not a table, a key relay does not know, a value of the wrong type, a value outside its allowed set or range, a key that has no effect.
- **env override**: an environment variable that replaces a kit.toml value (`RELAY_DELEGATE_TYPED_ONLY`) or a hook constant (`RELAY_CTX_STEP`).
- **flat section**: a section whose keys are plain values (`[delegate]`, `[land]`); a **nested section** holds tables or lists of tables (`[guard]`, `[packet]`).

## 1. What this decides (summary)

One new module, `lib/relay_kit.py`, is the one parser of kit.toml. It holds the list of every section and key relay knows (the schema), one typed record per flat section, and a `load` that never raises: it returns the values to use plus a list of problems, each a sentence naming the file, the key, the value, what is wrong and what was used instead. `relay_config.load_bindings` and `relay_config.get` are removed: every reader takes the typed record from `relay_kit.load`, so the values a reader acts on and the problems it reports come from the same parse. A wrong value falls back to the key's default, and every guard key's default is its strict setting. Every hook puts the problems of its sections into the context the session sees (not stderr); commands print them on stderr once per run; `relay doctor` shows one red line per problem. Env overrides go through the same field rules.

The one choice left to the owner: whether `relay gate` also refuses a branch whose kit.toml has a problem (section 6).

## 2. Measured on 30 Oct (live probes on the worktree's code, temp project under the scratchpad)

| Setting written | What happens today | Effect |
|---|---|---|
| `[delegate] build_tier_opus = "denny"` | an Opus worker with no `Escalated:` line is allowed (front reproduced it, item note 30 Oct) | the guard is off |
| `[delegate] label_guard = "denny"` | an unlabelled `delegate:worker` is allowed, no output, exit 0 | the guard is off (**new, not in the item**) |
| `[delegate] typed_only = "false"` (text) | a general-purpose agent is still denied | read as true: strict, but nothing says the value is wrong |
| `RELAY_DELEGATE_TYPED_ONLY=1` | a general-purpose agent is allowed | anything other than the word `true` switches the guard off (**new**) |
| `[observe] log_prompts = "false"` (text) | `log_prompts_enabled()` returns True | prompts go into the ledger although the owner wrote "false" (**new**, a privacy hole) |
| `[delegate` (unclosed) + `build_tier_opus = "deny"` | silent defaults; the deny seen is only the default `escalate` | no word that the file is broken |
| `RELAY_CTX_STEP=abc` | `budget.py` exits 1 with `ValueError` at import | the context budget warnings stop |

Readers (grep of the worktree, 30 Oct): 25 code files open kit.toml (8 hooks, `plugins/relay/bin/kit`, 2 plugin libs, 14 files in `lib/` and `bin/relay`). 16 call sites outside relay_config.py go through `relay_config.load_bindings` / `get` / `worktrees_folder` and read a raw dict. 7 call sites use a module's own `setting(cfg, key)` (relay_land 1, relay_metrics 1, ask_waiting 1, lanes.py 4). 16 sections are in use: `project, gate, coordination, product, packet, spec_check, guard, rules, specs, flow, delegate, observe, metrics, front, land, license`.

Live kit.toml files on this machine: 2 (relay, kartoteka). Kartoteka's `[product]` has 4 keys relay never reads (`look_review, widths, build, serve`); kartoteka's own skills read them through `kit get`. Neither file has `[observe] enabled`.

`relay setup` writes into every new project keys that no relay Python code reads: `project.name`, `project.stack_skills`, `gate.wt`, `gate.ci_log`, `gate.final`, `coordination.mode` (skill texts read some of them through `kit get`), and `[observe] enabled = true`, which nothing reads. `relay_config.relay_defaults()` is called by nothing.

The main-checkout guard (plugins/relay/hooks/guard_main.py:221-229) already refuses every Edit, Write and Bash call when kit.toml does not parse, and `relay gate` refuses an unreadable kit.toml (lib/relay_gate.py:58-63). So a syntax error already stops work. A wrong value in a file that parses stops nothing anywhere.

## 3. Critique of the brief

- **The section list.** The item names five sections; 16 are in use. The item also says "all sections relay reads", so the design takes all 16.
- **The loop check misses the tests of the failing case.** It names the ledger and setup tests but not `tests/test_hook_route_guard.py`, `tests/test_hook_budget.py`, `tests/test_openspec_hook.py`, `tests/test_hook_flow_stage.py`, `tests/test_land.py`, `tests/test_lanes.py`, and the failing case lives in the first. The builder adds them and the new `tests/test_kit_schema.py` to the loop.
- **Pass case 3 (typed_only) is reworded.** It says "not read as true". After the fix the text `"false"` is reported and the strict default `true` is used, because a text "false" could be a typo of either word. The checker judges against the item text, so the item needs the reworded pass case before the build (section 5.6, decision 7).
- **The size (2h on the item).** Converting 25 readers to the typed record is more than the item assumed: about 150-210 worker minutes (not measured: a guess).
- **Shared files.** The design changes call sites in 3 files of another lane (section 8).

## 4. Approaches considered

| | A. One schema module, every reader through it (chosen) | B. A schema file checked only by `relay doctor` | C. Do nothing beyond patching the 4 holes |
|---|---|---|---|
| What it is | `lib/relay_kit.py`: typed record + parser + problems; readers switch | `data/kit.schema.json` + a small stdlib validator in doctor; readers stay ad hoc | 4 one-line fixes in route-guard.py, ledger.py, budget.py |
| `"denny"` at the guard | strict default + a note | still decided by the guard's own code (needs the patch from C too) | strict default, silent |
| Doctor names a typo | yes | yes | no |
| Sources of truth for a key | 1 | 2 (schema file and each reader's own default) | many, as today |
| Size (not measured: a guess) | about 150-210 worker minutes | about 40 | about 15 |

How leading tools handle this (from memory, not checked here): Ruff refuses an unknown config key with "unknown field `x`, expected one of ...". Cargo warns "unused manifest key: package.x" and goes on. validate-pyproject checks `[project]` against a JSON Schema and errors. Relay follows them: its own sections are closed (Ruff), `[product]` stays open (like Cargo's `[package.metadata]`).

## 5. Design (A)

### 5.1 The schema and the record (`lib/relay_kit.py`)

- Standard library only, runs on Python 3.9 (hooks may run under it): `from __future__ import annotations`, no `match`, no `slots=`/`kw_only=`. It reads with `relay_toml` and does **not** import `relay_config`, because `plugins/relay/lib` has no `relay_config` link (relay_land.py:39 works around it).
- **What the schema holds.** Every key relay code reads, every key the setup template (`lib/relay_setup.py` `bindings_text`) writes, and every key `plugins/relay/README.md` documents. Tests 11 and 17 fail when one is missing.
- **Flat sections get a frozen dataclass each:** `Project, Gate, Rules, Specs, Flow, Delegate, Observe, Metrics, Front, Land, Coordination`. The dataclass is the schema. Each field's default is the key's default; its metadata holds the kind (bool, int, str, list of str; written out, because under 3.9 annotations are strings), and `choices=(...)` or `bounds=(low, high)` with `outside="clamp"|"default"|"refuse"`. `outside` keeps today's result for each key, so only the reporting changes:
  - land, metrics, front `stop_nudge` and `lane_quiet_hours` clamp;
  - `front.lanes_line_items` takes the default;
  - `rules.lanes` and `rules.wave_min` refuse, as `relay sync` does now.
  The value in the record is already the value to use (clamped or defaulted), so the modules' own `setting(cfg, key)` functions and `SETTINGS` tables go: callers read `kit.land.land_tries`.
- **Nested sections are listed by key names only:** `guard` (`target_flags, secret_patterns, block[pattern, unless, reason]`), `packet` (with `required_test[...]`), `spec_check` (`group[name, trigger, cases]`), `license` (`id, holder, headers`). Their values stay with their existing parsers, which already refuse loudly (guard_main dies, relay_license raises ValueError); they take `kit.raw[section]` from the same parse. The schema adds only "unknown key" reports for them.
- **`[product]` is open.** relay knows `medium, run_skill, surface`; any other key is the project's own and is not reported (kartoteka's 4 keys).
- **A section not in the list is reported** ("unknown section [delegat]"): this catches a misspelt section name.
- **A section that is not a table** (`delegate = "x"`, or `[[delegate]]`, an array of tables) gives that section's defaults and one problem: `[delegate] is not a table; defaults used`. The same for a nested table that is not a table. `load` catches every exception of its own section builders, so "never raises" holds by construction and is tested (tests 18-19).
- **The record:**
  - `Kit` (frozen): `path`, one field per flat section, `raw` (the parsed dict, for nested and open sections and `kit get`), `problems: tuple[Problem, ...]`, `broken: Problem | None` (the syntax error, if any).
  - `Problem` (frozen): `where` (`.claude/kit.toml [delegate] build_tier_opus` or `env RELAY_DELEGATE_TYPED_ONLY`), `value` (repr), `wrong` (`not one of escalate, allow, deny`), `used` (`"escalate"`). One `line()` method renders the sentence.
- **Functions:**
  - `load(root) -> Kit`: never raises. Missing file: defaults, no problems. Syntax error: defaults, `broken` set, one problem naming the file and the parser's message (e.g. `Expected ']' at the end of a table declaration (at line 1, column 10)`). Within one process it keeps the Kit by path and file modification time, so a command that reads several sections parses once and every reader sees the same problems.
  - `parse(text, path) -> Kit`
  - `env(name, section, key) -> tuple[value, Problem | None]`
  - `problems_of(kit, *sections)`: the problems a reader shows: always the syntax error, plus those in its sections.
  - `warn(kit, *sections)`: prints `problems_of` on stderr, each line at most once per process (for commands).
- **Which root each reader passes.** The same folder it reads today, so a problem a hook names is the problem of the file that reader acts on: route-guard, spec-rule, flow-stage, budget and ledger pass the session's working folder's git top level (a worktree reads its own, tracked, kit.toml; route-guard today uses the bare cwd, which in a sub-folder misses the file, and this fixes it); lanes.py, ask_waiting and the `relay` commands pass the main checkout as today; doctor passes the main checkout. A branch that edits kit.toml is thus checked by the hooks running in its worktree and by the gate (section 6), and by doctor only after it lands.
- **Removals and moves in `relay_config`.** `load_bindings`, `get` and `relay_defaults` are deleted. `worktrees_folder(main)` and `default_branch` read `relay_kit.load(main).project`. `relay_config` imports `relay_kit`, so `relay_kit.py` gets a link wherever `relay_config.py` or `relay_toml.py` has one: `plugins/{delegate,front,observe,openspec,relay}/lib/relay_kit.py -> ../../../lib/relay_kit.py`. `tests/test_plugin_links.py` covers the links.

### 5.2 What each reader does with a problem

Hooks: Claude Code shows a hook's stderr to no one on exit 0; only the hook's stdout context reaches the session. So every hook says it in its context, never on stderr.

| Reader | Sections | Value used on a problem | Where it says so |
|---|---|---|---|
| route-guard.py (PreToolUse Agent) | delegate, metrics | the key's default (strict) | appended to its deny reason, or a note (`additionalContext`) when it allows |
| ledger.py (observe) | observe | `log_prompts` → false | a note in its SessionStart context |
| budget.py (PostToolUse, UserPromptSubmit) | env `RELAY_CTX_HANDOVER_AT`, `RELAY_CTX_WRAP_AT`, `RELAY_CTX_STEP` | the default | in its own `additionalContext` note; exit 0 |
| lanes.py, ask_waiting.py (UserPromptSubmit) | front, project | as today (clamp/default) | the lanes line, which already says "out of bounds" (`setting_note`); extended to any problem in its sections |
| spec-rule.py (SessionStart, SubagentStart, UserPromptSubmit) | specs | `method` → "none" | a note in its `additionalContext` (the channel it already uses, spec-rule.py:132), one line per problem |
| flow-stage.py (UserPromptSubmit) | flow | `kind` → "none" | a note in its `additionalContext` (flow-stage.py:116) |
| guard_main.py (PreToolUse) | whole file | dies on a syntax error, as today | unchanged; its `kit dump` call reads through relay_kit |
| `kit get` / `kit dump` (plugins/relay/bin/kit, called by skill texts in Bash) | the asked key's section | for a flat key the typed value (default on a problem) | stderr of the Bash call, which the agent sees; a syntax error stays exit 1 naming the file |
| kit_packet, kit_spec_check, relay_license | packet, spec_check, license | unchanged (they already refuse loudly) | unchanged; they take `kit.raw` |
| `relay land`, metrics, coverage, lanes, lane_features, rules, git, estimate, inert, queue | their sections | as today (clamp/default/refuse per key) | `relay_kit.warn` on stderr, once per run: a person or agent reads that terminal |
| `relay gate` (relay_gate.py) | gate | as today | refuses on `kit.broken` as today (lib/relay_gate.py:58-63); on other problems per the owner's answer to section 6 |
| `relay setup` detect / doctor | all | n/a | doctor lines (5.4) |
| route-guard.py, any crash | n/a | the agent is allowed (fail-open, as today) | **new:** the outer `except` (route-guard.py:213-217) now emits a note naming the exception instead of nothing |

Worked values:
- `build_tier_opus = "denny"`: `Settings note: .claude/kit.toml [delegate] build_tier_opus = "denny" is not one of escalate, allow, deny; the guard used "escalate". Fix the line; relay doctor lists every problem.`
- `[specs] method = "opnspec"`, SessionStart: spec-rule.py stdout context names `.claude/kit.toml [specs] method` and `"opnspec"`, exit 0. `"openspec"`: today's rule text and steps, no note. No `[specs]`: prints nothing, as today.
- `[front] feature_lanes = "3"` (text): the lanes line uses 0 (the default) and names `.claude/kit.toml [front] feature_lanes`.
- `[land] land_tries = 9`: `relay land` still clamps to 3 and prints one problem line on stderr.
- No `[front]`: the lanes line is unchanged, no problem line.

The note repeats on every hook call while the problem stays, about 60 tokens per call. There is no "said once" marker, because a marker would be one more stored state (principle 3).

**Why defaults and not "refuse every agent".** Every guard key's default is its strict value: `typed_only` true, `build_tier_opus` escalate, `require_skill` deny, `label_guard` deny, `metrics.enabled` true. So a wrong value can only tighten a guard. Two exceptions: a project that lowered `fork_limit` below 100000 falls back to 100000; `max_parallel` only adds a note anyway. Refusing every agent on one wrong key would also stop the worker that fixes the file. A syntax error already stops everything through the main-checkout guard.

**Why the route guard's crash path stays open but speaks.** Today any exception inside the guard allows the agent silently (route-guard.py:213-217). Making it fail closed would stop every agent on one guard bug, including the one sent to fix it. The fix keeps it open but no longer silent: the note names the exception. With `load` unable to raise (5.1), a broken kit.toml can no longer reach this path.

### 5.3 Env overrides

`RELAY_DELEGATE_<KEY>` is parsed by the same field rules as the kit.toml key:
- booleans accept only `true` or `false`, in any letter case;
- `RELAY_DELEGATE_TYPED_ONLY=1` → the default `true` + a problem.

`RELAY_CTX_*` keys are whole numbers:

| Setting | Default | Bound | At the bound |
|---|---|---|---|
| `RELAY_CTX_STEP` | 30000 | ≥ 1000 | at 1000, a budget note about every 1k tokens |
| `RELAY_CTX_WRAP_AT` | 200000 | ≥ 1000 | at 1000, the wrap note from the first request |
| `RELAY_CTX_HANDOVER_AT` | 350000 | ≥ 1000 | at 1000, the handover note from the first request |

Below 1000 or not a number → the default + a problem. No upper bound (not asked for).

### 5.4 `relay doctor`

- One project check per problem, red: name = `where`, detail = `is <value>: <wrong>; used <used> -> fix it in .claude/kit.toml`.
- No problems: one green line, `.claude/kit.toml: keys and values valid`.
- **Env.** Doctor checks its own shell's env and the `env` blocks of `~/.claude/settings.json` and the project's `.claude/settings.json` and `.claude/settings.local.json` (what sessions actually get), for the prefixes `RELAY_DELEGATE_` and `RELAY_CTX_` only. An unknown name with those prefixes (`RELAY_DELEGATE_TYPED_ONLLY`) is a problem.
- `detect(root)["bindings"]` becomes the Kit; its 6 dict reads in relay_setup.py (lines 100, 636, 873, 910, 972, 1303) read typed fields or `kit.raw`.
- A red doctor line blocks nothing else: only `relay doctor` (bin/relay:546) and `relay setup` (relay_setup.py:1228) call `doctor_parts`.

### 5.5 `[observe] enabled`: dropped

No code reads it; 0 of 2 live kit.toml files have it. It is removed from the schema and from the setup template. A file that still has it gets: `[observe] enabled has no effect: no code reads it; remove the line`. This differs from `project.name` or `gate.final`, which also no Python code reads: those are data that skill texts read through `kit get`, and are in the schema; `enabled = false` looks like a switch that keeps a project out of the cost ledger and does nothing, so it misleads.

Turning it into a real switch would be a new mechanism, which goes to the design track, not into this fix (principle 7).

### 5.6 Decisions made (the owner can reverse each)

1. All 16 sections are in the schema; nested sections are checked for key names only.
2. Relay's own sections are closed; `[product]` is open; unknown sections and non-table sections are reported.
3. A wrong value falls back to the key's default; out-of-range numbers keep today's clamp, default or refuse per key.
4. One parser: `relay_config.load_bindings`, `get`, `relay_defaults` and the modules' `setting()` / `SETTINGS` are removed; every reader takes the Kit.
5. Hooks say problems in their session context, on every call; commands on stderr once per run; doctor lists them all. The route guard's crash path stays open and now names the exception.
6. Env booleans accept only true/false; `RELAY_CTX_*` must be ≥ 1000.
7. Pass case 3 of the item reads: `typed_only = "false" (string) is reported as a wrong type; the strict default true is used (a general-purpose agent is denied, and the deny reason names [delegate] typed_only)`. The front records it as a note on the item before the build (`relay queue note`, a decision), so the checker judges against it.
8. `[observe] enabled` is removed from the schema and the template.

## 6. Question for the owner

**Should the gate stop a branch whose settings file has a mistake**

relay lands a change only after `relay gate` passes on it. The gate already refuses a branch whose kit.toml does not parse (lib/relay_gate.py:58-63, "cannot read .claude/kit.toml"), because it needs `gate.ci` from it. A file that parses but holds `build_tier_opus = "denny"` passes the gate today and lands. After this fix the route guard notes it on every agent start in that project, and doctor shows it red, but the typo is already on the default branch. The question is whether the gate also refuses such a branch, so the typo never lands.

Measured: relay's own file and kartoteka's have 0 problems under the schema once `[product]` is open (tests 9 and 10 confirm it in the build), and a fresh `relay setup` file has 0 (test 17). The one live cost: a project set up before this change with `[observe] enabled = true` (none of the 2 on this machine) would be refused until the line is removed. A hand edit made on the default branch outside Claude skips the gate either way.

| | a. Gate refuses | b. Report only |
|---|---|---|
| A typo on a branch | stopped before landing, with the problem line | lands; noted at the next agent start and by doctor |
| Cost | one parse per gate (milliseconds), about 5 lines in relay_gate.py | none |
| A key a newer relay renamed | the branch cannot land until the line is fixed | lands, then shows red in doctor |

- **a.** (recommended) The gate refuses a branch whose kit.toml has any problem.
- **b.** Doctor and the hooks report; the gate does not refuse.

## 7. Tests (one per scenario; each shown to fail with the fix disabled)

In `tests/test_hook_route_guard.py`:
1. `build_tier_opus = "denny"`: an Opus `delegate:worker` with no `Escalated:` line is denied, and the reason names `[delegate] build_tier_opus`. (The failing case.)
2. `"deny"` denies even with an `Escalated:` line. With no key, denied without the line and allowed with it.
3. Unclosed `[delegate`: the output names `.claude/kit.toml` and the parser's message, and the defaults apply.
4. `label_guard = "denny"`: an unlabelled worker is denied, plus the note.
5. `RELAY_DELEGATE_TYPED_ONLY=1`: a general-purpose agent is denied, plus a note naming the variable.
6. `typed_only = "false"`: a general-purpose agent is denied and the reason names `[delegate] typed_only`; `typed_only = false` (boolean): allowed, no note (today).
19. `delegate = "x"` and `[[delegate]]` with `typed_only = false`: a general-purpose agent is denied, with a note naming `[delegate]`.
20. A guard crash (a monkeypatched `decide` that raises): exit 0, the output names the exception.

In `tests/test_kit_schema.py`:
7. Unknown key in `[observe]`: doctor has a red line naming it.
8. `[delegat]`: an unknown section is reported.
9. A kartoteka-shaped file (`plugins/relay/tests/profiles/kartoteka.toml`) has 0 problems.
10. Relay's own `.claude/kit.toml` has 0 problems (catches a schema that forgot a key such as `front.feature_lanes`).
11. Every `kit get <key>` in `plugins/`, `templates/` and `lib/`, and every key `plugins/relay/README.md` documents, names a key in the schema. This is the test that fails if "the schema lists every key relay reads" is false.
12. Doctor reports a bad `RELAY_CTX_STEP` found in a temp `settings.json` env block.
17. `bindings_text` for a UI and a non-UI project parses with 0 problems; the same text plus `[observe]\nenabled = true` has exactly 1 problem, naming `[observe] enabled`.
18. `parse` of `delegate = "x"` and of `[[delegate]]` gives `Delegate()` defaults and one problem naming `[delegate]`, and raises nothing.
21. `load` of the same path twice in one process parses once (the parse function is counted).

Other files:
13. `tests/test_hook_ledger.py`: `log_prompts = "false"` stores no prompt and the SessionStart note names the key.
14. `tests/test_hook_budget.py`: `RELAY_CTX_STEP=abc` exits 0, uses 30000, and says so.
15. `tests/test_setup.py`: a new project's kit.toml has no `[observe] enabled`.
22. `tests/test_openspec_hook.py`: `[specs] method = "opnspec"` on SessionStart: stdout names `.claude/kit.toml [specs] method` and `opnspec`, exit 0; `"openspec"`: today's text, no note; no `[specs]`: nothing.
23. `tests/test_hook_flow_stage.py`: `[flow] kind = "jria"`: the context names `[flow] kind`.
24. `tests/test_lanes.py`: `[front] feature_lanes = "3"`: the lanes line uses 0 and names the key; no `[front]`: unchanged.
25. `tests/test_land.py`: `[land] land_tries = 9`: clamped to 3 and one problem line on stderr.

Only if the owner picks 6a:
16. The gate on a worktree with `build_tier_opus = "denny"` refuses and names the line.

All tests use a temp folder, never the live `.relay/` or `docs/handover.md`.

## 8. Shared files with other lanes

- `lib/relay_land.py`: also changed by wt/gates-on-the-vps-hosts-transport-watch-b.
- `lib/relay_lanes.py` and `lib/relay_metrics.py`: also changed by wt/branch-names-cut-at-40-characters-mid-wo.

Here the `SETTINGS` table and `setting()` go and their callers read the Kit (relay_land 1 call site, relay_metrics 1 plus `enabled()`, relay_lanes 2 plus `worktrees_folder`), so a conflict when taking the default branch is a few hunks per file. `bin/relay` (two other lanes) is not touched: doctor lives in lib/relay_setup.py.

## 9. What changed after the review

| Finding | Held? | Fix |
|---|---|---|
| F1 (MEDIUM): spec-rule.py and flow-stage.py report on stderr, which no one sees on exit 0 | Held. Both hooks already emit `additionalContext` (spec-rule.py:132, flow-stage.py:116); stderr on exit 0 reaches no one. | Table 5.2: both say it in their context; a general rule above the table that no hook uses stderr. Tests 22, 23. |
| F2 (MEDIUM): the dict API (`load_bindings` + `get`, 16 call sites, 7 `setting()` calls) stays, so most readers bypass the typed record | Held. The project's Python rule asks for one typed record and one parser, and design 5.1 kept a second path. | `load_bindings`, `get`, `setting()` and `SETTINGS` are removed; every reader takes the Kit; `load` keeps one parse per file per process; commands print through `warn` once per run; table 5.2 lists lane_features, coverage, inert, queue, estimate, git, gate, `kit get`, doctor's `detect`. Tests 21, 24, 25. Size guess raised to 150-210 worker minutes. |
| F3 (LOW): pass case 3 is changed by the design but not in the item | Held. | Decision 7 gives the reworded text; the front records it with `relay queue note` before the build (a thinker does not write the queue). Test 6 covers both sides. |
| F4 (LOW): no test that a fresh `relay setup` file has 0 problems | Held. | 5.1 states the schema's sources (code, setup template, README); 5.5 says why `[observe] enabled` is reported and `project.name` is not. Test 17. |
| F5 (LOW): a non-table section could make the parser raise, and the guard's outer catch would then allow everything silently | Held (the build could have done it either way; nothing proved it). | 5.1: a non-table section gives defaults and one problem; `load` catches its builders' exceptions. The guard's crash path now names the exception. Tests 18, 19, 20. |
| Reviewer note (not a finding): which root each reader passes | Taken. | 5.1 "Which root each reader passes": hooks pass the git top level of their working folder, commands and doctor the main checkout. |

## Open for the owner

- **Should the gate stop a branch whose settings file has a mistake** (section 6): a. gate refuses (recommended) / b. report only. With no answer, the builder does b and leaves test 16 out.

For the front (not an owner choice): record decision 7, the reworded pass case 3, on the item before the build.

## Remaining

Nothing.
