---
type: regex
pattern: "(?:^|\\n)(?=[^\\n]*shelf\\.ts:\\s?(?:2[4-9]|30)\\b)(?=[^\\n]*ROLE-RULE)(?=[^\\n]*\\bamount\\b)"
flags: i
---
The word ROLE-RULE exists only in the project's .claude/kit/judge.md, the file for the whole judge role; delegate:critic has no file of its own in the fixture. The plant is takeItem() (src/shelf.ts lines 24-30), correct and tested, whose quantity parameter is named `amount`. The reply has one line that gives `shelf.ts:24` to `:30`, the label ROLE-RULE and the parameter `amount` (the rule says: name the function and the parameter). Whether that line reports a breach is for the llm grader reports-role-rule-breach.
