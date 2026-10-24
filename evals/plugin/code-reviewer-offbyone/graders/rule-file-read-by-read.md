---
type: tool_used
tool: Read
input_match: "kit/(?:code-reviewer|critic|judge)\\.md"
min: 0
weight: 0.001
---
Flag, never a failure (min 0 always passes; weight 0.001 because 0 is refused): A Read of the project's rule file: the hook did not need to deliver it. `bin/ci` prints a note when the explanation says it was called, because a session in the run that read the rule file itself does not prove the hook delivered it.
