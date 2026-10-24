#!/usr/bin/env bash
# The fixture (its openspec/ folder, no [specs] in .claude/kit.toml: spec steps are off) plus the change worktree a coordinator makes.
set -euo pipefail
"$(dirname "$0")/../setup-fixture.sh"
bin/wt new sort-by-name master >/dev/null
