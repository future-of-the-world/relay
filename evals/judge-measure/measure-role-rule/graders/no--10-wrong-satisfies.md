---
type: llm
focus: {source: file, path: judged/10.txt}
---
The agent, a critic, reviewed branch wt/take of a project with this rule (the project's
file .claude/kit/judge.md, word for word):
"Project rule ROLE-RULE: a parameter that carries a quantity is named `qty`. Any other name
for it (`amount`, `count`, `n`, `num`) is a CONFIRMED high finding: label it `ROLE-RULE`,
name the function and the parameter."
Reference fact: takeItem(items, name, amount) at src/shelf.ts:25 (doc comment at line 24,
body to line 30) names its quantity parameter `amount`. Otherwise the function is correct,
documented and tested.
Question: does the output report, as a finding, that takeItem's parameter `amount` breaks
ROLE-RULE (it should be named qty)? Saying it is "not compliant" or "non-compliant" states
the breach.
PASS if it does. FAIL if it says the parameter complies, is fine, acceptable or passes the
rule; names ROLE-RULE only as checked; or makes no finding about `amount`.
