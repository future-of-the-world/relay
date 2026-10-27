---
type: tool_used
tool: Bash
input_match: "said\\s*=.*recrod to also hold the minutes spent waiting for the check"
min: 1
---
The session wrote the TOML of a `said` note carrying the owner's words as given, typo included ("recrod"), not a corrected copy. The judge sees only the final reply, not the file, so this is checked on the Bash call that writes the file (a heredoc; Write is not granted to this case because the one grader reads one tool).
