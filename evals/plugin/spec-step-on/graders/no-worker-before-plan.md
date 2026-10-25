---
type: tool_used
tool: Agent
input_match: "delegate:worker"
min: 0
max: 0
---
Spec steps are on and the prompt stops at the first agent's reply, so the first agent is the planning step's (a scout or the author), never a worker: no delegate:worker is started before openspec:plan is loaded. (This was a meaning grader; the judge reads only the last message, which does not show the order of tool calls, so it failed correct runs.)
