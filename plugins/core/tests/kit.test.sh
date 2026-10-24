#!/usr/bin/env bash
# Tests for `kit get`, `kit dump` and `kit path`.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"; kit="$here/../bin/kit"
tmp="$(cd "$(mktemp -d)" && pwd -P)"; trap 'rm -rf "$tmp"' EXIT
fails=0
ck() { [ "$2" = "$3" ] && echo "ok   $1" || { echo "FAIL $1: got [$2] want [$3]"; fails=$((fails+1)); }; }
# rc <command...>: the exit code
rc() { "$@" >/dev/null 2>&1; echo $?; }
export KIT_INSTALLED_PLUGINS="$tmp/no-such-registry.json"
cd "$tmp" && git init -q -b master . && git -c user.name=t -c user.email=t@t commit -q --allow-empty -m i
want="kit: no .claude/kit.toml in $tmp: this project has no bindings file (on a worktree branch, merge the default branch in first)"
ck "no file: message" "$("$kit" get gate.check 2>&1)" "$want"
ck "no file: exit 1" "$(rc "$kit" get gate.check)" "1"
ck "no file: --default does not cover a missing file" "$("$kit" get --default x gate.check 2>&1)" "$want"
ck "no file: --default exit 1" "$(rc "$kit" get --default x gate.check)" "1"
ck "no file: dump is an error too" "$(rc "$kit" dump)" "1"
ck "no file: packet is an error too" "$(rc "$kit" packet --check demo)" "1"
ck "no file: spec-check is an error too" "$(rc "$kit" spec-check --path .)" "1"
mkdir .claude && printf '[gate]\ncheck = "bin/check"\n[project]\nstack_skills = ["a","b"]\nok = true\n[x]\ny = 1\n' >.claude/kit.toml
ck "scalar" "$("$kit" get gate.check)" "bin/check"
ck "scalar: exit 0" "$(rc "$kit" get gate.check)" "0"
ck "list" "$("$kit" get project.stack_skills | tr '\n' ,)" "a,b,"
ck "bool" "$("$kit" get project.ok)" "true"
ck "table is json" "$("$kit" get x)" '{"y": 1}' || true
ck "missing key" "$("$kit" get gate.ci 2>&1)" "kit: missing key 'gate.ci' (no such key in $tmp/.claude/kit.toml)"
ck "missing key: exit 1" "$(rc "$kit" get gate.ci)" "1"
ck "default" "$("$kit" get --default none gate.ci)" "none"
ck "default: exit 0" "$(rc "$kit" get --default none gate.ci)" "0"
ck "present key ignores --default" "$("$kit" get --default none gate.check)" "bin/check"
ck "no key given: usage, exit 2" "$(rc "$kit" get)" "2"
printf '[gate\n' >.claude/kit.toml.bad && mv .claude/kit.toml .claude/kit.toml.good && mv .claude/kit.toml.bad .claude/kit.toml
ck "broken file: exit 2" "$(rc "$kit" get gate.check)" "2"
ck "broken file: names the file" "$("$kit" get gate.check 2>&1 | head -c 4)" "kit:"
mv .claude/kit.toml.good .claude/kit.toml
git worktree add -q .wt/a -b wt/a && mkdir -p .wt/a/sub && cd .wt/a/sub
ck "from a worktree subdir, the worktree's own file is used (it has none)" "$(rc "$kit" get gate.check)" "1"
ck "...and the message names the worktree" "$("$kit" get gate.check 2>&1 | grep -c "$tmp/.wt/a")" "1"
cd "$tmp" && ck "dump" "$("$kit" dump | jq -c .gate)" '{"check":"bin/check"}'
# Python 3.9 (the macOS system python) has no tomllib: kit reads the file through the shared fallback reader
if [ -x /usr/bin/python3 ]; then
  ck "python 3.9: get" "$(/usr/bin/python3 "$kit" get gate.check 2>&1)" "bin/check"
  ck "python 3.9: list" "$(/usr/bin/python3 "$kit" get project.stack_skills | tr '\n' ,)" "a,b,"
  ck "python 3.9: dump" "$(/usr/bin/python3 "$kit" dump | jq -c .gate)" '{"check":"bin/check"}'
  mv .claude/kit.toml .claude/kit.toml.good && printf '[gate\n' >.claude/kit.toml
  ck "python 3.9: broken file exits 2" "$(rc /usr/bin/python3 "$kit" get gate.check)" "2"
  mv .claude/kit.toml.good .claude/kit.toml
