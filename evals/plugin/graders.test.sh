#!/usr/bin/env bash
# Proof that the eval graders can tell a good reply from a bad one. The evals
# cannot run on every machine (and cost money), so each regex grader is checked
# here against recorded replies, with node's RegExp (the grader's own dialect):
#
#   evals/<case>/recorded/good/*.txt           replies that must pass EVERY regex grader of the case
#   evals/<case>/recorded/bad/<grader>__*.txt  replies that must FAIL the grader named before `__`
#
# Every regex grader needs at least one bad reply, so a grader changed (or
# written) without proof that it fails a deliberately wrong answer is refused.
# (Rule of review 2, M5: a grader may change only together with such proof.)
#   evals/plugin/graders.test.sh
set -uo pipefail
cd "$(dirname "$0")" || exit 1
command -v node >/dev/null 2>&1 || { echo "graders.test: node is not installed (brew install node)" >&2; exit 1; }
exec python3 -I - <<'PY'
import glob, json, os, re, subprocess, sys

def grader(path):
    text = open(path, encoding="utf-8").read().split("\n")
    if text[0] != "---" or "---" not in text[1:]:
        raise SystemExit(f"FAIL {path}: no front matter")
    meta = {}
    for line in text[1:text.index("---", 1)]:
        k, _, v = line.partition(":")
        v = v.strip()
        meta[k.strip()] = json.loads(v) if v.startswith('"') else v
    return meta

def matches(meta, reply):
    js = "const [p,f,t]=JSON.parse(require('fs').readFileSync(0,'utf8'));process.stdout.write(String(new RegExp(p,f).test(t)))"
    out = subprocess.run(["node", "-e", js], input=json.dumps([meta["pattern"], meta.get("flags", ""), reply]),
                         capture_output=True, text=True, check=True).stdout
    return out == "true"

fails = 0
def ok(msg): print("ok   ", msg)
def bad(msg):
    global fails
    fails += 1
    print("FAIL ", msg)

for case in sorted(d for d in glob.glob("*/") if os.path.isdir(d + "graders")):
    case = case.rstrip("/")
    graders = {}
    for p in sorted(glob.glob(f"{case}/graders/*.md")):
        meta = grader(p)
        if meta.get("type") == "regex":
            graders[os.path.basename(p)[:-3]] = meta
    for name in graders:
        recorded = glob.glob(f"{case}/recorded/bad/{name}__*.txt")
        ok(f"{case}/{name}: {len(recorded)} bad reply(ies) recorded") if recorded else bad(f"{case}/{name}: no bad reply recorded (recorded/bad/{name}__<label>.txt)")
    for p in sorted(glob.glob(f"{case}/recorded/good/*.txt")):
        reply = open(p, encoding="utf-8").read()
        for name, meta in graders.items():
            ok(f"{p} passes {name}") if matches(meta, reply) else bad(f"{p} must pass {name}")
    for p in sorted(glob.glob(f"{case}/recorded/bad/*.txt")):
        name = os.path.basename(p).split("__")[0]
        if name not in graders:
            bad(f"{p}: no regex grader named {name}")
            continue
        ok(f"{p} fails {name}") if not matches(graders[name], open(p, encoding="utf-8").read()) else bad(f"{p} must FAIL {name}")
    cfg = open(f"{case}/prompt.md", encoding="utf-8").read() if os.path.exists(f"{case}/prompt.md") else ""
    casefile = open(f"{case}/case.yaml", encoding="utf-8").read() if os.path.exists(f"{case}/case.yaml") else ""
    runs = re.search(r"^runs:\s*(\d+)", cfg + "\n" + casefile, re.M)
    ok(f"{case}: runs: {runs.group(1)}") if runs and int(runs.group(1)) >= 3 else bad(f"{case}: set runs: 3 (one run cannot show a flaky agent)")

print("graders.test: all passed" if not fails else f"graders.test: {fails} failed")
sys.exit(1 if fails else 0)
PY
