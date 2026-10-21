#!/usr/bin/env bash
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"; fails=0
check() { local name="$1" want="$2" out; out="$(printf '{"hook_event_name":"UserPromptSubmit","prompt":%s}' "$3" | python3 "$here/../hooks/tune-stage.py")"
  if [[ "$out" == *"$want"* ]]; then echo "ok   $name"; else echo "FAIL $name: got '$out'"; fails=1; fi; }
quiet() { local name="$1" out; out="$(printf '{"hook_event_name":"UserPromptSubmit","prompt":%s}' "$2" | python3 "$here/../hooks/tune-stage.py")"
  if [[ -z "$out" ]]; then echo "ok   $name"; else echo "FAIL $name: expected silence, got '$out'"; fails=1; fi; }
check "try haiku for workers" 'front:tune' '"try Haiku instead of Sonnet for workers"'
check "more planning smaller tasks" 'front:tune' '"change worker flow, make more planning and smaller task for Haiku setup, make comparison of results"'
check "what did this week cost" 'front:tune' '"what did this week cost?"'
check "compare" 'front:tune' '"make a comparison of the two setups"'
check "adopt it" 'front:tune' '"ok adopt it"'
quiet "project work: silent" '"fix the flaky kill test in procgroup"'
quiet "project work with the word model: silent" '"add a model field to the Item type"'
quiet "slash command: silent" '"/opsx:apply add-x"'
quiet "task notification: silent" '"<task-notification>the worker finished; compare haiku and sonnet</task-notification>"'
quiet "agent message: silent" '"<agent-message from=\"scout\">try haiku instead of sonnet for workers</agent-message>"'
quiet "system notification: silent" '"[SYSTEM NOTIFICATION] what did this week cost?"'
exit $fails
