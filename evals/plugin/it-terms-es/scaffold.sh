#!/usr/bin/env bash
# The fixture plus a project CLAUDE.md that carries the owner's language line and the rule text itself
# (rules/working-with-me.md, the one a synced project loads).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
"$here/../setup-fixture.sh"
{ echo "My native language: Spanish."; echo; cat "$here/../../../rules/working-with-me.md"; } > CLAUDE.md
