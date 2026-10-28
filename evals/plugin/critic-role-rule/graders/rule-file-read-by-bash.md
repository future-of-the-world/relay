---
type: tool_used
tool: Bash
input_match: "(?:^\\{\"command\":\"(?:(?!<<)(?:\\\\\"|[^\"]))*?(?:\\.claude/kit|\\bkit/(?:code-reviewer|critic|judge)\\.md))|(?:^\\{\"command\":\"(?:(?!<<)(?:\\\\\"|[^\"]))*?\\bgit\\b(?:(?!<<)(?:\\\\\"|[^|;&<>\"]))*?\\blog\\b(?:(?!<<)(?:\\\\\"|[^|;&<>\"]))*?\\s(?:-p|--patch)\\b(?!(?:\\\\\"|[^|;&<>\"])*\\.\\.))|(?:^\\{\"command\":\"(?:(?!<<)(?:\\\\\"|[^\"]))*?\\bfind\\b(?:(?!<<)(?:\\\\\"|[^|;&<>\"]))*?\\.claude\\b)|(?:^\\{\"command\":\"(?:(?!<<)(?:\\\\\"|[^\"]))*?\\bgrep\\b(?:(?!<<)(?:\\\\\"|[^|;&<>\"]))*?\\s(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\\s(?=(?:(?!<<)(?:\\\\\"|[^\"]))*?(?:(?:DOC|ROLE)-RULE|\\.claude\\b|(?:qty|amount|count)\\b(?:\\\\\"|[^|;&<>\"])*?\\s\\.(?=\\s|\\\\\"|\"))))|(?:^\\{\"command\":\"(?:(?!<<)(?:\\\\\"|[^\"]))*?\\brg\\b(?:(?!<<)(?:\\\\\"|[^|;&<>\"]))*?\\s(?:-u{1,3}|--hidden|--no-ignore)\\b)"
min: 0
max: 0
---
The case fails a run in which a session read the rule file (max 0): such a run does not prove the hook delivered it. Any shell command naming .claude/kit or kit/<file>.md, git log -p without a range, find over .claude, a recursive grep for a word the rule file holds (or over .claude), or ripgrep with hidden files. A heredoc body never counts.
