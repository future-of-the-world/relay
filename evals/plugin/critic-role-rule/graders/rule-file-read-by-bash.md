---
type: tool_used
tool: Bash
input_match: "(?:^\\{\"command\":\"(?:(?!<<)(?:\\\\\"|[^\"]))*?\\b(?:cat|head|tail|less|more|sed|awk|nl|bat)\\b(?:(?!<<)(?:\\\\\"|[^|;&<>\"]))*?\\bkit/(?:code-reviewer|critic|judge)\\.md)|(?:^\\{\"command\":\"(?:(?!<<)(?:\\\\\"|[^\"]))*?\\bgrep\\b(?:(?!<<)(?:\\\\\"|[^|;&<>\"]))*?\\s(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\\s(?=(?:(?!<<)(?:\\\\\"|[^\"]))*?(?:(?:DOC|ROLE)-RULE|\\.claude\\b|\\s\\.(?=\\s|\\\\\"|\"))))|(?:^\\{\"command\":\"(?:(?!<<)(?:\\\\\"|[^\"]))*?\\brg\\b(?:(?!<<)(?:\\\\\"|[^|;&<>\"]))*?\\s(?:-u{1,3}|--hidden|--no-ignore)\\b)"
min: 0
max: 0
---
The case fails a run in which a session read the rule file (max 0): such a run does not prove the hook delivered it. A shell read of the rule file (cat, head, sed ... kit/<file>.md), a recursive grep aimed at it, or ripgrep with hidden files. A heredoc body never counts.
