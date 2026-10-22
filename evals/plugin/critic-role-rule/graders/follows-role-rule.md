---
type: regex
pattern: "^(?![\\s\\S]*\\b(no (findings|bugs)|found nothing|nothing (found|to report))\\b)(?=[\\s\\S]*(?:^|\\n)(?=[^\\n]*shelf\\.ts:\\s?(2[4-9]|30)\\b)(?=[^\\n]*ROLE-RULE))"
flags: i
---
The word ROLE-RULE exists only in the project's .claude/kit/judge.md, the file for the whole judge role; delegate:critic has no file of its own in the fixture. The plant is takeItem() (src/shelf.ts lines 24-30), correct and tested, whose quantity parameter is named `amount`. The fact is graded through a form the agent's own text requires, not through wording: one reply line that gives `shelf.ts:24` to `:30` and the label ROLE-RULE (a project-rule finding is a line with where, what and the rule's label). A reply that says "no findings" fails.
