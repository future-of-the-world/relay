---
type: tool_used
tool: Bash
input_match: "said\\s*=.*минуты ожидания проверки"
min: 1
---
The session wrote the TOML of a `said` note carrying the owner's words about the minutes of waiting for the check as given, in Russian. The judge sees only the final reply, not the file, so this is checked on the Bash call that writes the file (a heredoc; Write is not granted to this case because the one grader reads one tool).
