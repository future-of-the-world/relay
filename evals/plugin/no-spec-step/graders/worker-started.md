---
type: tool_used
tool: Agent
input_match: "delegate:(?:worker|scout)"
min: 1
---
The change goes to a plain delegate agent, never an openspec one: the request does not say where the list lives, so the coordinator may send a scout to find it first, and the prompt stops at the first agent's reply, so the scout is then the only agent started (measured 27 Oct: 2 of 18 runs, both scout-first, failed the old "delegate:worker" pattern for that reason alone; the other 16 started a worker).
