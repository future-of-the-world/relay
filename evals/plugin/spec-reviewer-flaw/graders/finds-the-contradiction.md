---
type: regex
pattern: "(?:^|\\n)(?=[^\\n]*spec\\.md)(?=[^\\n]*(?:design\\.md|\\bD2\\b))"
flags: i
---
The planted flaw: the "Corrupt data" scenario says the file is left as it is, while design D2 moves a corrupt file aside to shelf.json.bad. `kit spec-check` and `openspec validate` both pass on this change, so only a reviewer that reads the spec against the design finds it. This grader is the fact the code can check: one reply line names spec.md and (design.md or D2). Whether that line reports a contradiction is for the llm grader reports-the-contradiction.
