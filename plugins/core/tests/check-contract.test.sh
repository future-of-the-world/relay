#!/usr/bin/env bash
# Contract test for a project's check script (README, "The check-script
# contract"): the exact behaviour the shared worker and fixer rely on.
#
#   plugins/core/tests/check-contract.test.sh
#       runs it against the eval fixture's bin/check (a temporary copy);
#   KIT_CONTRACT_PROJECT=<clean checkout or worktree> plugins/core/tests/check-contract.test.sh
#       runs it against that project's own gate.check. It adds the probe change
#       openspec/changes/contract-probe and, for the tests mode, two probe test
#       files named by CONTRACT_PASS_FILE and CONTRACT_FAIL_FILE (paths relative
#       to the project; the files must exist: one passing, one failing); both
#       probes and the .ci/check state are removed at the end. Without the two
#       variables the tests-mode cases are skipped and say so.
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd -P)"
fixture="$here/../../../evals/plugin/fixture"
fails=0
ck() { [ "$2" = "$3" ] && echo "ok   $1" || { echo "FAIL $1: got [$2] want [$3]"; fails=$((fails + 1)); }; }
has() { grep -qE -- "$2" <<<"$3" && echo "ok   $1" || { echo "FAIL $1: expected /$2/ in: $3"; fails=$((fails + 1)); }; }
hasnt() { grep -qE -- "$2" <<<"$3" && { echo "FAIL $1: unexpected /$2/ in: $3"; fails=$((fails + 1)); } || echo "ok   $1"; }

if [ -n "${KIT_CONTRACT_PROJECT:-}" ]; then
  P="$(cd "$KIT_CONTRACT_PROJECT" && pwd -P)"
  tmp=""
  cleanup() { rm -rf "$P/openspec/changes/contract-probe" "$P/.ci/check"; }
else
  tmp="$(cd "$(mktemp -d)" && pwd -P)"
  P="$tmp/project"
  mkdir -p "$P" && cp -R "$fixture/." "$P/" && cd "$P" && git init -q -b master . \
    && git add -A && git -c user.name=t -c user.email=t@t commit -q -m fixture || { echo "check-contract.test: cannot build the fixture copy" >&2; exit 1; }
  cleanup() { rm -rf "$tmp"; }
  CONTRACT_PASS_FILE="src/probe-pass.test.ts"; CONTRACT_FAIL_FILE="src/probe-fail.test.ts"
  printf "import { expect, test } from 'bun:test';\ntest('probe passes', () => { expect(1).toBe(1); });\n" >"$P/$CONTRACT_PASS_FILE"
  printf "import { expect, test } from 'bun:test';\ntest('probe fails', () => { expect(1).toBe(2); });\n" >"$P/$CONTRACT_FAIL_FILE"
fi
trap cleanup EXIT

cd "$P" || exit 1
check="$("$here/../bin/kit" get gate.check)" || exit 1
[ -x "$P/$check" ] || { echo "check-contract.test: $P/$check is not executable" >&2; exit 1; }

c=openspec/changes/contract-probe
mkdir -p "$c"
cat >"$c/tasks.md" <<'TASKS'
## 1. Probes

Wave 1 · depends on: none

- [ ] 1.1 Green. Reads: none. Tests: none. Files: none. Check: `true`
- [ ] 1.2 Red. Reads: none. Tests: none. Files: none. Check: `echo probe-finding >&2; false`
- [ ] 1.3 Hangs. Reads: none. Tests: none. Files: none. Check: `sleep 30`
- [ ] 1.4 Flips. Reads: none. Tests: none. Files: none. Check: `test -f .ci/probe-ok`
- [ ] 1.5 Third. Reads: none. Tests: none. Files: none. Check: `false`
TASKS
mkdir -p .ci
run() { "./$check" "$@" 2>&1; }
code() { "./$check" "$@" >/dev/null 2>&1; echo $?; }

# Green: quiet, exit 0.
out="$(run contract-probe 1.1)"; rc=$?
ck "green: exit 0" "$rc" "0"
has "green: says passed" "passed" "$out"
ck "green: quiet (at most 3 lines)" "$([ "$(wc -l <<<"$out")" -le 3 ] && echo yes || echo no)" "yes"
hasnt "green: no stop word" "BUDGET SPENT|HUNG|TIME BUDGET SPENT" "$out"

