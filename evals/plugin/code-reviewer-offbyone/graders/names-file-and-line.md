---
type: regex
pattern: "^(?![\\s\\S]*\\b(no (findings|bugs)|found nothing|nothing (found|to report))\\b)(?=[\\s\\S]*(shelf\\.ts:\\s?2[5-8]\\b|\\blines? 2[5-8]\\b))"
flags: i
---
The planted bug is at src/shelf.ts line 27 (lines 25-28 are page()). The reply gives the file and a line in that range, as `file:line`, and is not a "no findings" reply.
