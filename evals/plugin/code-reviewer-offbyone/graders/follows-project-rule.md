---
type: regex
pattern: "(?:^|\\n)(?=[^\\n]*DOC-RULE)(?=[^\\n]*pageCount)"
flags: i
---
The word DOC-RULE exists only in the fixture's .claude/kit/critic.md, the project's addition for this role. The rule says: label the finding `DOC-RULE` and name the function, so the label and `pageCount` stand on ONE line. Whether that line reports a breach is for the llm grader reports-doc-rule-breach.
