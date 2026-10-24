---
type: tool_used
tool: Bash
input_match: "(?:^\\{\"command\":\"(?:(?!<<)(?:\\\\\"|[^\"]))*?\\b(?:cat|head|tail|less|more|sed|awk|nl|bat)\\b(?:(?!<<)(?:\\\\\"|[^|;&<>\"]))*?\\bkit/(?:critic|judge)\\.md)|(?:^\\{\"command\":\"(?:(?!<<)(?:\\\\\"|[^\"]))*?\\bgrep\\b(?:(?!<<)(?:\\\\\"|[^|;&<>\"]))*?\\s(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\\s(?=(?:(?!<<)(?:\\\\\"|[^\"]))*?(?:(?:DOC|ROLE)-RULE|\\.claude\\b|\\s\\.(?=\\s|\\\\\"|\"))))|(?:^\\{\"command\":\"(?:(?!<<)(?:\\\\\"|[^\"]))*?\\brg\\b(?:(?!<<)(?:\\\\\"|[^|;&<>\"]))*?\\s(?:-u{1,3}|--hidden|--no-ignore)\\b)"
min: 0
weight: 0.001
---
Flag, never a failure (min 0 always passes; weight 0.001 because 0 is refused): A shell read of the rule file (cat, head, sed ... kit/<file>.md), a recursive grep aimed at it, or ripgrep with hidden files. A heredoc body never counts. `bin/ci` prints a note when the explanation says it was called, because a session in the run that read the rule file itself does not prove the hook delivered it.
