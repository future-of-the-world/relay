---
type: regex
pattern: "(?:^|\\n)(?![^\\n]*\\b(?:complies|compliant|conforms)\\b)(?=[^\\n]*shelf\\.ts:\\s?(?:2[4-9]|30)\\b)(?=[^\\n]*ROLE-RULE)(?=[^\\n]*\\bamount\\b)"
flags: i
---
The word ROLE-RULE exists only in the project's .claude/kit/judge.md, the file for the whole judge role; delegate:critic has no file of its own in the fixture. The plant is takeItem() (src/shelf.ts lines 24-30), correct and tested, whose quantity parameter is named `amount`. The fact is graded through a form the agent's own text requires, not through wording: one reply line that gives `shelf.ts:24` to `:30`, the label ROLE-RULE and the parameter `amount` (the rule says: name the function and the parameter). A line that says the code complies does not count. The grader does not look at other lines: a right finding stays right next to "no bugs elsewhere" or "no findings outside this change"; a reply with no such line fails.
