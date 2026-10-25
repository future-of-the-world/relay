#!/usr/bin/env bash
# The fixture. The rule texts the session follows reach it through `append_system_prompt` in prompt.md (the runner
# turns CLAUDE.md loading off); evals/plugin/system_rules.py writes that line.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
"$here/../setup-fixture.sh"
