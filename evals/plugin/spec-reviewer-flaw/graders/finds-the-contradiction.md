---
type: regex
pattern: "^(?=[\\s\\S]*(shelf\\.json\\.bad|moved aside|set aside|\\bD2\\b))(?=[\\s\\S]*(as it is|in place|untouched|left alone|left where))(?=[\\s\\S]*(contradict|conflict|disagree|inconsisten|mismatch|differs?\\b|does(n't| not) match|can(no|'|’)t satisfy both|cannot both|\\bvs\\.?\\s|\\bversus\\b|\\bwhereas\\b|\\bbut (the )?(design|D2|spec|scenario)))"
flags: i
---
The planted flaw: the "Corrupt data" scenario says the file is left as it is, while design D2 moves a corrupt file aside to shelf.json.bad. `kit spec-check` and `openspec validate` both pass on this change (the failure scenarios exist), so only a reviewer that reads the spec against the design finds it. The reply names the two sides (D2 or shelf.json.bad, and the file left as it is / in place) and sets them against each other ("contradict", "conflict", "vs", "can't satisfy both", "but design D2").
