---
type: regex
pattern: "^(?![\\s\\S]*(findings:\\s*none|no findings|\\bthey agree\\b))(?:(?=[\\s\\S]*(shelf\\.json\\.bad|moved aside|set aside|\\bD2\\b))(?=[\\s\\S]*(as it is|in place|untouched|left alone|left where))(?=[\\s\\S]*(contradict|conflict|disagree|inconsisten|mismatch|differs?\\b|does(n't| not) match|can(no|'|\u2019)t satisfy both|cannot both|\\bvs\\.?\\s|\\bversus\\b|\\bwhereas\\b|\\bbut (the )?(design|D2|spec|scenario)))|[\\s\\S]*?(?:^|\\n)[^\\n]*(?:spec\\.md:1[5-8](?:-1[5-9])?\\b.{0,20}\\W+(?:vs\\.?|against|versus)\\W+.{0,20}design\\.md:1[1-3](?:-1[1-3])?\\b|design\\.md:1[1-3](?:-1[1-3])?\\b.{0,20}\\W+(?:vs\\.?|against|versus)\\W+.{0,20}spec\\.md:1[5-8](?:-1[5-9])?\\b))"
flags: i
---
The planted flaw: the "Corrupt data" scenario says the file is left as it is, while design D2 moves a corrupt file aside to shelf.json.bad. `kit spec-check` and `openspec validate` both pass on this change (the failure scenarios exist), so only a reviewer that reads the spec against the design finds it.

The fact is graded through a form the agent's own text requires, not through wording. Either half passes:
- the words: the reply names the two sides (D2 or shelf.json.bad, and the file left as it is / in place) and sets them against each other ("contradict", "conflict", "vs", "can't satisfy both", "but design D2");
- the location pair: one reply line joins spec.md:15-18 and design.md:11-13 by "vs", "against" or "versus" (a finding's place is `artifact:line`, so this holds however the sentence is phrased).
A reply that says "no findings" or that the two "agree" fails both halves. No multiline flag is used (the eval harness's support for it is not documented): the line anchor is `(?:^|\n)[^\n]*`. Proof: evals/plugin/graders.test.sh replays recorded replies, among them the master run that failed on wording alone.
