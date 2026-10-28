---
type: tool_used
tool: Grep
input_match: "\"path\":\"[^\"]*\\.claude(?:/kit)?\"|\"pattern\":\"[^\"]*(?:DOC|ROLE)-RULE|kit/(?:code-reviewer|critic|judge)\\.md"
min: 0
max: 0
---
The case fails a run in which a session read the rule file (max 0): such a run does not prove the hook delivered it. A Grep over the .claude folder or for the rule label.
