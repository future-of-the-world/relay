---
type: regex
pattern: "(?:^|\\n)[^\\n]*shelf\\.ts:\\s?2[5-8]\\b"
flags: i
---
The planted bug is at src/shelf.ts line 27 (lines 25-28 are page()). The reply has one line that locates page() as `file:line` in that range. Whether that line reports the bug is for the llm grader reports-off-by-one. The form is `file:line` (`src/shelf.ts:27`); a location written `src/shelf.ts line 27` does not match, by design: the reviewer's required form is `file:line`.
