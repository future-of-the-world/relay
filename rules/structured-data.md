# Structured data
> Information that a script, a hook or a later step reads is stored as a structured file (JSON, TOML or YAML) with a schema check, and changed only through one script, when it is one of many records of the same shape; instructions and prose stay text.

- The test: a value goes into a structured file when it is one of many records of the same shape (queue
  items, verdicts, ledger lines, votes) whose fields a script reads or writes. Instructions, rules,
  briefs, reports and hand-backs are text for people and models and stay prose.
- What counts as read by a script: state, verdicts, items, logs, votes. Each is a structured
  file, not prose with labels.
- One writer: a single library parses, checks and writes the file. Nothing else edits it by hand or by
  string replacement; a file that fails the check is shown as malformed, never guessed at.
- When a person reads it, the readable form is a view made from the data (a table, a list, a
  summary), never read back. The readable form is rendered by a script on demand, never stored beside the data.
- Extensions (extra views, reports, converters) live in relay only. They get a copy of the parsed data
  and read it; they never write.
- No new label or regex search over markdown to get a value out of it. A reviewer flags one, and the
  fix is to store that value as data.
