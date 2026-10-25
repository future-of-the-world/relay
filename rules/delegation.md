# Delegation
> Small work on small models, thinking on thinking models, nothing lost: one brief file per agent, typed agents only, a 10-line hand-back. Load the `delegate` skill before the first agent.

What work costs is the number of requests times the context each one re-reads.
A subagent's cache lives 5 minutes, a session's 1 hour; on Opus and Sonnet a 5-minute
cache write costs 25 reads, a 1-hour write 40, an output 100 (Haiku half of
that, Fable double; measured 2026-10-21 from Claude Code's own totals;
prices.toml keeps the table).
So: fewer, longer agents; no agent that waits; no agent that carries what it
does not need; and the big model only where judgment is what is being bought.

- The main session only routes and talks: it starts agents from brief files
  and reads 10-line hand-backs. It does not read long files, run long
  commands, or write code (see the `delegate` skill for who does what).
  Size is no reason to do it yourself: one function, one test, one edited
  line, one small script still go to a `worker` through a brief file. The
  main session's own work is talking to the owner, writing briefs, and the
  steps the front skill gives it (the handover file, the merge, the paid
  run in the background); a request to build or change something starts with
  the brief, not the file.
- A question from the owner about a new mechanism (a field, a command, a
  step: "can we", "would X help", "how should we") is not answered inline:
  it goes to the design track. A `thinker` gets the owner's words verbatim and
  measures live data first (a script over the queue, git, the ledger), writes
  at least two distinct approaches plus "do nothing" and how leading tools
  solve it; a `critic` reviews it; the revision comes to the owner with the
  measured numbers. Explaining what already exists stays with the front.
- Tiers, with model and effort set by the active relay profile: scout and
  runner (small model, low effort) read and run; worker and fixer (middle
  model) build and fix; thinker and critic (big model, high effort) design
  and review. A worker gets the big model only with `Escalated: <reason>`
  after a middle-model worker failed the same brief. The routing guard
  refuses `general-purpose` agents and forks from sessions over 100k tokens.
- One agent, one brief: the brief names the files and sections to read, the
  check to loop on, the decisions verbatim, and what is not decided. A group
  of related tasks shares one brief and one agent and runs in order.
- No command blocks over 4 minutes (Bash `timeout` at most 240000 ms); a
  longer job runs detached with a log, waited on in calls of at most 240 s
  (a job over about 30 minutes, the paid `bin/ci`, is the front's: Bash
  `run_in_background`, never a runner).
  A coordinator that must wait for others is a session of its own, not an
  agent. Don't resume an agent idle over 5 minutes: start a fresh one from
  the brief and the old report.
- At most 4 agents at once unless the project says otherwise; independent
  lookups go to one scout in one message.
- One good review, not several: a design review before a risky build; one
  review of the whole change in which every finding carries its failing case
  and the cases a correct fix must pass; the fix is checked against those
  cases by a checker, not reviewed again. Never no review. Wrong inside the
  change is fixed before the merge; wrong elsewhere is a fix item in the work
  queue (rules/queue.md). What is still open comes to the owner with a
  recommendation. The review method is the judge base that every reviewer carries (relay's copy: `~/relay/roles/judge.md`).
- Reports go to files in the session scratchpad; the conversation gets the
  outcome in plain words.
