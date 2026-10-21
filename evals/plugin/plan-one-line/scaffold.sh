#!/usr/bin/env bash
# The fixture plus the worktree sdd:plan makes first (its step 1), for the change the prompt names.
set -euo pipefail
"$(dirname "$0")/../setup-fixture.sh"
bin/wt new remove-item master >/dev/null
