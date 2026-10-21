# Delegation

The main session routes; typed agents work; a brief file carries the
context; the hand-back is ten lines. The economics are in
`rules/delegation.md`; the procedure in the `delegate` skill
(`plugins/delegate/skills/delegate/SKILL.md`). This page is the reference.

## Tiers

| tier | agent | default model, effort | tools | reply |
|---|---|---|---|---|
| look | `delegate:scout` | haiku, low | Read Grep Glob | ≤10 lines, file:line |
| run | `delegate:runner` | haiku, low | Bash Read | ≤3 lines |
| build | `delegate:worker` | sonnet, medium | Read Edit Write Bash Grep Glob Skill | ≤10 lines + report file |
| fix | `delegate:fixer` | sonnet, medium | same | ≤10 lines + report file |
| think | `delegate:thinker` | opus, high | Read Grep Glob Bash Write Skill | ≤10 lines + one document |
| judge | `delegate:critic` | opus, high | Read Grep Glob Bash Write | ≤10 lines + findings file |

The models and efforts come from `profiles/active.toml` and are written
into the agent files by `relay sync`. An OpenSpec project's flow maps its
own roles (`sdd:worker`, `sdd:author`, ...) onto the same tiers in
`plugins/sdd/flow.json`; their frontmatter is not profile-driven yet
(see docs/handover.md, open items).

## The routing guard

`plugins/delegate/hooks/route-guard.py`, PreToolUse on Agent:

| call | decision |
|---|---|
| `subagent_type: general-purpose` | deny, naming the six typed agents (`[delegate] typed_only = false` to allow) |
| `subagent_type: fork` with the session over `fork_limit` | deny: write a brief, start a typed agent |
| worker/fixer/scout/runner with `model: opus` | deny unless the prompt has a line `Escalated: <reason>` (`build_tier_opus = allow|deny|escalate`) |
| prompt over 3,000 characters without `Brief:` | a note: put it in a brief file |
| `max_parallel` agents already running | a note |

Settings per project in `.claude/kit.toml [delegate]`; per shell with
`RELAY_DELEGATE_<KEY>`. Tests: `plugins/delegate/tests/route-guard.test.sh`.

## Escalation

A Sonnet worker that returns `BLOCKED` or `BUDGET SPENT` twice on the same
brief may be restarted on Opus: same brief, a fresh agent, the prompt line
`Escalated: <what failed>`. The ledger records the model, so `relay report`
shows how often escalation happens; if it is often, the brief format or the
tier is wrong, not the model.

## Not losing context

- The brief file (template in the `delegate` skill): goal, done-when, check,
  the files and sections to read, the decisions verbatim, what is not
  decided, the report path. The front writes it from the conversation; the
  agent reads only it and what it names.
- The report file: the agent's reply plus what did not fit. The front opens
  its first 40 lines only when the reply is not `DONE`.
- `docs/handover.md` of the project: state across sessions (front plugin).
- The session scratchpad (`scratchpad_dir` in hook input) holds briefs and
  reports; nothing of it goes into the repository.

## Parallelism

At most `max_parallel` (4) agents at once. Agents started together each pay
a first read of CLAUDE.md, the brief and the code, so a wave wider than the
work is parallel for no gain. Independent lookups go to one scout in one
message. Fewer, longer agents are the cheap shape; an agent that waits is
not.
