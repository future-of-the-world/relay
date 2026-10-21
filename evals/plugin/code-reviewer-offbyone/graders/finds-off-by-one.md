---
type: regex
pattern: "^(?![\\s\\S]*\\b(no (findings|bugs)|found nothing|nothing (found|to report))\\b)(?=[\\s\\S]*(off[- ]by[- ]one|(one|1) (\\w+ )?(extra|more|additional)\\b|(one|1) (item|element|entry|row)s? too many|too many (items|elements|entries)|(more|larger) than `?size|size ?\\+ ?1 (items|elements)|(holds?|returns?|yields?|gives?) `?size ?\\+ ?1|exceeds? `?size))"
flags: i
---
The planted bug: page() slices to start + size + 1, so a page holds one item too many. The reply states that as a defect. The reply may say it as "off by one", "one item too many", "holds size + 1 items" or "returns size+1". A reply that says "no findings", or only quotes the slice, or says "one parameter too many", does not pass (graders/../recorded/bad/ holds such replies, checked by evals/graders.test.sh).
