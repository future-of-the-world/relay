#!/usr/bin/env bash
# Tests for templates/kit-shim: a project script reaches `kit` with no PATH help.
#   plugins/relay/tests/shim.test.sh
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd -P)"
shim="$here/../templates/kit-shim"
core="$(cd "$here/.." && pwd -P)"
tmp="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT
fails=0
ck() { [ "$2" = "$3" ] && echo "ok   $1" || { echo "FAIL $1: got [$2] want [$3]"; fails=$((fails + 1)); }; }

P="$tmp/project"
mkdir -p "$P/bin" "$P/.claude" "$P/openspec/specs/dial" && cd "$P" && git init -q -b master . \
  && cp "$shim" bin/kit && chmod +x bin/kit \
  && printf '[gate]\ncheck = "bin/check"\n' >.claude/kit.toml \
  && printf '## Purpose\nDial.\n\n## Requirements\n\n### Requirement: Spin\nThe dial SHALL spin.\n\n#### Scenario: Fast\n- **WHEN** asked\n- **THEN** it spins\n' >openspec/specs/dial/spec.md \
  && git add -A && git -c user.name=t -c user.email=t@t commit -q -m init \
  && git worktree add -q .worktrees/w -b wt/w || { echo "shim.test: cannot build the project" >&2; exit 1; }

# No kit anywhere on PATH: only the python3 that kit needs.
pybin="$(dirname "$(command -v python3)")"
run() { env -i HOME="$tmp/home" PATH="$pybin:/usr/bin:/bin" "$@"; }
mkdir -p "$tmp/home"
cd "$P"
ck "kit is not on PATH" "$(run bash -c 'command -v kit || echo none')" "none"

# 1. the registry's project-scope entry
reg="$tmp/installed_plugins.json"
cat >"$reg" <<JSON
{"version": 2, "plugins": {"core@principles": [
  {"scope": "project", "projectPath": "$tmp/elsewhere", "installPath": "$tmp/nowhere", "version": "9.9.9"},
  {"scope": "project", "projectPath": "$P", "installPath": "$core", "version": "0.1.0"}]}}
JSON
ck "registry: get" "$(run KIT_INSTALLED_PLUGINS="$reg" bin/kit get gate.check)" "bin/check"
ck "registry: spec-check runs on a sound spec" "$(run KIT_INSTALLED_PLUGINS="$reg" bin/kit spec-check --path openspec/specs >/dev/null 2>&1; echo $?)" "0"
mkdir -p openspec/specs/bad && printf '## Requirements\n\n### Requirement: Broken\nIt does things.\n' >openspec/specs/bad/spec.md
out="$(run KIT_INSTALLED_PLUGINS="$reg" bin/kit spec-check --path openspec/specs 2>&1)"; rc=$?
ck "registry: spec-check flags a broken spec (exit 1)" "$rc" "1"
ck "registry: ...and names the requirement" "$(grep -c "Broken" <<<"$out")" "1"
rm -rf openspec/specs/bad
ck "registry: from a worktree of the project" "$(cd .worktrees/w && run KIT_INSTALLED_PLUGINS="$reg" ../../bin/kit get gate.check 2>&1)" "bin/check"
# 2. a source checkout
ck "source checkout" "$(run KIT_INSTALLED_PLUGINS="$tmp/none.json" PRINCIPLES_DIR="$core/../.." bin/kit get gate.check)" "bin/check"
# 3. an explicit override
ck "\$KIT override" "$(run KIT="$core/bin/kit" bin/kit get gate.check)" "bin/check"
# nothing found: a clear error, exit 2
out="$(run KIT_INSTALLED_PLUGINS="$tmp/none.json" PRINCIPLES_DIR="$tmp/none" bin/kit get gate.check 2>&1)"; rc=$?
ck "nothing found: exit 2" "$rc" "2"
ck "nothing found: says what to do" "$(grep -c "claude plugin install core@principles" <<<"$out")" "1"

[ "$fails" -eq 0 ] && echo "shim.test: all passed" || { echo "shim.test: $fails failed"; exit 1; }
