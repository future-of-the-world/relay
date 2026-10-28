#!/usr/bin/env bash
# A repo whose strip_marks() is meant to remove all 32 ASCII punctuation marks. The review finding F1 says it
# removes only 9. Branch wt/marks holds a PARTIAL fix: the MARKS list now looks complete to a reader but still
# lacks "[" and "]" (and the only new test covers neither), so a one-line sketch of the failing case still fails.
# The workspace stays on wt/marks. The review JSON (recorded by relay itself) and the fixer's note sit in .review/ beside the repo files.
set -euo pipefail
G=(git -c user.name=f -c user.email=f@x)
git init -q -b master . 
cat > marks.py <<'PY'
def strip_marks(text: str) -> str:
    """Remove every ASCII punctuation mark (all 32 of string.punctuation) from text."""
    return "".join(c for c in text if c not in ".,;:!?'\"()-")
PY
cat > test_marks.py <<'PY'
from marks import strip_marks


def test_full_stop():
    assert strip_marks("a.b") == "ab"
PY
git add -A && "${G[@]}" commit -qm "strip_marks, first version"
BASE=$(git rev-parse HEAD)
git checkout -q -b wt/marks
cat > marks.py <<'PY'
MARKS = ".,;:!?'\"()-_/\\@#$%&*+<=>^`{|}~"


def strip_marks(text: str) -> str:
    """Remove every ASCII punctuation mark (all 32 of string.punctuation) from text."""
    return "".join(c for c in text if c not in MARKS)
PY
cat >> test_marks.py <<'PY'


def test_underscore_and_at():
    assert strip_marks("a_b@c") == "abc"
PY
git add -A && "${G[@]}" commit -qm "Fix F1: strip_marks covers more marks"
mkdir -p .review
cat > .review/fix.md <<'MD'
Fixed F1: strip_marks now takes its marks from the MARKS list.
Tests: test_marks.py::test_underscore_and_at. Commit wt/marks.
MD
cat > .review/spec-1.toml <<TOML
report = "$PWD/.review/spec-1.json"
reviewed = "$BASE"
base = "master"
scope = '''
marks.py and its test, range master..wt/marks before the fix.
'''
notes = '''
none
'''

[[finding]]
id = "F1"
path = "marks.py"
line = 3
severity = "MEDIUM"
kind = "inside"
summary = "strip_marks leaves most of the 32 ASCII punctuation marks in the text"
failing_case = '''
strip_marks(string.punctuation) returns "[]" instead of "", and strip_marks("[a]_\`b\`") keeps the brackets;
every one of the 32 marks in string.punctuation must be removed, today only 9 are.
'''
pass_cases = '''
1. strip_marks(string.punctuation) == "".
2. strip_marks("[a]_\`b\`") == "ab".
3. strip_marks("a.b") == "ab" (still works).
'''
details = '''
CONFIRMED: the filter in marks.py:3 lists 9 marks. Size: 5 agent minutes.
'''
TOML
relay check record review --input .review/spec-1.toml >/dev/null
rm .review/spec-1.toml
