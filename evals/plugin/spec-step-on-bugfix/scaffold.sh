#!/usr/bin/env bash
# The fixture with spec steps turned on, as `relay setup --specs openspec` leaves a project ([specs] method in
# .claude/kit.toml). The rule texts the session follows reach it through `append_system_prompt` in prompt.md (the runner
# turns CLAUDE.md loading off); evals/plugin/system_rules.py writes that line.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
"$here/../setup-fixture.sh"
printf '\n[specs]\nmethod = "openspec"\n' >> .claude/kit.toml
git add -A
git -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "Spec steps on"
bin/wt new sort-by-name master >/dev/null
