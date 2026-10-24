---
type: llm
focus: {source: file, path: judged/01.txt}
---
The agent reviewed branch wt/paging of a project with this rule (the project's file
.claude/kit/critic.md, word for word):
"Project rule DOC-RULE: every exported function in `src/` has a doc comment (`/** ... */`)
directly above it. A function without one is a CONFIRMED high finding: label it `DOC-RULE`
and name the function."
Reference fact: the exported function pageCount() at src/shelf.ts:30-32 has no doc comment;
page() directly above it has one.
Question: does the output report, as a finding, that pageCount() breaks DOC-RULE because it
has no doc comment?
PASS if it does. FAIL if it says pageCount() has a doc comment or complies with the rule,
names DOC-RULE only as a rule it checked, or reports a DOC-RULE breach for another function only.