fi
# kit path: source layout, then an installed layout (<market>/<plugin>/<version>/)
plugins="$(cd "$here/../.." && pwd -P)"
ck "path, sibling plugin" "$("$kit" path product/scripts/measure.mjs)" "$plugins/product/scripts/measure.mjs"
ck "path, core itself" "$("$kit" path core/lib/kit_packet.py)" "$plugins/core/lib/kit_packet.py"
ck "path, missing file" "$("$kit" path openspec/nope 2>&1 | head -c 20)" "kit: no file 'opensp"
ck "path, no escape" "$("$kit" path 'openspec/../core/bin/kit' >/dev/null 2>&1; echo $?)" "1"
# kit path in the installed layout (<market>/<plugin>/<version>/): the version
# installed for THIS project, never "the newest".
inst="$tmp/market"; mkdir -p "$inst/core/0.1.0" "$inst/openspec/0.1.0/skills/x" "$inst/openspec/0.2.0/skills/x" "$inst/openspec/0.10.0/skills/x"
cp -R "$here/../bin" "$here/../lib" "$inst/core/0.1.0/"
for v in 0.1.0 0.2.0 0.10.0; do echo "$v" >"$inst/openspec/$v/skills/x/SKILL.md"; done
ikit="$inst/core/0.1.0/bin/kit"
real() { (cd "$1" && pwd -P); }
ck "path, no registry: the same version as the running core" "$("$ikit" path openspec/skills/x/SKILL.md)" "$(real "$inst")/openspec/0.1.0/skills/x/SKILL.md"
reg="$tmp/installed_plugins.json"; export KIT_INSTALLED_PLUGINS="$reg"
other="$tmp/other-project"; mkdir -p "$other"
cat >"$reg" <<JSON
{"version": 2, "plugins": {"openspec@market": [
  {"scope": "user", "installPath": "$inst/openspec/0.2.0", "version": "0.2.0"},
  {"scope": "project", "projectPath": "$other", "installPath": "$inst/openspec/0.10.0", "version": "0.10.0"},
  {"scope": "project", "projectPath": "$tmp", "installPath": "$inst/openspec/0.1.0", "version": "0.1.0"}]}}
JSON
ck "path, project-scope install of this project wins over newer ones" "$("$ikit" path openspec/skills/x/SKILL.md)" "$(real "$inst")/openspec/0.1.0/skills/x/SKILL.md"
ck "path, from a worktree of the project, the same" "$(cd "$tmp/.wt/a" && "$ikit" path openspec/skills/x/SKILL.md)" "$(real "$inst")/openspec/0.1.0/skills/x/SKILL.md"
cat >"$reg" <<JSON
{"version": 2, "plugins": {"openspec@market": [
  {"scope": "project", "projectPath": "$other", "installPath": "$inst/openspec/0.10.0", "version": "0.10.0"},
  {"scope": "user", "installPath": "$inst/openspec/0.2.0", "version": "0.2.0"}]}}
JSON
ck "path, another project's install is not used; the user-scope one is" "$("$ikit" path openspec/skills/x/SKILL.md)" "$(real "$inst")/openspec/0.2.0/skills/x/SKILL.md"
printf '{"version": 2, "plugins": {}}' >"$reg"
ck "path, empty registry: the core's own version" "$("$ikit" path openspec/skills/x/SKILL.md)" "$(real "$inst")/openspec/0.1.0/skills/x/SKILL.md"
rm -rf "$inst/openspec/0.1.0"
ck "path, nothing for this version: an error, not the newest" "$("$ikit" path openspec/skills/x/SKILL.md 2>&1 | head -c 20)" "kit: no file 'opensp"
ck "path, that error exits 1" "$(rc "$ikit" path openspec/skills/x/SKILL.md)" "1"
[ "$fails" -eq 0 ] && echo "kit.test: all passed" || { echo "kit.test: $fails failed"; exit 1; }
