# Design: a change runs with relay's settings from the project only (revision 4)

Queue item `a-change-runs-with-relay-s-settings-from-the-pro` (feature, IP 95 agent-chosen). Thinker, 30 Oct 2026, measured at
master f43540fa (revision 3) and a870a7a0 (revision 4). Revision 3 answered the owner's four rounds of 30 Oct (brief
`design-session-rev3.md`). **Revision 4** answers the review of revision 3 (9 findings, section 1) and the owner's round 5 (the
registry answer "a" and the request for scenarios, section 6). The whole design is here; what changed since revision 2 is marked
**[rev 3]**, what changed after the review is marked **[rev 4]**. Status: complete.

Terms used throughout:
- **Launcher**: a small relay program that starts Claude Code with extra switches so the session takes its settings from the
  project and from relay, not from the user folder `~/.claude`.
- **Rule text**: the instructions Claude Code reads at the start of every session (files named CLAUDE.md and similar).
- **Memory** (Claude Code's "auto memory"): short notes Claude Code writes by itself between sessions, one file per note plus an
  index file `MEMORY.md` that lists them; today it lives in the user folder, not in the project.
- **Skill**: a folder with a `SKILL.md` that teaches Claude one task (for example "how to run this project's linter").
- **Guard**: a relay program (a hook) that Claude Code runs before an action and that can refuse it, whatever the text says.
- **Main checkout**: the project's own folder (for relay, `~/relay`), kept on the default branch and clean; changes are built in
  separate folders called worktrees.
- **[rev 4] Marker block**: lines that relay writes into a file a person may also edit, between a start line and an end line that
  name relay; relay rewrites only what is between them and never touches the lines outside.
- **[rev 4] The three homes**: relay's repository (defaults only), `~/.relay` (this machine and its owner, never in git), and the
  project's own git (everything about that project). Section 5.11 draws them.

## 0. In one paragraph

Claude Code can run a session that ignores the user's own settings while keeping everything the project itself holds. Probes
(revision 2 about $0.02, revision 3 $0.0057, measured; each one `claude -p` call) show that `--setting-sources project,local`, one
`--plugin-dir` per relay plugin and one generated `--settings` file give a session whose plugins, agents, rules, model and
permissions come from the project and relay's copy of itself, with the sign-in kept and relay's hooks running, and that the
project's own `CLAUDE.md`, `.claude/rules`, `CLAUDE.local.md`, `AGENTS.md`, skills, agents and hooks keep loading. The
recommendation stays **B2: one settings builder in relay, used by a launcher for every Claude Code session in a relay project and
by every Claude Code call the gate makes.** It follows the owner's rule of 30 Oct: relay is a guest in a project, keeps every
setting the project has and adds its shared rules and principles on top; a conflict is met by one rule line (ask the user,
recommend the project's setting), and relay's guards stay in force because they are programs. **[rev 4]** Where things live
follows the owner's round-5 "a": relay's repository ships only defaults, the owner's facts and the machine's project list sit in
`~/.relay`, and a project's own choices sit in that project's git (`.claude/kit.toml`). **[rev 4]** Memory: of 36 notes, 35 leave
Claude Code's per-machine folder (14 duplicates deleted, 20 moved into git as rules or decisions, 1 into the owner's settings).
The recommendation **changed** to the owner's own pick of 24 Oct, which revision 3 missed: a project's notes are kept in that
project's git and every new note lands there at once, so every machine has them (section 5.10). **[rev 4]** The shell function
is shown verbatim (section 5.1) and tested today in zsh and bash: in a folder outside relay, `claude` gets the same arguments,
the same environment and the same exit code as before.

The owner's words (item `why`, verbatim): "Как мы вообще планируем задачи, документируем эксперименты, мы должны быть
устройство независимым, вплоть до того что бы можем запускать каждое изменение в новой docker контейнере где
предустановлены все необходимые утилиты, как будто это запуск ci/cd в стандартных системах (woodpecker), с минимумом
настроек глобального relay, хочу вообще без глобальных настроек relay и claude, полностью чистое окружение с
предустановленными утилитами и файлами проекта / При этом получать тот же результат". Answers of 27 Oct: "3. A", "4. A".

## 1. What changed after the review [rev 4]

The review of revision 3 (30 Oct, 9 findings, no paid probe) is not kept anywhere else; this table is its record. "Held" means
I checked the failing case and it is right.

| Finding | Held? | What changed |
|---|---|---|
| F1 HIGH: the "Scenarios" section the owner asked for in round 5 is missing; the shell function is prose only, with no removal and no proof | held | New section 6 "Scenarios": three scenarios, each with a before/after file table (machine and project), what a session loads, where memory is written, interruption, several actors. The function is in 5.1 verbatim with its marker lines, the files it goes into and `relay install --remove`. The pass-through proof was run today (section 3.4): zsh and bash, outside relay, same arguments, same environment hash, same exit code. The build estimate includes the removal path and the scenario tests (section 9). |
| F2 HIGH: per-project choices and the guest line still routed through relay's `projects.toml`, against round-5 "a" | held | Every `projects.toml` reference is re-pointed: a project's opt-in rules go to its `.claude/kit.toml` (`[rules] load`), the owner's facts (native language, paid cap, subscription) to `~/.relay`, the guest line to a default file in relay's repository (`rules/guest.md`). The machine's project list is derived from setup runs recorded in `~/.relay`. The queue item `relay-as-a-portable-tool-project-data-out-of-rel` moves the data and lands before B2 (section 7 item 15). |
| F3 HIGH: the memory recommendation contradicts the owner's 24 Oct pick (notes kept in the project's git) without saying so, and misdescribes that option | held | Section 5.10 rewritten: the owner's 24 Oct words quoted with the item that holds them; option M2 is the accepted mechanism (notes in the project's git, each note landing at once like a queue item, main checkout clean); my critique said once; the recommendation **moved to M2** on two pieces of evidence (section 5.10). `taste-means-judgement` re-read and re-classed as a decision; the other two "personal" notes re-read too (one moves to the owner's settings). The open question marks option a as the owner's 24 Oct pick. |
| F4 MEDIUM: the function is written into the zsh startup file only, while install work is Linux-first and Linux shells are bash | held | `relay install` writes the same block into `~/.zshrc` and `~/.bashrc` (each one that exists, and the one of `$SHELL` always); the block is valid in both shells (tested, section 3.4); a second install leaves one block per file; `--remove` deletes it from every file. Other shells (fish) are named as not supported by install's output. |
| F5 MEDIUM: a project that commits its `CLAUDE.local.md` gets a dirty tree at every start | held (no such project exists today; the failing case is real) | Section 5.1: when `CLAUDE.local.md` is tracked by git, the launcher does not write it; it passes relay's text with `--append-system-prompt` (offered in `claude --help` of 2.1.314 without a print-only note; the builder probes interactive use first) and says once at start that subagents of this session do not get relay's text. Tree stays clean. Test cases in 5.3. |
| F6 LOW: one run settings file per start under `.git/relay`, never removed | held | Section 5.1: the file name carries the launcher's process id; each start deletes files whose process is gone. The number of files is then bounded by the number of live sessions, so no tunable number is needed (section 5.4 says why). |
| F7 LOW: count slips (29 vs 19 moved; 12 vs 11 unindexed duplicates; Python both opt-in and moved) | held | Recounted live: 15 notes are not in the index, 11 of them duplicate rules. With F3's re-reading the totals are now 14 deleted, 20 moved into git, 1 to the owner's settings, 1 stays (section 3.3). The opt-in example no longer names Python. |
| F8 LOW: the fixed subcommand list goes stale as Claude Code auto-updates, and an option before a subcommand (`claude --debug mcp list`) defeats the first-argument test | held | No fixed list: the launcher reads the "Commands:" list from `claude --help` of the installed version (cached per version in `~/.relay`) and finds the first word that is not an option or an option's value. Live evidence the list moves: today's list has `attach`, `logs`, `respawn`, `rm`, `stop`, `ultrareview`, which revision 3's examples did not name. Section 5.1. |
| F9 LOW (outside): ALIX still loads a relay-generated `CLAUDE.local.md` of 24 Oct, 71 lines, that nothing updates | held | A fix item in section 10, and a line in scenario 3: the launcher only rewrites the relay block in projects it starts in; doctor names a relay-marked file in a folder that is no longer a relay project. |

Also from the review's notes, carried in: `~/AGENTS.md` (3,160 bytes, the owner's working agreements of 13 Oct) sits above every
project in the home folder and does not appear to load today; the builder confirms with one probe run from inside `~/relay`
(revision 3's probes ran under the scratchpad and could not see it).

## 2. The owner's words, and what the design does with them

The owner's answers of 30 Oct, verbatim (the numbers are the owner's: 2 = how a session starts, 3 = memory, 4 = grilling):
- Round 1: "2. Пункт про запуск сессии мне не понятен, давай разберем отдельно / 3. Что ты имеешь ввиду, можешь показать пример /
  4. Можем ли мы использовать это просто как skill, кажется что это внешнее, мы можем использовать это как и любой другой skill"
- Round 2: "1. Да, это небольшой trade-off, впоследствии мы переедем полностью / 2. Как это будет работать, это первый шаг к тому
  чтобы мы использовали только relay для relay ? / 3. Кажется что 2 пункт это отключает, наблюдается конфликт / 4. Если мы
  применим 2 пункт, смогу ли я загружать его по просьбе, или сможем ли мы включить его в конкретный проект, думаю эту часть как и
  openspec лучше отделить от relay, он здесь не привносит ничего нового, использовать это можно и без него"
