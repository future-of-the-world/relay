#!/usr/bin/env bash
# The fixture plus a project CLAUDE.md that carries the owner's language line, a glossary line for gate, and the rule text itself
# (rules/working-with-me.md, the one a synced project loads).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
"$here/../setup-fixture.sh"
{ echo "My native language: Russian."; echo; echo "Project glossary: the gate is this project's full local check before a merge (tests, lint, types); it is a relay term."; echo; cat "$here/../../../rules/working-with-me.md"; } > CLAUDE.md