# Red: exit 1, the finding, the round, a log that exists; BUDGET SPENT only on the third failure in a row.
out="$(run contract-probe 1.2)"; rc=$?
ck "red: exit 1" "$rc" "1"
has "red: shows the finding" "probe-finding|FAILED" "$out"
has "red: round 1 of 3" "round 1 of 3" "$out"
hasnt "red: no BUDGET SPENT on the first failure" "BUDGET SPENT" "$out"
log="$(sed -nE 's/.*log: ([^)]+)\).*/\1/p' <<<"$out" | head -1)"
ck "red: the log path it names exists" "$([ -f "$log" ] && echo yes || echo no)" "yes"
out="$(run contract-probe 1.2 --failed)"; rc=$?
ck "red, --failed: accepted, exit 1" "$rc" "1"
has "red: round 2 of 3" "round 2 of 3" "$out"
hasnt "red: no BUDGET SPENT on the second failure" "BUDGET SPENT" "$out"
out="$(run contract-probe 1.2)"
has "red: BUDGET SPENT on the third failure in a row" "BUDGET SPENT" "$out"

# A pass resets the count.
rm -f .ci/probe-ok
run contract-probe 1.4 >/dev/null; run contract-probe 1.4 >/dev/null
touch .ci/probe-ok; ck "flip: a pass exits 0" "$(code contract-probe 1.4)" "0"
rm -f .ci/probe-ok
run contract-probe 1.4 >/dev/null; out="$(run contract-probe 1.4)"
hasnt "a pass resets the count (two more failures: no BUDGET SPENT)" "BUDGET SPENT" "$out"
rm -f .ci/probe-ok

# A hung check is killed and reported.
start=$(date +%s)
out="$(CHECK_TIMEOUT=1 run contract-probe 1.3)"; rc=$?
ck "hang: exit 1" "$rc" "1"
has "hang: says HUNG" "HUNG" "$out"
ck "hang: killed within 15 s" "$([ $(( $(date +%s) - start )) -lt 15 ] && echo yes || echo no)" "yes"

# The time budget.
out="$(CHECK_WORKER_MINUTES=0 run contract-probe 1.5)"
has "time budget: TIME BUDGET SPENT (on a failing run)" "TIME BUDGET SPENT" "$out"
out="$(CHECK_WORKER_MINUTES=0 run contract-probe 1.1)"; rc=$?
has "time budget: also on a green run" "TIME BUDGET SPENT" "$out"
ck "time budget: a green run still exits 0" "$rc" "0"

# Usage and unreadable tasks exit 2.
ck "no arguments: exit 2" "$(code)" "2"
ck "unknown task: exit 2" "$(code contract-probe 9.9)" "2"
ck "unknown change: exit 2" "$(code no-such-change 1.1)" "2"

# From a subfolder of the checkout the script still works at the checkout's root.
mkdir -p sub && ck "from a subfolder" "$(cd sub && "../$check" contract-probe 1.1 >/dev/null 2>&1; echo $?)" "0"

# Review-fix mode.
if [ -n "${CONTRACT_PASS_FILE:-}" ] && [ -n "${CONTRACT_FAIL_FILE:-}" ]; then
  ck "--tests, passing file: exit 0" "$(code --tests "$CONTRACT_PASS_FILE")" "0"
  out="$(run --tests "$CONTRACT_FAIL_FILE")"; rc=$?
  ck "--tests, failing file: exit 1" "$rc" "1"
  has "--tests: names the failing file" "$CONTRACT_FAIL_FILE" "$out"
  ck "--tests --failed: accepted, exit 1" "$(code --tests "$CONTRACT_FAIL_FILE" --failed)" "1"
  out="$(run --tests "$CONTRACT_FAIL_FILE")"
  has "--tests: BUDGET SPENT on the third failure in a row" "BUDGET SPENT" "$out"
  ck "--tests with no file: exit 2" "$(code --tests)" "2"
else
  echo "skip --tests cases: set CONTRACT_PASS_FILE and CONTRACT_FAIL_FILE"
fi

[ "$fails" -eq 0 ] && echo "check-contract.test: all passed" || { echo "check-contract.test: $fails failed"; exit 1; }
