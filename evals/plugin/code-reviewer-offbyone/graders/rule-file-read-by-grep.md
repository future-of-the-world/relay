---
type: tool_used
tool: Grep
input_match: "\"path\":\"[^\"]*\\.claude(?:/kit)?\"|\"pattern\":\"[^\"]*(?:DOC|ROLE)-RULE|kit/(?:code-reviewer|judge)\\.md"
min: 0
weight: 0.001
---
Flag, never a failure (min 0 always passes; weight 0.001 because 0 is refused): A Grep over the .claude folder or for the rule label. `bin/ci` prints a note when the explanation says it was called, because a session in the run that read the rule file itself does not prove the hook delivered it.
