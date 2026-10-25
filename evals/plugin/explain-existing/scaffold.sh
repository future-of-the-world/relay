#!/usr/bin/env bash
# The fixture plus a project CLAUDE.md that carries the rule texts the front reads (delegation, working with me, verify).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
"$here/../setup-fixture.sh"
{ cat "$here/../../../rules/delegation.md" "$here/../../../rules/working-with-me.md" "$here/../../../rules/verify.md"; } > CLAUDE.md