- Round 3: "2. Что будет входить в эти 245 минут, в описании тут видно только shell обертка, как я могу кастомизировать правила
  для конкретного проекта, допустим хочу включить правило - node под запретом, только relay, не общее правило, а именно для
  relay, или указать рекомендации по работе именно с конкретными проектом, допустим skill для использования linter / 3. Что
  будет в этой memory, как это сочетается с тем что изменения могут идти с нескольких машин, как это сочетается с 2 пунктом /
  4. a, думаю что не стоит игнорировать .claude/skills/*, в случае если эти принципы противоречат друг другу оставлять это на
  волю пользователя, до тех пор пока не будет исправлено отказываться работать"
- Round 4 (replaces round 3 point 4): "2. Да, relay не отказывается от настроек которые пользователь уже имеет в
  репозитории, он должен их уважать, при этом добавляя свои правила и принципы, которые являются общими для relay, часть
  философии разработки relay / 3. Значит ли это что вопрос исчерпан, до пересмотра / 4. Думаю что можно просто добавить строчку -
  если нашел противоречие между правилами relay и правилами проекта - спроси пользователя, рекомендуй использовать настройки
  проекта, ты в гостях, уважай место где ты находишься, мягкий способ разрешать конфликты, без строгих проверок"
- **[rev 4]** Round 5, after answering "a" to the registry question (owner settings and the machine's project list in
  `~/.relay`, a project's own settings in that project's git, relay's repository ships only defaults): "a, что ты подразумаешь
  под правилами, я немного запутался касательно того где и как лежат данные, память, как мы это будем разделять, думаю тебе
  следует визуально это продемонстрировать для лучшего понимания / 1. Сценарий новой машины + git repo / 2. Сценарий машины с
  существующими правилами + git repo / 3. Сценарий машины с существующими правилами + существующий git repo со своими правилами /
  Как будет меняться поведение, хранение файлов, прерывание работы и работа нескольких actor / Будет ли установщик править claude
  shell, как это будет выглядеть, как это измениться для проектов которые не используют relay ?"

What the design does with them:
1. **Settled by the owner:** relay keeps every setting the project has in its repository (`CLAUDE.md`, `AGENTS.md`,
   `.claude/settings.json`, `.claude/skills`, `.claude/agents`) and adds its own shared rules and principles on top. Section 5.8
   shows, file by file, where a project author puts a project-only rule and a project skill, with probes.
2. **Settled by the owner:** a conflict between relay's rules and the project's is handled by one rule line, with no checks in
   code and no refusal (section 5.9). The round-3 design ("refuse to work until fixed") is dropped.
3. **Settled by the owner:** grilling is not part of relay, like OpenSpec. A project that wants it keeps its own copy in its
   `.claude/skills`.
4. **[rev 4] Settled by the owner (round 5 "a"):** relay's repository ships only defaults; the owner's settings and the machine's
   project list live in `~/.relay`; a project's own settings live in that project's git. Section 5.11 draws it.
5. **Memory:** the 36 notes classified (section 3.3), approaches compared (section 5.10), "is the question closed" answered there.
6. **Decisions inside the principles,** all following from "relay respects what the project has" (section 7).
7. **The 245 agent minutes** listed in plain words and re-estimated (section 9).
8. **[rev 4] Round 5's "what do you mean by rules":** in this design a *rule* is a piece of text that tells Claude how to work
   ("Node is not used in relay; use bun"). Rules are files: relay's shared ones in relay's `rules/`, a project's own in its
   `.claude/rules/` or `CLAUDE.md`. *Settings* are values a program reads (which plugins are on, how many lanes, the paid cap).
   *Memory* is notes Claude writes by itself. Section 5.11 shows where each one lives.
9. **My reading, for the front to confirm:** round 4 "2. Да" answers revision 2's first question (how a session in a relay
   project becomes project-only) with **a, the shell function**. Not listed as decided in the brief, so it stays in "Open for the
   owner" as a confirmation, now with the function shown.

## 3. Measured

### 3.1 Probes (one `claude -p` each, haiku, `--max-turns 1`, RELAY_HOME in the scratchpad)

Revision 2's probes (30 Oct, in this item's worktree):

| Probe | Flags | Plugins load from | Extra user agents / skills | User rules file `~/.claude/CLAUDE.md` | Auto memory | Signed in | Cost |
|---|---|---|---|---|---|---|---|
| p0, p5 | none (as today) | main checkout `~/relay/plugins` | `worker`, `reviewer`; `grilling` | loaded | loaded | yes | $0.0047 |
| p2, p3 | `--setting-sources project,local` + `--plugin-dir` x4 | the worktree | none | **still loaded** | **still loaded** | yes | $0.0040 |
| p6 | p3 + `--settings {"claudeMdExcludes":[user file],"autoMemoryEnabled":false}` | the worktree | none | **not loaded** | **not loaded** | yes | $0.0024 |
| p7 | p3 + `--settings {"autoMemoryDirectory":<empty folder>}` | the worktree | none | loaded | not loaded (redirected) | yes | $0.0037 |
| p4 | p3 + `CLAUDE_CONFIG_DIR=<fresh folder>` | - | - | - | - | **"Not logged in"** | $0 |
| p8 (free) | `--setting-sources project,local --settings {...} plugin list` | - | - | - | - | - | $0: exit 0, lists the user's install registry |

Revision 3's probes, all with the p6 switches and relay's four enabled plugins, in two throwaway projects in the scratchpad. Each
file carried one made-up code word; the session was asked to list the code words it had been given.

| Probe | What the project holds | Answer | Also seen in the start message | Cost |
|---|---|---|---|---|
| q1 | `CLAUDE.md` (HERON), `AGENTS.md` (OTTER), `.claude/rules/probe.md` (LYNX), `CLAUDE.local.md` (MAPLE), skill `.claude/skills/probe-lint` | HERON, LYNX, MAPLE | skill `probe-lint` listed; user skill `grilling` absent | $0.0015 |
| q2 | only `AGENTS.md` (OTTER) | OTTER | - | $0.0014 |
| q3 | q1 + agent `.claude/agents/probe-linter.md` + a SessionStart hook in `.claude/settings.json` that creates a file | - | agent `probe-linter` listed; the hook ran; old user agents `worker`, `reviewer` absent | $0.0014 |
| q4 | q1 with `@AGENTS.md` as the first line of `CLAUDE.local.md` | HERON, LYNX, MAPLE, OTTER | - | $0.0015 |

What they settle:
- A project's `CLAUDE.md`, `.claude/rules/*.md`, `CLAUDE.local.md`, skills, agents and hooks all load under the launcher's
  switches. Project skills are kept; only the user folder's skills drop out.
- `AGENTS.md` loads by itself only when the project has no `CLAUDE.md` (q2). When a `CLAUDE.md` exists, Claude Code skips
  `AGENTS.md` (q1), and an `@AGENTS.md` line imports it again (q4). relay already knows it: `relay setup` writes that import line
  into a new `CLAUDE.md` (`lib/relay_setup.py:697`, `agents_import`).
- **[rev 4]** p7 matters for memory: `autoMemoryDirectory` passed in the launcher's `--settings` redirects memory, so the launcher
  can point memory anywhere without writing the project's `.claude/settings.local.json` (the 24 Oct proposal's way).

Facts carried from revision 2: under the project-only switches the Workflow tool is offered; the observe plugin's SessionStart
hook writes its record, so hooks run under `--plugin-dir`; one `--plugin-dir <folder of plugins>` loads every child, openspec
included even though the project turns it off, so the launcher passes one `--plugin-dir` per enabled plugin; the claude.ai
connector (Claude Docs) appears under project-only; a fresh config folder loses the sign-in on this Mac (p4), so isolation works
through the p6 switches, not a new config folder.

### 3.2 The global state a change depends on

Classes: **project** = moves into the project or into relay's copy; **input** = named as a required input and recorded per run;
**remove** = deleted; **machine** = stays machine-local because it changes time, not the result.

| # | Piece | Where now (measured) | Changes the result? | Target |
|---|---|---|---|---|
| 1 | Plugins switched on | user `enabledPlugins` (5) + project `.claude/settings.json` (since 28 Oct) | yes: no relay plugin means no merge guard | project (done); the user copy stays for folders outside relay and sessions not started by the launcher |
| 2 | Where plugins come from | user `extraKnownMarketplaces.amidman` = `~/relay`; a retired `principles` entry | yes: today a worktree session runs the main checkout's hooks (p0) | project: `--plugin-dir` of relay's copy; the user entry stays |
| 3 | Plugin install registry and cache | `~/.claude/plugins/installed_plugins.json`, two stale scopes | no under `--plugin-dir` | not read by a launcher run; stale scopes are a fix item (section 10) |
| 4 | Front model and effort | user `model`, `modelSettings...effortLevel` | yes | project: run settings from the profile |
| 5 | Permissions and mode | user allow 2 (one retired); project allow 3 | yes | project: run settings |
| 6 | Environment in settings | user `env.CLAUDE_CODE_RETRY_WATCHDOG` | yes (retries) | project: run settings |
| 7 | Behaviour keys | user `autoCompactWindow: 400000`, `switchModelsOnFlag`, `skipWorkflowUsageWarning` | yes | project: profile `[session]` |
| 8 | Look keys | user `theme: auto` | no | input: pass through (allowlist, 5.4) |
| 9 | Global rules text | `~/.claude/CLAUDE.md` (18,671 bytes), generated by `relay sync`; loads even under project-only (p3) | yes | project: generated by the launcher at every start, hashed per run; the user file excluded |
| 10 | Project rules text (relay's part) | `CLAUDE.local.md` (6,273 bytes, main checkout only), generated, git-excluded | yes | project: same generator as row 9; a hand-written file is kept (section 7 item 10); **[rev 4]** a tracked one is not written (5.1) |
| 10b | The project's own rules, skills, agents, hooks | `CLAUDE.md`, `AGENTS.md`, `.claude/rules`, `.claude/skills`, `.claude/agents`, `.claude/settings.json` (q1-q4) | yes | project, committed, kept as they are (5.8) |
| 11 | Auto memory | `~/.claude/projects/-Users-amidman-relay/memory`, 36 notes + index | yes for the front | **[rev 4]** the project's git, `.relay/memory/` (M2, 5.10); gate, bench and container runs have memory off |
| 12 | Old user agents | `~/.claude/agents/worker.md`, `reviewer.md`, visible in every session (p0), absent under the launcher (q3) | yes | remove |
| 13 | Old user hooks folder | `~/.claude/hooks/` (unwired) | no | remove |
| 14 | User skills | `~/.claude/skills/`: grilling, synced, tauri; dropped under the launcher (p2, q1) | yes for "grill me" | stay personal; a project that wants one keeps its own copy in `.claude/skills` |
| 15 | Account connectors | claude.ai MCP (Claude Docs) | barely | input |
| 16 | Sign-in | macOS keychain, keyed to the config folder (p4) | yes | input (the one input the owner cannot avoid) |
| 17 | Admin-pushed settings | `~/.claude/remote-settings.json` | possibly | input, recorded |
| 18 | Claude Code version | 2.1.314, auto-updates on | yes | input, recorded per run (5.7) |
| 19 | Which relay program runs | `~/.local/bin/relay` -> main checkout | yes | relay's copy = the main checkout, commit, dirty mark and content hash recorded (5.6) |
| 20 | Project list and owner facts | `projects.toml` in relay's repository: `[global]` (native language, paid cap, intro), `[relay]` (lanes, load), with this Mac's paths | yes for rules | **[rev 4]** the machine's project list: `~/.relay`, derived from dated records of `relay setup` runs; owner facts: `~/.relay`; a project's opt-ins and lanes: its `.claude/kit.toml`; the intro: `rules/guest.md`. Moved by item `relay-as-a-portable-tool-...` |
| 21-23 | Gate slots, test tokens, test times, records | `$RELAY_HOME` | no (time, order, records) | machine |
| 24 | Gate tools | python3 3.14.6, uv, ruff, pytest, bun, jq, ps (deps.toml) | yes | project (done) |
| 25 | git global config | identity, editor | identity yes | input |
| 26 | Locale and time zone | `LANG=en_US.UTF-8`, `TZ` unset | not verified | input, recorded |

Drift, measured in revision 2: since 1 Oct, 112 commits touched `rules/`, `profiles/` or `projects.toml` and 426 touched
`plugins/`; each changes what a session on this Mac loads, and the commit under test does not show it. Live today: relay's main
checkout still has `profiles/active.toml` changed and not committed, so a run on this Mac uses a profile no commit holds.

### 3.3 Memory, note by note [rev 3; recounted and re-read in rev 4]

Measured 30 Oct in `~/.claude/projects/-Users-amidman-relay/memory`: 36 notes plus the index `MEMORY.md` (3,050 bytes, 21
lines), 54,398 bytes in all. Claude Code's own type field: 22 feedback, 9 project, 5 user. Written 21-30 Oct. **15 of the 36
notes are not listed in the index** (recounted in rev 4), so a session never sees them unless it opens the folder; **11** of
those 15 are notes whose content already sits in relay's rules: retired from the index, never deleted.

Where memory lives: the folder is keyed to the repository's path on this Mac (`-Users-amidman-relay`). Sessions in relay's task
worktrees share it. 22 projects on this Mac have notes (relay 37 files, ALIX 48). On a Linux machine with relay at another path
the key differs, so that machine starts with no notes.

Classes: **in rules** = relay's rules already say it, the note is a duplicate; **shared rule** = belongs in relay's `rules/`
(every relay project); **relay rule** = belongs in relay's own `.claude/rules/` (only relay); **decision** = a dated decision or
fact that belongs in the queue, the handover or a project doc; **owner fact [rev 4]** = a fact about the owner that a relay
program reads, which round 5 puts in `~/.relay`; **personal** = about the owner, stays a note.

| Note | Type | Index | Class | Where it goes |
|---|---|---|---|---|
| always-review-fixes | feedback | no | in rules | Delegation: "One good review, not several" |
| display-pretty-store-plain | feedback | no | in rules | principle 4 |
| estimates-in-agent-time | feedback | no | in rules | principle 8 |
| flaky-means-find-the-cause | feedback | no | in rules | principle 6, Quality gate |
| measure-before-recommending | feedback | yes | in rules | Working style: "A recommendation says what it rests on" |
| natural-language-triggers | feedback | no | in rules | principle 5 |
| owner-native-language | user | no | in rules | **[rev 4]** the owner's settings in `~/.relay` (today `native_language` in projects.toml); the generated line |
| paid-checks-preapproved | feedback | no | in rules | **[rev 4]** the $200 cap goes to the owner's settings in `~/.relay` (today `paid_cap_usd_per_day` in projects.toml); Git rule on paid runs |
| persist-structured-operate-scripts | feedback | no | in rules | Structured data rule, principle 4 |
| questions-carry-context | feedback | no | in rules | Working with me: "Every question opens with an introduction" |
| say-agree-or-disagree | feedback | yes | in rules | Working with me: "Critique my picks" |
| stop-agents-after-handback | feedback | no | in rules | Working with me: "prune idle agents at once" |
| use-english-it-terms | feedback | yes | in rules | Working with me (standard IT terms) |
| why-cant-is-a-question | feedback | no | in rules | principle 9 |
| frame-a-move-as-a-move | feedback | yes | shared rule | Working with me |
| owner-steers-design | feedback | yes | shared rule | Working with me |
| record-measurements-at-once | feedback | yes | shared rule | Working style |
| no-guard-workarounds | feedback | no | shared rule | Delegation or Git (no rule says it today) |
| podman-only-no-docker | feedback | yes | shared rule | Shell rule (the owner's machines, every project) |
| queue-items-hold-words-and-facts | feedback | yes | shared rule | Work queue rule ("no report links" is not there yet) |
| strategy-and-wave-digest | feedback | yes | shared rule | front skill; item `one-digest-per-wave-instead-of-status-me` is building it |
| bun-not-node | user | yes | relay rule | relay's `.claude/rules/tools.md` (owner, round 3: "только relay, не общее правило") |
| core-is-the-standard-package | feedback | yes | relay rule | relay's `.claude/rules/` |
| paths-via-env-var | feedback | yes | relay rule | relay's `.claude/rules/python.md` |
| language-specific-rules-per-language | project | yes | relay rule | relay's `.claude/rules/` |
| front-stays-on-opus | project | yes | decision | a comment beside the front's model in `profiles/active.toml` (the bench result and date) |
| glonass-deferred | project | yes | decision | a queue item for connecting Glonass, with the owner's words and "deferred" |
| linux-first-development | project | yes | decision | the handover's strategy section, or a project doc |
| main-session-share-trend | project | yes | decision | docs beside `relay report` |
| relay-cost-calibration | project | no | decision | the calibration record under `$RELAY_HOME` / docs |
| relay-no-consumers-speed-first | project | yes | decision | project doc (strategy) |
| relay-not-published | project | yes | decision | project doc (strategy) |
| relay-plugins-load-from-folder | project | yes | decision | becomes false under the launcher (`--plugin-dir`); delete when it lands |
| taste-means-judgement | user | no | **decision [rev 4]** | body re-read: it records the 24 Oct memory decision ("Memory = raw notes (kept, managed, in git)", also in item `relay-as-a-portable-tool-...`) and "reserve the name taste" (a project doc); its one working rule ("when the owner names a broad concept with one example, ask whether the example is the whole of it") goes to Working with me |
| owner-billing-subscription | user | no | **owner fact [rev 4]** | body re-read: "subscription with usage limits; relay's dollar figures are notional"; the registry item lists the subscription among the owner's facts, so `~/.relay` |
| owner-manifesto-ai-development | user | yes | personal | body re-read: the owner's post-release plans, verbatim; stays a note |
| (MEMORY.md, the index) | - | - | - | derived at every start (5.10) |

**[rev 4] Totals:** 14 in rules (deleted), 7 shared rules, 4 relay rules, 9 decisions (one deleted when the launcher lands), 1
owner fact, 1 personal. So 35 leave the notes: 14 deleted, 20 moved into git (7 + 4 + 9), 1 into `~/.relay`; 1 stays a note.
The classes rest on the description lines plus the bodies of the three notes revision 3 called personal; the move re-reads every
note before deleting it.

### 3.4 The shell function, tested today [rev 4]

The function of section 5.1 was run in the scratchpad with a fake `claude` (a script that prints its arguments and a sha256 of
its environment, never the values, and exits 7) and a fake `relay`, under `zsh -f` and `bash --noprofile --norc`; each command
ran once directly (`command claude`) and once through the function. Three folders: a git repository with no relay files; a
folder holding a `.relay/` folder, like `~/.relay` (to check it is not mistaken for a project); a folder two levels inside a
repository that has `.claude/kit.toml`.

| Folder | zsh | bash |
|---|---|---|
| repository without relay | same arguments `['-p', 'x y', '', '--flag']`, same environment hash, exit 7 | same |
| folder with a `.relay/` folder | same, exit 7 | same |
| inside a relay project, two levels down | the launcher ran with the arguments unchanged; its exit code came back | same |

That is the proof that `claude` outside relay behaves exactly as before: the same program gets the same arguments (an empty one
included), the same environment and the same exit code. Cost: free. Found while testing: `~/.relay` is a folder named `.relay`
in the home folder, so "a folder with `.relay/`" cannot be the sign of a relay project, or every folder under the home folder
would count; the function looks for `.claude/kit.toml` only, which every `relay setup` writes. The test goes into the build as a
unit test (5.3).

## 4. How leading tools solve it

- **CI runners (Woodpecker, GitHub Actions, GitLab CI).** The pipeline file is in the repository; the runner starts a pinned
  image with no user state; secrets are named inputs. GitHub separates `pull_request` from `pull_request_target` (the base
  branch's workflow, trusted), so a change cannot weaken the checks that judge it. relay needs the same for its merge guard (5.5).
- **Dev containers.** The repository names the image and setup steps; the editor attaches. This is the shape of A.
- **mise, asdf, direnv, Nix devshells.** The repository pins tool versions; a shell hook activates them when you enter the
  folder, so you keep typing the same commands. A shell started some other way does not get them, and these tools warn rather
  than strip the user's global tools. This is how B2 enters (a shell function) and how it treats a session that bypasses it.
  **[rev 4]** They also show the install shape: direnv and mise ask the person to add one line to `~/.zshrc` or `~/.bashrc`
  (or `config.fish`), one per shell, and conda writes a block between `# >>> conda initialize >>>` marker lines and removes it with
  `conda init --reverse`. relay's install follows conda's shape (5.1).
- **pre-commit.** Each hook repository is pinned by `rev:` and cached per revision: the tool always runs a copy identified by a
  commit, the model for "relay's copy".
- **Rules and memory** (from their documentation, not measured here):
  - *Claude Code*: a layered set of rule files, all put into one text: admin policy, the user's `~/.claude/CLAUDE.md`, the
    project's `CLAUDE.md` and `.claude/rules/*.md` (committed), then `CLAUDE.local.md` (private). Nothing resolves a
    contradiction; the model reads all of them. Auto memory is per user, per machine, per repository path, never committed, and
    can be pointed elsewhere with `autoMemoryDirectory` (p7).
  - *Codex (OpenAI)*: `AGENTS.md` files, a global one in the user folder and one per folder in the repository, the closer one
    read later so it wins on conflict; no automatic memory.
  - *Cursor*: project rules in `.cursor/rules/*.mdc` (committed), user rules in the app's settings (synced with the account),
    "memories" learned from chats kept per user on Cursor's side, not in the repository.
  - *Aider*: a conventions file committed and named in `.aider.conf.yml`; no memory.
  The common pattern: durable rules are committed files of the project; what a tool learns about one person stays with that
  person; on conflict the closer (project) text is expected to win. relay's guest line (5.9) follows it. **[rev 4]** On memory
  the owner's pick (5.10) goes past these tools: they keep learned notes with the person (Cursor's account, Claude Code's user
  folder), none puts them in the repository. That is the price named in 5.10's critique, and also why the leading tools do not
  get "same notes on every machine" except through an account sync relay does not have.
- **Claude Code's switches.** `--setting-sources`, `--plugin-dir`, `--settings`, `--strict-mcp-config`, `--append-system-prompt`;
  `--bare` is out (it skips hooks and reads only an API key). `claude plugin eval` has none of the first three.
- **relay already does this in one place.** `relay bench` builds its command from `--plugin-dir`, `--agents`,
  `--append-system-prompt` and `--model` (lib/relay_bench.py:505-535). Its `--isolate` (fresh config folder) is broken on this
  Mac (p4).

## 5. Approaches to the session

| | 0. Do nothing | B1. Project files only | **B2. Project-only settings builder (recommended)** | A. Container per change |
|---|---|---|---|---|
| How a session starts | `claude` | `claude` | `claude` (a shell function calls the launcher in a relay project); the gate's own Claude Code calls use the same builder | the launcher inside an image, per change |
| User rules, memory, old agents, user skills | all load | all still load (p3) | user rules, agents, skills excluded (p6, q1, q3); memory from the project's git (5.10) | absent |
| Project's own rules, skills, agents, hooks | load | load | load (q1-q4) | load |
| Plugins come from | main checkout via user marketplace | project marketplace entry (absolute path) | `--plugin-dir` of relay's copy | the image's copy of relay |
| Sign-in | keychain | keychain | keychain (p6) | a token as a named input |
| Pieces of 3.2 still global | 23 of 26 | about 15 | 9 named inputs + 3 machine | 8 named inputs (memory off) |
| Build size (agent minutes, not measured) | 0 | ~45 | **[rev 4]** ~455 with memory M2, ~385 with M1 (section 9) | B2 plus the VPS/container work already queued |
| What it loses | the item's goal | the goal for rules, memory, agents, skills | `theme` unless passed through; user skills; a session started some other way stays global (told so at its start) | the front and landing still on the host (decided 27 Oct) |

B1 is cheaper but leaves the four pieces that differ from a clean run: rules, memory, agents and skills. A without B2 means
either a container with no plugins (no hooks, no merge guard) or `~/.claude` copied into the image. The steps run 0 -> B2 -> A.

The owner asked (round 2) whether this is "the first step to using only relay for relay". Yes in one sense: after B2 a relay
session is made only of relay's copy plus the project's files plus named inputs, which is what a container needs (A). It does not
make relay use only itself: it uses Claude Code as before and keeps every file the project has.

### 5.1 B2 in detail: what one run is made of

A run = the project's commit + relay's copy (its commit, dirty mark and content hash) + the profile + the owner's settings + the
named inputs. One library, `lib/relay_session.py`, turns these into the extra arguments for any Claude Code call relay makes:

    claude --setting-sources project,local
           --plugin-dir <relay copy>/plugins/<p>      (one per relay plugin the project's .claude/settings.json turns on)
           --settings <git common dir>/relay/run-<pid>.json
           <the caller's own arguments>

**What the launcher does at each start, in order:**

1. **[rev 4] Decide whether this call is a session.** Claude Code's subcommands (`claude mcp list`, `claude plugin install`,
   `claude update`) manage the user's own install and go to the real program unchanged. The launcher takes the list from the
   "Commands:" part of `claude --help` of the installed version, kept in `$RELAY_HOME` per version (read once per new version,
   so an auto-update brings its new commands with it; today's list: `agents attach auth auto-mode doctor gateway import install
   logs mcp plugin purge respawn rm setup-token stop ultrareview update`, plus aliases). It looks at the first word that is not an
   option and not the value of an option that takes one (also read from `--help`: `--model <model>` takes one, `--debug` does
   not). So `claude --debug mcp list` goes straight through, and `claude -p "mcp"` is a session (its "mcp" is the value of
   `-p`). If `--help` cannot be read, every call is treated as a session and doctor says the list could not be read.
2. **[rev 4] Clear old run files.** Each run settings file is named with the launcher's process id. Every start deletes the files
   whose process is no longer running; a running session's file is never deleted.
3. **Write the run settings file** `<git common dir>/relay/run-<pid>.json`, by the launcher's own Python (not by a tool call, so
   guard-main never sees it). It lives inside `.git`, so it is never committed. It holds:
   - `model`, `modelSettings.<model>.effortLevel`, `permissions.defaultMode`, `autoCompactWindow`, `switchModelsOnFlag`,
     `skipWorkflowUsageWarning`, and `env`, from the profile's `[session]`;
   - `claudeMdExcludes: [<CLAUDE_CONFIG_DIR or ~/.claude>/CLAUDE.md]`;
   - memory: **[rev 4]** a front session gets `autoMemoryDirectory` pointed at the project's memory staging folder (5.10), or
     Claude Code's own folder when the project's `kit.toml` says `[memory] local = true`; every other call (gate, bench,
     container) gets `autoMemoryEnabled: false`;
   - the allowlisted look keys from the user file (5.4).
4. **Write the rule text** (below).
5. **[rev 4] Prepare memory** (5.10): land any note this machine wrote that did not land, copy the project's notes from the
   default branch into the staging folder, and derive the index `MEMORY.md` from the notes.
6. Set `RELAY_SESSION=<run id>` in the session's environment (the bypass warning reads it) and start Claude Code with the
   arguments above.

`--setting-sources project,local` keeps the project's `.claude/settings.json` and `.claude/settings.local.json`: the project's
hooks, permissions and plugin switches apply (q3).

**The rule text is written at every start, not at sync.** **[rev 4]** It is built from the three homes (5.11), in this order:
the guest line (`rules/guest.md`, a default in relay's repository); relay's shared rules and principles (relay's `rules/`, the
same for every relay project); the shared rules this project opts into (its `.claude/kit.toml`, `[rules] load = [...]`, for
example `openspec` or `product-work`); the owner's facts that rules use (`~/.relay`: the native language line); then, when needed,
an `@AGENTS.md` import (section 7 item 11). The launcher writes it into the project's `CLAUDE.local.md` at the main checkout's
root, by an atomic rename (the file is whole old or whole new, never half). The file is git-excluded, so the tree stays clean. A
session in a task worktree reads it by Claude Code's walk up the folders (measured in revision 2). When the project already has
a `CLAUDE.local.md` without relay's marker (written by a person), the launcher keeps every line of it and writes its text as a
marker block at the end (section 7 item 10). `relay sync` stops writing `CLAUDE.local.md`; the launcher is its one writer. The
rule text's sha256 is a fingerprint line. Cost: a session that bypasses the launcher in a relay project loads the shared rules
twice (about 4.7k tokens more at bytes/4, not measured as tokens); it is warned at its start (5.3).

**[rev 4] When `CLAUDE.local.md` is tracked by git** (the project commits it; `git ls-files --error-unmatch CLAUDE.local.md`
succeeds), git's exclude list has no effect, so writing it would dirty the tree at every start. The launcher then does not touch
the file; it passes relay's text with `--append-system-prompt` and prints one line at start: "this project commits
CLAUDE.local.md, so relay's rules are given to this session directly; agents this session starts do not get them; to give them,
stop committing the file (`git rm --cached CLAUDE.local.md`) or ask the project's owner". No refusal. Why not use
`--append-system-prompt` for every project: subagents (relay's workers, reviewers) read the CLAUDE.md files but not the parent's
added system prompt (not measured; the builder checks it first, free with a fake agent), and text in the system prompt weighs more
than the project's own `CLAUDE.md`, which is the opposite of "the project's setting wins". No project relay knows commits the file
today (ALIX's is excluded: `.git/info/exclude` line 19).

**[rev 4] The shell function, verbatim.** `relay install` writes this block into `~/.zshrc` and `~/.bashrc` (each one that
exists, and always the startup file of the shell named in `$SHELL`), written as a temporary file renamed into place:

```sh
# >>> relay: claude goes through relay's launcher in relay projects >>>
# Written by `relay install`; `relay install --remove` deletes this block.
claude() {
  _relay_d=$PWD
  while :; do
    if [ -f "$_relay_d/.claude/kit.toml" ] && command -v relay >/dev/null 2>&1; then
      unset _relay_d
      relay session -- "$@"
      return
    fi
    if [ -e "$_relay_d/.git" ] || [ -z "$_relay_d" ] || [ "$_relay_d" = / ]; then
      break
    fi
    _relay_d=${_relay_d%/*}
  done
  unset _relay_d
  command claude "$@"
}
# <<< relay: claude goes through relay's launcher in relay projects <<<
```

How it reads: starting in the current folder and going up, it looks for `.claude/kit.toml` (every `relay setup` writes it) and
stops at the folder that holds `.git` (the repository's root, or a worktree's root). Found, and `relay` is installed: the call goes
to `relay session`, which applies step 1 above. Not found: `command claude "$@"` runs the real program exactly as typed (tested,
section 3.4). The function lives in interactive shells only: scripts, IDEs and the desktop app never see it, and relay's own
calls (the gate, bench) use the builder directly. A second `relay install` replaces the block in place, so each file holds one.
`relay install --remove` deletes the block from every file that holds it and says which files it changed; deleting the lines by
hand does the same. Other shells (fish, nushell) are not written; install says so and prints the block for the person to adapt.
Doctor checks that the block is present in the startup file of `$SHELL`.

### 5.2 Every Claude Code call relay makes

| Call | Where | Today | After B2 |
|---|---|---|---|
| Interactive session | the owner's `claude` | user settings, rules, memory, agents | launcher, builder arguments |
| hooks-live (full gate only) | `tests/hooks_live.py:80-81`, from `lib/relay_ci.py:306-319` | project-only switches, but the user rules file still loads (p3) | builder arguments: user rules excluded, memory off |
| plugin validate | `lib/relay_ci.py` | no model call | unchanged |
| plugin evals (paid record step) | `lib/relay_ci.py:416`, `claude plugin eval` | user settings in full | no switch exists; named input: the user rules file's sha256 and settings keys' hash recorded in the eval record; never in a container |
| bench | `lib/relay_bench.py:505-541` | user rules and memory load unless `--isolate`, which loses sign-in (p4) | builder arguments by default; `--isolate` becomes the builder's arguments |

The gate log (`lib/relay_gate.py`) records the fingerprint of each gate, one line per model step, so a Mac gate and a container
gate of one commit can be compared line by line.

### 5.3 Never and only, each with its test

- *A launcher or gate session in a relay project never loads `~/.claude/CLAUDE.md`.* Unit test: the generated settings contain
  `claudeMdExcludes` with the user path, for the interactive caller, hooks-live and bench (a fake `claude` records the arguments).
  Live (paid step, about $0.003): the p6 question answers "no".
- *A gate, bench or container run never loads memory.* Unit test: their settings contain `autoMemoryEnabled: false`.
- *Plugins come only from relay's copy in a launcher session.* Unit test with a fake `claude`: one `--plugin-dir` per enabled
  relay plugin, all under the copy. Live: the start message's plugin paths all lie under the copy.
- *A launcher session never drops a file the project has.* Live test in the paid step (q1 + q3 + q4 repeated, about $0.006): a
  fixture project with `CLAUDE.md`, `AGENTS.md`, `.claude/rules`, a hand-written `CLAUDE.local.md`, a skill, an agent and a hook
  answers with all four code words, lists the skill and the agent, and the hook's file appears.
- *The launcher never removes a line a person wrote in `CLAUDE.local.md`.* Unit test: a hand-written file plus two launcher
  starts keeps the person's lines byte for byte and holds exactly one relay block.
- **[rev 4]** *A launcher start never leaves the main checkout dirty.* Three fixture repositories, `git status --porcelain`
  empty after a start in each: no `CLAUDE.local.md` (file created, git-excluded); an untracked hand-written one (kept, one
  block); a committed one (not touched; the fake `claude` received `--append-system-prompt` holding the probe word).
- **[rev 4]** *`claude` outside a relay project is never changed.* Unit test (the 3.4 test, zsh and bash): same arguments,
  environment hash and exit code as `command claude`, in a repository without `kit.toml` and in a folder holding `.relay/`.
- **[rev 4]** *Subcommands are never routed into a session.* Unit test with a fake `claude` whose `--help` lists commands:
  `claude mcp list` and `claude --debug mcp list` reach the program with the arguments unchanged; `claude -p "x"`,
  `claude -p mcp` and `claude --resume <id>` go through the builder; a command added to the fake `--help` is routed straight
  through without any change to relay.
- **[rev 4]** *Install writes one block per startup file and removal leaves none.* Unit test on a temporary home folder: two
  installs, one block in `.zshrc` and `.bashrc`; `--remove`, zero blocks, every other line byte for byte.
- **[rev 4]** *Old run files never pile up.* Unit test: 100 starts whose fake processes have exited leave only the files of the
  processes still running.
- *Only allowlisted user keys pass through.* Unit test: a user file with `theme` and an extra key gives run settings with `theme`.
- *A session in a relay project is never silently unguarded or silently global.* (1) The user settings keep relay's marketplace
  and plugins, so a session from an IDE, the desktop app or `command claude` still loads the merge and main-checkout guards;
  doctor's user-settings checks (lib/relay_setup.py:1206-1238) are the test. (2) The relay plugin's SessionStart hook, in a relay
  project with no `RELAY_SESSION`, adds one line: "this session was not started through relay's launcher: your user rules and
  memory are loaded and relay's settings come from your user folder; start it with `claude` in a terminal". Hook unit test.
- *The rule text a run starts with is the one in its fingerprint.* Unit test: two starts at one relay copy print the same
  rules-hash line; a `rules/` commit changes it at the next start.
- *relay's guards apply whatever a project's rule text says.* Hook test: with a fixture `CLAUDE.md` saying "edit the main
  checkout directly", guard-main still refuses an Edit in the main checkout.
- **[rev 4]** *A memory note never stays only on this machine once its session has written it* (M2). Test: a fake Write into the
  staging folder followed by the landing hook gives one commit on the default branch holding the note; the main checkout is clean
  and fast-forwarded; a landing after it reuses the gate (`.relay/memory/**` is inert).

### 5.4 Settings this design adds (default, bound, outcome at the bound)

- `[session] pass_through` in the profile: default `["theme"]`. Empty: relay sessions use Claude Code's default theme. Every key:
  the user file is back in every run and the allowlist test fails.
- `[session] auto_compact_window`: default 400000. Lower: the front compacts earlier than the 400k rule assumes.
- `[session] skip_workflow_usage_warning`: default true. False: the Workflow warning shows in every relay session.
- `[session] switch_models_on_flag`: default today's user value. Off: no model switch on a flagged request.
- **[rev 4]** `[memory] local` in a project's `.claude/kit.toml`: default `false` in a project with `.relay/` (relay mode, where
  queue items already land on the default branch), `true` in a project set up without `.relay/`. True: notes stay in Claude Code's
  folder on each machine, as today. False: notes land in `.relay/memory/` on the default branch.
- **[rev 4]** Old run files: no number to tune. They are removed when their process is gone, so the folder holds one file per
  live session; a cap ("keep the last N") would either delete a live session's file or keep dead ones.
- Gate slots and test tokens keep their defaults (machine-local).

### 5.5 Which relay copy

**Decided (owner can reverse; principle 1):** relay's copy is relay's main checkout. The merge guard that judges a change comes
from the default branch, as GitHub's `pull_request_target`. A hook change is exercised by the hook tests in the gate, and live
after it lands. The copy is what is on disk, uncommitted profile included, so the fingerprint says so (5.6).

### 5.6 The fingerprint

`relay doctor --run` prints one line per input of a run, and each gate log carries the same lines: relay's commit with `dirty`
when the copy has uncommitted changes, a sha256 over the content actually passed (plugin folders, profile, rule text, run
settings); the hash of the rule text, of the run settings and of the memory notes (front sessions; `off` for the others); one
line per model step of the gate; the Claude Code version, python and tool versions, the sign-in kind (never the value), the
locale, whether admin settings exist. The launcher warns at start when relay's copy is dirty; it does not refuse. Acceptance
test: the same command on this Mac (clean copy) and in the clean image differs only on lines marked as inputs; it runs in the
per-wave paid step.

### 5.7 Claude Code version

**Decided (owner can reverse; speed first):** not pinned on the host, recorded per run; pinned in the image.

### 5.8 Where a project author puts project-only rules and skills

The owner asked (round 3): "как я могу кастомизировать правила для конкретного проекта, допустим хочу включить правило - node
под запретом, только relay ... или ... skill для использования linter". The answer is Claude Code's own project files, which
the launcher keeps (q1-q4). relay adds no format of its own for this.

| What you want | File you edit (committed in that project) | Loaded by | Probe |
|---|---|---|---|
| A rule for this project only ("node is banned, bun only" for relay) | `<project>/.claude/rules/<topic>.md`, one file per rule; or a line in `<project>/CLAUDE.md` | Claude Code, every session in that project | q1 (LYNX, HERON) |
| A skill for this project ("how to run our linter") | `<project>/.claude/skills/<name>/SKILL.md` | Claude Code; offered when the request matches its description | q1 (`probe-lint`) |
| An agent for this project | `<project>/.claude/agents/<name>.md` | Claude Code | q3 |
| A hook or a permission for this project | `<project>/.claude/settings.json` | Claude Code | q3 (hook ran) |
| Rules shared with other tools (Codex, Cursor) | `<project>/AGENTS.md` | Claude Code directly, or by the import line relay adds (section 7 item 11) | q2, q4 |
| relay's knobs for this project (lanes, gate command, routing guard, memory) | `<project>/.claude/kit.toml` | relay's code | existing |
| **[rev 4]** One of relay's shared rules this project opts into (OpenSpec, product work) | `<project>/.claude/kit.toml`, `[rules] load = [...]` | the launcher's rule text | moved from projects.toml by the registry item |

Live examples, as the build would make them:
- relay itself: a new committed file `~/relay/.claude/rules/tools.md` with "Node is not used in relay: JavaScript and TypeScript
  tooling runs on bun; install tools with their official installers, as their own instructions say." It replaces the memory
  note `bun-not-node`. Other projects are untouched (the owner: "не общее правило, а именно для relay").
- the linter project (`~/go/src/go.amidman.dev/linter`): a committed `.claude/skills/lint/SKILL.md` whose description says when
  to use it ("run the linter on changed Go files before a commit") and whose body gives the command.
- relay's `rules/python.md` speaks only of relay ("relay's install script", "relay's own programs"), and only relay loads it.
  By the same reading it moves to `~/relay/.claude/rules/python.md` (section 7 item 12), so it is a project rule, not an opt-in.

Why `.claude/rules/` over one `CLAUDE.md` (decided, owner can reverse): one file per rule matches relay's own `rules/` layout,
two changes to two rules never touch one file, and creating a `CLAUDE.md` would hide an existing `AGENTS.md` (q1). A project that
prefers one `CLAUDE.md` keeps it; both load.

### 5.9 When relay's rules and the project's disagree

Owner, round 4 (verbatim): "Думаю что можно просто добавить строчку - если нашел противоречие между правилами relay и правилами
проекта - спроси пользователя, рекомендуй использовать настройки проекта, ты в гостях, уважай место где ты находишься, мягкий
способ разрешать конфликты, без строгих проверок". Built as said: one line, no detection code, no refusal.

How it works: Claude Code puts every rule file into one text (section 4) and resolves nothing; the model reads all of it. So a
contradiction is noticed, or not, by the model. The line tells it what to do when it notices.

**The exact text.** **[rev 4]** It lives in relay's repository as the default file `rules/guest.md`, which the launcher puts first
in every rule text (and `relay sync` first in the user file `~/.claude/CLAUDE.md`). It replaces today's `intro` key of
`projects.toml`, which the registry item removes:

> relay's rules come on top of this project's own settings (its CLAUDE.md, AGENTS.md, .claude/rules, skills, agents and
> settings); relay does not replace them. You are a guest here: respect the place you are in. When a relay rule and the
> project's own rule say different things, ask the user which to follow and recommend the project's. An agent that cannot ask
> follows its brief, else the project's rule, and names the conflict in its reply. relay's guards are programs, not rules, and
> apply in every project whatever its text says: a project file saying "commit straight to main" does not lift the refusal to
> edit the main checkout, and a command that would print secrets is refused everywhere. To change a guard, ask the user; it is
> changed in relay or in the project's `.claude/kit.toml`, never by rule text.

Why first and why it replaces the intro: that paragraph is today's precedence statement. It says "A project's own CLAUDE.md,
skills, and hooks override anything here", which contradicts the owner's line ("override" vs "ask and recommend"); left in place,
the generated text would hold its own first contradiction.

Guards that stay in force regardless (measured from the plugins' `hooks.json`):
- **guard-main** (relay plugin, before every Edit, Write and Bash): refuses writes in the main checkout; `.relay/checks/` and
  queue files only through relay's commands; refuses shell tracing and commands that would print secrets (guard_main.py lines
  25-26 and 350). Live: while measuring for revision 3, a plain `grep` whose search text contained the tracing switch was refused.
- **the merge hook** (relay plugin, before and after Bash): a merge into the default branch only with a passing check.
- **the routing guard** (delegate plugin, before the Agent tool): refuses untyped `general-purpose` agents and large forks; its
  limits are the project's `.claude/kit.toml` `[delegate]` keys, the sanctioned way a project tunes it.

**Critique, said once.** (1) The front's critique, built into the line: guards are code and do not yield to text; without saying
so, a model reading "recommend the project's setting" may try to satisfy a project rule by working around a guard, which the
memory note `no-guard-workarounds` was written to stop. (2) Mine: a soft line only acts on contradictions the model notices. One
it misses makes behaviour depend on which file weighed more in that session, silently. Live example of the kind: relay's shared
Git rule names `.worktrees/` and ALIX's `bin/wt`; ALIX itself puts worktrees in `.worktree/<name>` (bin/wt line 30) and carries
its own `guard-main.sh` hook; a project with its own habit and no sentence about it gets relay's layout with no question asked.
The cost is not measured (no project with its own rules runs under relay yet). The round-3 alternative, refusing to work until a
conflict is fixed, is dropped by the owner's round 4; it would have needed a detector that cannot read meaning (principle 5).
Built as the owner said.

### 5.10 Memory: where it lives, and several machines [rev 4: rewritten]

The owner asked (round 3): "Что будет в этой memory, как это сочетается с тем что изменения могут идти с нескольких машин", and
(round 4) "Значит ли это что вопрос исчерпан, до пересмотра".

**The owner already chose, on 24 Oct, and revision 3 missed it.** Queue item `relay-as-a-portable-tool-project-data-out-of-rel`,
`why`, verbatim: "заменять память не стоит - лучше научиться ей управлять, почему мы не можем хранить память о всех проектах в
самих проектах, сохранять их в гит и легко переносить между машинами"; "память лишь записывает, из памяти в дальнейшем мы
собираем функциональные компоненты системы, каким может стать "вкус", память это заметки, claude уже умеет с этим работать, мы
лишь управляем"; the goal: "моя цель - свежая копия relay + <project> работает одинаково на всех машинах". The front's proposal
the owner accepted that day: "A project's Claude memory (raw notes): a folder in the project's own repo ... A note written
mid-session must land in git at once without dirtying the main checkout (like `relay queue` items land) and the main-checkout
guard must allow it. A project whose repo is shared can set "memory local" (stays in ~/.claude)." This item's own note of
30 Oct 11:00 moved the front's recommendation to the same place.

What is in memory today: section 3.3. Most of it is not memory in the personal sense: 14 notes repeat relay's rules, 20 are rules
or decisions that never reached git, 1 is an owner fact, 1 is the owner's plans.

How today's memory meets several machines: the folder is keyed to the repository's path on one machine and never synced. A
second machine (the owner's Linux VMs, note `linux-first-development`, 29 Oct) starts with none, so a front there lacks the 11
rules that live only in memory: it would, for example, reach for Node in relay and for Docker. If two machines shared one folder,
every save rewrites the one index file `MEMORY.md`, so two machines saving notes the same day would conflict on that file even
when the notes differ.

**Can the index be derived: yes.** Every note has `name` and `description` lines (36 of 36). Today the index also acts as a
selection (15 notes left out, 11 of them retired duplicates), so regenerating it would bring the duplicates back; once they are
deleted, the index is all the notes and the launcher writes it at every start. It is then never committed: each machine builds
its own, so it never conflicts.

**M2 as accepted, and how it is built.** Claude Code writes notes through its own file tools into the folder that
`autoMemoryDirectory` names (p7: the launcher's `--settings` can name any folder). Two ways to meet "a folder in the project, the
main checkout clean":
- *Directly into the checkout* (`<main checkout>/.relay/memory/`): the write itself makes the main checkout dirty until it lands;
  guard-main must open a hole for that folder; and git refuses to fast-forward over an untracked or changed file of the same
  name, so the landing must first remove the written file. Three moving parts in the most guarded folder.
- *Through a staging folder* (chosen, owner can reverse): `autoMemoryDirectory` names `$RELAY_HOME/memory/<project>/`, outside
  every checkout. The committed copy is `.relay/memory/<name>.md` on the default branch. A hook after each Write or Edit into the
  staging folder lands that one file on the default branch with the queue's landing engine (a temporary index, a commit, the
  main checkout fast-forwarded: `lib/relay_queue.py` `land_files`, the way `relay queue` lands items today). At each start the
  launcher first lands any staged note that differs from the default branch and is newer than its last commit (a write whose hook
  did not run, for example after a crash), then copies the default branch's notes into staging, then derives `MEMORY.md`. guard-
  main needs no hole; it refuses direct writes into `.relay/memory/` as it does for `.relay/queue/`.
- `.relay/memory/**` joins the inert paths (`lib/relay_inert.py`: today `docs/handover.md` and `.relay/queue|checks|changes`), so
  a landing after a memory note reuses the gate instead of running it again (`lib/relay_land.py:392`).
- A shared repository, or a project set up without `.relay/`, keeps `[memory] local = true` (5.4): notes stay in Claude Code's
  folder on that machine, as today.
- Deleting a note: by a normal change in a worktree, like any file. The staging copy would otherwise bring it back. Rare:
  measured, no note was ever deleted from relay's folder (the 11 retired ones are all still there).

Volume, measured: 37 notes were written in 10 days (21-30 Oct), about 4 a day; edits of notes are not measured. Since 23 Oct (7 days)
master took 3,509 commits, 1,291 of them queue commits; memory would add well under 1% more.

| | M0. Do nothing | M1. Rules out of memory, rest per machine | **M2. Notes in the project's git (owner, 24 Oct; recommended)** | M3. A personal notes repository |
|---|---|---|---|---|
| What happens | 36 notes stay per machine | the 20 rules and decisions go into git, 14 duplicates are deleted, 1 owner fact to `~/.relay`; new notes stay per machine | M1's clean-up first, then every note lives in `.relay/memory/` and each new note lands there at once (above) | `autoMemoryDirectory` points at `~/notes/<project>`, a git repository of the owner's, synced by a relay command |
| A second machine or a container gets | nothing | every rule and decision moved so far; not later notes | every note, whenever the default branch reaches it | every note, if that repository is cloned there |
| Personal notes in a work repository | no | no | yes, forever (today: 1 note, the manifesto) | no |
| Conflicts between machines | none (nothing shared) | none (git, separate files) | only when one note is edited on two machines; index derived | the same as M2 |
| New parts | none | none: text moves and deletions | a start step, a landing hook, an inert path, a switch | a sync command, a second repository |
| Build (agent minutes, not measured) | 0 | about 30 | about 100 (30 clean-up + 70) | about 75 (30 clean-up + 45) |
| What it loses | the rules on any other machine | every later note lives on one machine until someone moves it | clean project history; the line between person and project | one more repository to keep and sync |

**Critique of the owner's pick, said once.** (1) Personal notes enter the work repository's history for good. Today that is one
note (the manifesto; the subscription fact goes to `~/.relay`), and relay is not published (owner, 28 Oct); the cost appears on
the day a repository is published or shared: its history then holds whatever personal notes were written in it, and removing
them means rewriting history. The leading tools all keep learned notes with the person, not the repository (section 4). (2) It
is the only option with new parts: about 70 agent minutes more than M1. (3) A note lands without review, as a queue item does.

**Why the recommendation moved from M1 to M2** (evidence, not the owner's push): (a) measured drift: in 10 days 20 rules and
decisions piled up in memory and reached no other machine; M1 cleans them once but keeps the cause, so every later note repeats
it, and a second machine is near (Linux, 29 Oct); (b) the parts are smaller than revision 3 assumed: p7 lets the launcher point
memory anywhere without project settings, and the landing engine and the inert list already exist. Against them, M1's one gain
is no new parts and no personal notes in git, and the second cost is one note today.

The owner's round-4 question, "is the question closed until revisited": after M2, yes: notes travel with the project. What stays
open is how branches meet between machines, which the owner deferred on 29 Oct ("Пока это нигде не хранится отложим вопрос
касательно синхронизации, но сейчас я склоняюсь к репозиторию на github"); until then a new machine gets the notes as of its
clone. After M1 alone it is closed only for the 20 notes moved.

### 5.11 Where data lives: the three homes [rev 4]

The owner's round 5: "я немного запутался касательно того где и как лежат данные, память, как мы это будем разделять ... визуально
это продемонстрировать". One picture; file names marked *(proposed)* are the registry item's to settle.

```
 relay's repository (~/relay, git)               SHIPS DEFAULTS ONLY; the same on every machine
 ├── rules/*.md            shared rules and principles; rules/guest.md (the guest line) comes first
 ├── profiles/*.toml       models, effort, [session] keys
 └── plugins/              guards (hooks), relay's skills and agents
     (projects.toml is retired by the registry item: its owner facts go to ~/.relay,
      its per-project lists go into each project's kit.toml)

 ~/.relay  (this machine only, never in git)    THE OWNER AND THE MACHINE
 ├── owner.toml (proposed)       native language, paid cap per day, subscription; asked once per machine
 ├── setups.jsonl (proposed)     one dated line per `relay setup` run -> the machine's project list (derived)
 ├── memory/<project>/           staging copy Claude Code writes notes into (M2); rebuilt from git at each start
 ├── claude-help/<version>       Claude Code's command list, read once per version (5.1 step 1)
 └── ledger/, gate-slots/, test-tokens/, test-times/, bench/ ...   as today

 <project> (its own git; travels to every machine with the project)     EVERYTHING ABOUT THIS PROJECT
 ├── CLAUDE.md, AGENTS.md, .claude/rules/, .claude/skills/,
 │   .claude/agents/, .claude/settings.json          the project's own; relay reads them, never rewrites them
 ├── .claude/kit.toml        relay's knobs: [gate], [delegate], [front] lanes, [rules] load, [memory] local
 ├── .relay/queue/, checks/, changes/                relay's records (as today)
 ├── .relay/memory/*.md      the project's notes (M2); MEMORY.md is not committed
 ├── CLAUDE.local.md         relay's rule text, written at each start, git-excluded (never committed)
 └── .git/relay/run-<pid>.json   one per live session, inside .git, never committed

 ~/.claude (Claude Code's user folder)           THE PERSON'S OWN; relay sessions read only the sign-in from it
 ├── sign-in (keychain on macOS)                     used by every session
 ├── settings.json      relay marketplace + 4 plugins: for sessions not started by the launcher
 ├── CLAUDE.md          the person's lines + relay's marker block: for folders outside relay projects
 ├── skills/, agents/   personal; not loaded in launcher sessions
 └── projects/<path>/memory/   still used in folders outside relay projects and where [memory] local = true
```

Who writes what: a person or an agent in a worktree writes the project's files (committed by a normal change); `relay queue`
and the landing hook write `.relay/queue` and `.relay/memory` on the default branch; the launcher writes `CLAUDE.local.md`, the
run file and the staging folder; `relay install` writes `~/.claude` and the shell startup files; `relay setup` writes the
project's first files and one line in `~/.relay`.

## 6. Scenarios [rev 4]

The owner's round 5 asked for three scenarios and, in each, how behaviour, stored files, interruption and several actors change,
and whether the installer edits the shell. Each scenario has its table; interruption (6.4), several actors (6.5) and folders
outside relay (6.6) work the same way in all three and are given once. "Install" is `relay install` (once per machine); "setup" is
`relay setup <repo>` (once per project). Names marked *(proposed)* are the registry item's to settle.

### 6.1 A new machine and a git repository

Example: a fresh Linux VM (the owner's plan of 29 Oct) with Claude Code installed and signed in, login shell bash, and a repository
holding only code, say the linter project cloned there.

| | Before | After install and setup |
|---|---|---|
| `~/.claude` | the sign-in; maybe an empty `settings.json` | `settings.json`: relay's marketplace and its 4 plugins; `CLAUDE.md` created holding only relay's marker block (for folders outside relay projects) |
| `~/.relay` | absent | `owner.toml` *(proposed)*: install asks once for native language and paid cap; `setups.jsonl` *(proposed)*: one dated line for this repository; empty machine folders |
| `~/.bashrc`, `~/.zshrc` | the system's default `~/.bashrc`; no `~/.zshrc` | the marker block of 5.1 in `~/.bashrc`; `~/.zshrc` is not created |
| `CLAUDE.md` | absent | a skeleton (what the project is, its commands), written only because none existed; to be filled and committed |
| `AGENTS.md` | absent | absent (were it present, the skeleton would start with `@AGENTS.md`) |
| `.claude/` | absent | `kit.toml` (relay's knobs, `[memory] local = false` with `.relay/`), `settings.json` (relay's plugins on) |
| `.relay/` | absent | `README.md` (turns on the queue and merge checks once on the default branch); later `queue/`, `checks/`, `memory/` |
| `CLAUDE.local.md` | absent | written at the first `claude` start, git-excluded |
| Also written by setup | - | `bin/check`, `bin/ci`, `bin/wt` templates, `docs/handover.md`, `.gitignore` lines; setup lists them as files to commit |
| A session loads | - | the guest line, relay's rules and principles, the native language line from `~/.relay`, the project's `CLAUDE.md`; relay's plugins from `~/relay` |
| Memory is written to | - | the staging folder `~/.relay/memory/<project>/`; each note lands at once in `.relay/memory/` on the default branch |
| Interrupted | - | install or setup stopped half-way: run it again (every step keeps what exists: templates never overwrite, the shell block is replaced in place); a session: 6.4 |
| Several actors | - | one machine, first use: two sessions at once (6.5) |

If the repository is relay itself, cloned onto the VM: its rules, its project rules and (after M2) its notes arrive with the
clone; the VM's front has what the Mac's has, except the owner's settings, asked once.

### 6.2 A machine that already has rules, and a git repository without its own

Example: this Mac. `~/.claude/CLAUDE.md` (18,671 bytes, written by `relay sync`), 3 user skills (grilling, synced, tauri), 2 old
user agents, notes for 22 projects, `~/.relay` with the ledger and gate records, `~/.zshrc` (5,749 bytes) and `~/.bashrc` (5,452
bytes), both without any relay lines (measured: no relay code writes either file today). The repository has code and no Claude
files. A newcomer's machine looks the same except that its `~/.claude/CLAUDE.md` was written by the person.

| | Before | After install and setup |
|---|---|---|
| `~/.claude` | as listed above | `CLAUDE.md`: relay's file is refreshed; **a person's own file keeps every line and gets relay's marker block at its end** (today install moves it aside to `CLAUDE.md.before-relay`, so it stops loading: `lib/relay_rules.py` `write_target`; section 7 item 16 changes that). Skills, agents and notes untouched; doctor names the 2 old relay agents with the command that removes them |
| `~/.relay` | ledger, gate slots, test tokens, bench | the same, plus `owner.toml` *(proposed)* filled from today's `projects.toml` values (not asked again) and one setup line |
| `~/.zshrc`, `~/.bashrc` | no relay lines | the marker block in both (both exist) |
| `CLAUDE.md`, `AGENTS.md`, `.claude/`, `.relay/`, `CLAUDE.local.md` | absent | as in 6.1 |
| A session loads | today: everything in `~/.claude` | in this repository: as 6.1. What the person notices: the user folder's rules, skills ("grill me") and old agents are not there; the native language still is (from `~/.relay`). In every other folder: as before (6.6) |
| Memory is written to | `~/.claude/projects/<path>/memory` | the staging folder, landed into `.relay/memory/`. Notes Claude Code already holds for this folder on this machine are not moved silently: setup prints their count and lands them only when the person says yes |
| Interrupted | - | as 6.1 |
| Several actors | - | 6.5; on this Mac the realistic case is the front plus up to 6 lanes in one project |

### 6.3 A machine that already has rules, and a repository with its own rules

Example, live: ALIX (`~/alix`). It commits a 481-line `CLAUDE.md`, 10 or more skills in `.claude/skills` (`alix-*`, `openspec-*`),
9 agents in `.claude/agents`, its own hooks in `.claude/hooks` (its own `guard-main.sh` among them), and a `.claude/settings.json`
with about 20 allow rules. It has no `AGENTS.md`, no `kit.toml` and no `.relay/`. It also has a stale relay-written
`CLAUDE.local.md` (71 lines, 24 Oct, git-excluded) that nothing updates since ALIX left `projects.toml` (fix item, section 10).

| | Before | After setup (install as in 6.2) |
|---|---|---|
| `CLAUDE.md` | ALIX's 481 lines | unchanged (setup writes one only when none exists: `copy_template` never overwrites) |
| `AGENTS.md` | absent | absent; were it present and not imported by `CLAUDE.md`, relay's rule text would start with `@AGENTS.md` (item 11); ALIX's `CLAUDE.md` itself is never edited |
| `.claude/skills`, `.claude/agents`, `.claude/hooks` | ALIX's | unchanged, and all load (q1, q3) |
| `.claude/settings.json` | ALIX's permissions and hooks | every key kept; relay's plugins added to `enabledPlugins` |
| `.claude/kit.toml` | absent | written; it marks ALIX as a relay project for the shell function |
| `.relay/` | absent | only if the owner chooses relay mode for ALIX (setup's `relay_dir`); then `[memory] local = false` |
| `CLAUDE.local.md` | relay's stale 24 Oct text | at the first start its relay block is rewritten from relay's copy; any lines a person added are kept |
| A session loads | everything in `~/.claude`, ALIX's files, the stale relay text | the guest line, relay's rules, ALIX's `CLAUDE.md`, skills, agents and hooks; **both** guard hooks run (relay's and ALIX's own); either can refuse an action; the stricter one decides |
| A conflict, live | - | relay's Git rule puts worktrees in `.worktrees/`; ALIX's `bin/wt` puts them in `.worktree/<name>`. The guest line: the session asks the owner and recommends ALIX's way |
| Memory is written to | `~/.claude/projects/-Users-amidman-alix/memory` (48 notes) | without `.relay/`: the same folder (`[memory] local = true`), nothing changes. With `.relay/`: staging and `.relay/memory/`; setup asks before landing the 48 |
| Interrupted | - | as 6.1 |
| Several actors | - | 6.5; plus a teammate who clones ALIX without relay: sees `kit.toml`, relay's plugin entries in `settings.json` and, with `.relay/`, the notes; what Claude Code shows them for a plugin whose marketplace they lack is not measured |

### 6.4 When work is interrupted (all scenarios)

| What stops | What is lost | What comes back, and how |
|---|---|---|
| A session is closed or killed mid-change | only what the conversation had not written down (the handover rule covers it) | the worktree's files and commits, the queue item and the handover are on disk and in git; `claude -c` or `claude --resume <id>` goes through the launcher again; the next start deletes the dead run file |
| The launcher is killed during its steps | nothing | `CLAUDE.local.md` is whole (atomic rename); run `claude` again |
| A note was written but its landing failed (the default branch moved, git busy) | nothing | the landing engine retries as `relay queue` does and the session is told; the next start lands the staged note |
| `relay install` or `relay setup` is stopped half-way | nothing | run it again; every write is a rename; one shell block per file |
| The machine is lost | `~/.relay` (owner settings, ledger, gate records), and branches or default-branch commits (queue items, notes) not yet on another machine | rules, project settings and notes come back with any clone that has them; owner settings are asked again; how branches meet between machines is deferred by the owner (29 Oct); with M1 instead of M2, notes not yet moved are lost |

### 6.5 Several actors at once (all scenarios)

| Who | Rules and settings | Memory |
|---|---|---|
| Two sessions on one machine, one project | each start rewrites `CLAUDE.local.md` with the same text from the same copy (atomic rename); if relay's copy changed between the two starts, the earlier session keeps what it loaded and its fingerprint says so; one run file per process | one staging folder per project per machine; each note lands on its own, the landing engine re-reads the head and retries; one note edited by both at once: the later write wins and the earlier one stays in git history |
| Agents in lanes (worktrees) | they read `CLAUDE.local.md` by Claude Code's walk up the folders; they never run the launcher and never write rule files | whether agents started by the front read or write memory is not verified (the builder checks it first); their worktrees never hold memory |
| Two machines | rules, `kit.toml` and project rules are files in git and meet when branches meet; each machine has its own `owner.toml` (doctor shows its values) | notes are files in git and meet when branches meet; `MEMORY.md` is built on each machine, so it never conflicts; one note edited on both machines is a one-file conflict at that point |
| The owner editing by hand | lines outside relay's marker blocks (in `CLAUDE.local.md`, `~/.claude/CLAUDE.md`, the shell startup files) are never touched; lines inside are rewritten at the next start or install, as the marker line says; project rules are edited in a worktree and land as a change | a note edited by hand in the staging folder lands at the next start (newer than its last commit); a note edited in the main checkout's `.relay/memory/` makes the tree dirty, as any edit there does |
| Two people sharing a repository | the guest line and the project's own files, as for any project | `[memory] local = true`: each person's notes stay on their machine |

### 6.6 Folders that do not use relay, and the shell

**Does the installer edit the shell: yes, one marked block** in `~/.zshrc` and `~/.bashrc` (5.1), removed by `relay install
--remove` or by deleting the marked lines. **In a folder that is not a relay project, `claude` behaves exactly as before**: the
function hands the call to the real program with the same arguments, environment and exit code (tested in zsh and bash, 3.4). Two
differences remain visible: `type claude` reports a shell function, and the function checks a few folders before it starts
(a file test per folder up to the repository root).

What install itself changes outside relay projects is a separate matter, and it is not new: today `relay install` already writes
relay's shared rules into `~/.claude/CLAUDE.md` and turns relay's 4 plugins on for the whole user, so a session in any folder
loads relay's rules and relay's hooks (whether guard-main acts in a repository without `.relay/` is not measured here). Revision 3
kept that (section 7 item 6) so a relay project opened from an IDE or the desktop app still has its guards. The one change this
design makes there is that a person's own `~/.claude/CLAUDE.md` is kept instead of moved aside. Whether relay should stay at user
level at all is in "Open for the owner".

## 7. Decided inside the principles (each one the owner can reverse)

1. B2 before A, as the owner's "4. A" and the 27 Oct design say. No `--bare` (it skips hooks).
2. relay's copy is the main checkout as it is on disk, its commit, dirty mark and content hash recorded per run.
3. One settings builder serves every Claude Code call relay makes that takes switches; `claude plugin eval` cannot take them and
   is a named input.
4. The rule text is written by the launcher at every start; the launcher is its one writer; sync keeps only the user file.
5. **[rev 4]** Memory follows the owner's pick of 24 Oct (M2, 5.10) unless the owner changes it in "Open for the owner"; gate,
   bench and container runs have memory off. The launcher writes no note into any checkout.
6. `relay setup --global` keeps writing relay's marketplace, plugins, model, effort and env into the user settings, so a session
   not started by the launcher keeps the guards; those sessions are told so at start (see the open question on user level).
7. Claude Code is recorded, not pinned, on the host; pinned in the image.
8. Pieces 21-23 stay in `$RELAY_HOME`.
9. Account connectors stay, as an input.
10. A hand-written `CLAUDE.local.md` is kept: the launcher writes relay's text as a marker block at its end and never touches the
    person's lines. Today `relay sync` refuses such a file unless `--adopt`; the owner's "relay не отказывается от настроек которые
    пользователь уже имеет" rules that out.
11. When a project has an `AGENTS.md` that its `CLAUDE.md` does not import (relay's existing check `agents_md_loaded`,
    lib/relay_setup.py:703), the launcher's text starts with `@AGENTS.md`. It never edits the project's `CLAUDE.md`.
12. relay's principles load in every relay project (owner, round 4: "свои правила и принципы, которые являются общими для relay").
    `rules/python.md`, which speaks only of relay, moves to relay's own `.claude/rules/python.md`.
13. Grilling stays out of relay (owner, rounds 2-3: like OpenSpec); a project that wants it commits a copy to its `.claude/skills`.
    relay's own repository does not get one unless the owner asks (grilling was invoked in 1 relay session since 1 Oct).
14. Project-only rules go into the project's `.claude/rules/` (5.8); relay invents no format for them.
15. **[rev 4]** Data follows the owner's round-5 "a" (5.11). The registry item `relay-as-a-portable-tool-project-data-out-of-rel`
    lands **before** B2, so B2's readers are written once against the new places (principle 1: B2 depends on it; principle 2: no
    reader written twice). B2 adds no reader of `projects.toml`.
16. **[rev 4]** `relay install` keeps a person's own `~/.claude/CLAUDE.md` and writes relay's text as a marker block at its end,
    instead of moving the file aside. Same rule as item 10, applied to the user folder.
17. **[rev 4]** A committed `CLAUDE.local.md` is never written; relay's text goes in by `--append-system-prompt`, with one line
    saying what that loses (5.1). No refusal (owner, round 4: "без строгих проверок").
18. **[rev 4]** M2 is built through a staging folder outside every checkout, not by writing into the main checkout (5.10): no
    guard hole, no dirty moment, no fast-forward over a written file.
19. **[rev 4]** Claude Code's subcommands are read from its own `--help`, per version, not kept as a list in relay (principle 3:
    what can be derived is not stored).
20. **[rev 4]** `[memory] local` defaults to false in relay mode (`.relay/`), where queue items already land on the default branch,
    and to true elsewhere.
21. **[rev 4]** The shell function's sign of a relay project is `.claude/kit.toml`; it stops at the repository root. `.relay/`
    cannot be the sign: `~/.relay` would make every folder under the home folder a relay project (found while testing, 3.4).

## 8. Critique of the picks

- **The owner: "хочу вообще без глобальных настроек relay и claude".** Zero is not reachable: the sign-in is user state (p4),
  admin settings apply whatever the switches, the Claude Code version is a machine fact, `claude plugin eval` takes no switches.
  The reachable goal is "nothing global that is not named and recorded": 9 inputs.
- **The owner: "3. A" (the Mac re-gates until 3 waves agree with the container).** Given before the 30 Oct answer that the VPS runs
  build-time gates and the Mac only the landing gate; belongs to item `each-change-is-gated-in-a-fresh-container`; does not block
  B2.
- **The owner: "relay keeps every setting the project already has".** Two real costs: relay's `CLAUDE.local.md` becomes a shared
  file when a person already has one (item 10 handles it); a project's `.claude/settings.json` can turn relay's plugins off and
  the launcher honours it, so that project runs without relay's guards. Doctor names it in one line, no refusal.
- **The owner: the soft conflict line.** Section 5.9: it acts only on contradictions the model notices; the front's guard
  critique is built into the line.
- **The owner: grilling out of relay.** I looked and found no weakness for relay's goal; the cost is that "grill me" no longer
  works in relay sessions until a project keeps a copy.
- **[rev 4] The owner: round 5 "a" (defaults in relay, owner and machine in `~/.relay`, project in its git).** I looked. Two
  costs: (1) `~/.relay` is per machine, so the owner's settings are set once on each machine and can differ (a VM asked for the
  native language could get another answer); doctor shows the values, nothing syncs them. (2) B2 now waits for the registry item
  (its own rough size: 3-4 changes of 30-60 agent minutes). Neither changes the pick.
- **[rev 4] The owner: memory in each project's git (24 Oct).** Section 5.10: personal notes enter the history for good (1 note
  today), and it is the only option with new parts (about 70 agent minutes over M1).
- **[rev 4] The item's goal seen from a newcomer (scenario 6.2).** A person's own `~/.claude/CLAUDE.md` no longer loads in relay
  projects. relay carries the native language through `~/.relay`; anything else the person wants in every relay project has no
  home except each project's files. For the owner nothing is lost (the user file is relay's own today); for a newcomer it is a
  visible change, said at install. Not measured.
- **The front: IP 95.** No weakness found: B2 is the precondition of the container work.
- **The item's own claim, "the same commit gives the same gate result".** Holds for the gate verdict and hooks, not for what agents
  write. The acceptance test is the verdict and the fingerprint.

## 9. Build plan [rev 4: re-estimated]

Agent minutes are guesses (not measured: relay keeps no minutes-per-change record to calibrate against). Revision 2 said about
245, revision 3 about 310. Prerequisite, not counted here: the registry item (item 15).

1. **The launcher itself (about 155, was 115).** A library that, at each start, decides whether the call is a session (Claude
   Code's command list read from `--help` per version) **[rev 4, +10]**; clears dead run files **[rev 4, +5]**; writes the run
   settings (model, effort, permissions, the user rules file excluded, memory); writes relay's rule text from the three homes into
   `CLAUDE.local.md` as a marker block, with the `AGENTS.md` import, or by `--append-system-prompt` when the file is committed
   **[rev 4, +10]**; one `--plugin-dir` per enabled plugin; starts Claude Code. Plus the `relay session` command; the shell block
   in `~/.zshrc` and `~/.bashrc`, written once per file, `relay install --remove`, doctor's check **[rev 4, +15]**; the fake-`claude`
   tests of 5.3.
2. **The gate's own model calls (about 45).** hooks-live and bench take the builder's arguments; plugin evals record what they
   cannot change; `relay bench --isolate` stops losing the sign-in.
3. **Profile, sync and rules (about 55, was 50).** The four `[session]` keys; `relay sync` stops writing `CLAUDE.local.md`;
   `rules/guest.md`; principles in every relay project and `python.md` moved to relay's `.claude/rules`; relay's
   `.claude/rules/tools.md` (the bun rule); the rule text reads `kit.toml [rules] load` and the owner's settings **[rev 4, +5]**.
4. **The fingerprint (about 50).** `relay doctor --run`, the gate log lines, the dirty warning, the Mac-vs-image comparison.
5. **The bypass warning (about 20).** The SessionStart line for sessions not started by the launcher; doctor's line for a project
   that turns relay's plugin off.
6. **Memory M2 (about 100, was M1 at 30) [rev 4].** Clean-up first (30): re-read each note, move the 20 rules and decisions, the
   owner fact to `~/.relay`, delete the 14 duplicates. Then (70): the start step (land leftovers, fill staging, derive the
   index), the landing hook built on the queue's engine, the inert path and guard-main's refusal of direct writes, the
   `[memory] local` switch and setup's question about notes already on the machine, tests.
7. **Install keeps a person's `~/.claude/CLAUDE.md` (about 10) [rev 4].**
8. **Scenario tests (about 20) [rev 4].** The three scenarios of section 6 on a temporary home folder with a fake `claude`: the
   files before and after match the tables; one interruption case each (a killed start, a failed landing).

Total about 455 (was 310): +45 launcher, +5 rules, +70 memory (M2 instead of M1), +10 install, +20 scenario tests, -5 rounding.
With M1 instead of M2: about 385. Without memory work (M0): about 355.

Not verified, for the builder to check first (each free or under one cent):
- That `--plugin-dir`, `--settings` and `--append-system-prompt` behave the same in an interactive session as under `-p`.
- That an interactive session in a folder Claude Code has not seen still asks the trust question for the project's hooks.
- Whether `claude plugin eval`'s child runs load `~/.claude/CLAUDE.md` and a parent `CLAUDE.local.md`.
- Whether agents started by the front read or write auto memory, and whether they see the parent's added system prompt.
- Whether `~/AGENTS.md` loads in a session started inside `~/relay` (one probe run from there).
- That Claude Code writes notes with its own Write and Edit tools (so a hook after them sees each note); if it does not, the
  landing runs at session end and at the next start instead, and a crash loses nothing but the timing.

## 10. Found while measuring: fix items (wrong outside this change)

- **MEDIUM, repeats every session:** `~/.claude/agents/worker.md` and `reviewer.md` (untyped) appear in every session (p0); the
  route guard refuses only `general-purpose`. Failing case: the agent list holds `worker` next to `delegate:worker`. Pass cases:
  doctor names leftover user agents with the command that removes them; the guard refuses an untyped agent whose name matches a
  typed one.
- **LOW:** `relay bench --isolate` says sign-in still works with the keychain; measured "Not logged in".
- **LOW:** the retired `principles` marketplace, permission `Read(~/principles/**)`, stale install scopes and `~/.claude/hooks/`
  remain; doctor reports none of them.
- **LOW:** the memory index drifts from the notes: 15 of 36 notes are not in `MEMORY.md`, 11 of them duplicates of rules that
  were never deleted. Failing case: `ls memory | wc -l` minus 1 differs from the index's line count with no record why. Pass
  case: every note is in the index, or doctor names the ones that are not. (Item 6 of the build fixes it.)
- **[rev 4] LOW (review F9):** ALIX loads a relay-written `CLAUDE.local.md` of 24 Oct (71 lines) that nothing updates, because
  ALIX is no longer in `projects.toml`. Failing case: a folder with a relay-marked `CLAUDE.local.md` and no project entry; no
  command names it. Pass cases: doctor names such a file with the command that removes its relay block; a relay-marked file in a
  listed project gives no message; a hand-written file (no marker) is never named. The check runs over the folders where relay
  setup ran (the registry item's machine list). About 15 agent minutes.
- **[rev 4] MEDIUM, a person's file stops loading:** `relay install` moves a hand-written `~/.claude/CLAUDE.md` aside to
  `CLAUDE.md.before-relay` (`lib/relay_rules.py` `write_target`, install calls sync with `adopt="global"`). Failing case: a
  temporary home with a hand-written `CLAUDE.md`; after install, Claude Code no longer reads the person's lines. Pass case: the
  lines stay byte for byte and relay's block follows them once. Build item 7 fixes it; a fix item only if B2 is put off.

## 11. The review of revision 2, finding by finding (kept from revision 3)

F1 (memory in the checkout refused by guard-main): nothing is written into any checkout; under M2 the notes land through relay's
landing engine and the staging folder is outside every checkout. F2, F3 (step 8 leaves sessions unguarded, strips plugins outside
relay): step 8 dropped. F4 (the gate's calls load user rules): hooks-live and bench use the builder; plugin evals are a named
input. F5 (rule text at sync): written per start, hashed. F6 (dirty copy): dirty mark, content hash, warning. F7
(skipWorkflowUsageWarning): carried. F8 (subcommands): passed straight through, now read from `--help`. F9 ("13 projects"):
corrected. F10 (personal notes in work repositories): M2 is the only option that puts them there; said in 5.10's critique and
handled for shared repositories by `[memory] local`.

## Open for the owner

**Confirm: `claude` in a relay project goes through relay's launcher**

Today typing `claude` in relay's folder loads the plugins, rules, memory, model and old agents from your user folder. `relay
install` would add one marked block to `~/.zshrc` and `~/.bashrc` (shown in section 5.1): in a folder whose repository has
`.claude/kit.toml` it sends `claude` through relay's launcher, which keeps everything the project has (its rules, skills, agents
and hooks all loaded in four tests, $0.006) and adds relay's rules and settings from relay. In any other folder it runs the real
`claude` with the same arguments, environment and exit code (tested today in both shells). `relay install --remove` takes the
block out. A session from an IDE or the desktop app stays as today and is told so at its start. Your round-4 "2. Да" reads as a.

| | Habit | Every relay session project-only | Cost |
|---|---|---|---|
| a. Shell block | none | yes, from a terminal | one block in each shell startup file; about 455 agent minutes for the whole item (385 with memory option b) |
| b. A separate command `relay session` | new command | only when you remember | the same less about 15 |
| c. Project files only, no launcher | none | no: user rules, memory, agents and skills still load | about 45 |

- a. Shell block (recommended; my reading of your "Да")
- b. A separate command
- c. Project files only

**Where the memory of a project lives**

Claude Code keeps short notes between sessions ("memory"): for relay, 36 notes in your user folder on this Mac, keyed to relay's
path, so a Linux VM starts with none. Sorted one by one: 14 repeat relay's rules, 20 are rules or decisions that exist only there
(for example "Node is banned in relay, bun only", "relay is not published"), 1 is a fact about your subscription, 1 is your
plan for after release. On 24 Oct you chose to keep each project's notes in that project's git ("почему мы не можем хранить
память о всех проектах в самих проектах, сохранять их в гит и легко переносить между машинами"); the previous revision missed
that and recommended keeping notes per machine. Every option starts with the same clean-up (14 deleted, 20 moved into the rules
or the queue). They differ in where new notes go.

| | A new note reaches another machine | Your personal notes in a work repository | New parts | Agent minutes (guess) |
|---|---|---|---|---|
| a. Notes in the project's git, each landing at once (your 24 Oct pick) | yes, with the project | yes, for good (1 note today) | a start step, a landing hook | about 100 |
| b. Clean-up only; new notes stay per machine | no, until someone moves it (20 piled up in 10 days) | no | none | about 30 |
| c. A notes repository of your own, synced | yes, if cloned there | no | a sync command, one more repository | about 75 |
| d. Do nothing | no | no | none | 0 |

- a. Notes in the project's git (recommended; your 24 Oct pick; after it, the memory question is closed until revisited)
- b. Clean-up only
- c. A personal notes repository
- d. Do nothing

**Should relay stay in your user folder, for folders outside relay projects**

Besides the shell block, `relay install` writes relay's shared rules into `~/.claude/CLAUDE.md` and turns relay's 4 plugins on
for your whole user, so a Claude Code session in any folder (a relay project opened from an IDE or the desktop app, or a project
that does not use relay) loads relay's rules and hooks. That is how it works today. For you it means your working rules (Russian,
lettered choices, plain words) apply everywhere; for a newcomer it means installing relay changes every one of their projects.
The launcher does not need it: inside relay projects it supplies everything itself.

| | Relay project opened from an IDE or the desktop app | A folder that does not use relay | Your working rules outside relay projects |
|---|---|---|---|
| a. Keep relay in the user folder (today), keeping a person's own lines | guards on, told it bypassed the launcher | gets relay's rules and plugins | yes |
| b. Shell block only | no guards, no relay rules, nothing tells it | exactly as before relay | no |

- a. Keep relay in the user folder (recommended: the guards stay on for every relay session, and your rules follow you)
- b. Shell block only
