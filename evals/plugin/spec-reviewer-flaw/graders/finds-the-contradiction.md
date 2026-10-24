---
type: regex
pattern: "(?:^|\\n)(?=[^\\n]*\\bspec(?:\\.md|\\b))(?=[^\\n]*(?:design\\.md|\\bD2\\b))"
flags: i
---
The planted flaw: the "Corrupt data" scenario says the file is left as it is, while design D2 moves a corrupt file aside to shelf.json.bad. `kit spec-check` and `openspec validate` both pass on this change, so only a reviewer that reads the spec against the design finds it. This grader is the fact the code can check: one reply line names the spec (spec.md or "the spec") and (design.md or D2); a reviewer may write "the spec's ... scenario" with only design.md:13 as the path. Whether that line reports a contradiction is for the llm grader reports-the-contradiction.
