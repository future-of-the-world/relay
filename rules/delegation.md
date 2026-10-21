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
  longer job runs detached with a log, waited on in calls of at most 240 s.
  A coordinator that must wait for others is a session of its own, not an
  agent. Don't resume an agent idle over 5 minutes: start a fresh one from
  the brief and the old report.
- At most 4 agents at once unless the project says otherwise; independent
  lookups go to one scout in one message.
- Review runs twice at most: critic, fixer, critic over the fix range. What
  is still open comes to the owner with a recommendation.
- Reports go to files in the session scratchpad; the conversation gets the
  outcome in plain words.
