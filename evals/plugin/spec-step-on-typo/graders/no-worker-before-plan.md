---
type: llm
---
The run is a project with spec steps on, given a plain feature request. Question: in the
tool calls, is the Skill call that loads openspec:plan made before any Agent call that
starts delegate:worker (or is no delegate:worker started at all)?
PASS if openspec:plan is loaded first, or no worker is started. FAIL if a delegate:worker
is started before openspec:plan is loaded.
