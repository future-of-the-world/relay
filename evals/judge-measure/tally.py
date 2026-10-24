#!/usr/bin/env python3
"""Reads the --json file of a judge-measure eval run and says whether the judge model passes.

  python3 evals/judge-measure/tally.py <eval.json> --expect-model haiku|sonnet [--max-wrong 0] [--max-split 1]

The expected answer is the `expect: PASS|FAIL` line in each grader file's front matter (make.py writes it
from items.txt); the grader's name is never read for it. A grader file without it is not judged (exit 2).
Per question (one case each), per run, the majority of the 3 votes is the verdict. Printed:
  wrong verdicts   runs whose majority verdict is not the expected answer      (bar --max-wrong, 0-2)
  split items      items whose votes, over all runs, are not all alike          (bar --max-split, 0-3)
  wrong votes      single votes against the expected answer (information only)
and the cost. Exit 0: every question passes; 1: a bar is exceeded; 2: nothing is judged, no verdict
is printed (also for a file that cannot be read or has the wrong shape). A verdict needs every expected case, every item of it (items.txt lines, and the case's own
graders[]) and every run (runsPerCase) present, without `error`, and judged with 3 votes. Exit 2
otherwise: a grader not judged (no judgeVotes, or not 3: the tool returns a skipped judge as
passed=false, which would read as a right "no" and a wrong "yes"), a run that errored (the tool returns
`error` and `graders: []`), a missing case, item or run, a partial run, a skipped paid grader, or a
suite.judgeModel other than the one asked for.
Standard library only; no model is called.
"""
import argparse, json, os, re, sys


class NotJudged(Exception):
    pass


def load_expected(here=None):
    """{case name: number of items} from questions.json (the cases) and each case's items.txt."""
    here = here or os.path.dirname(os.path.abspath(__file__))
    out = {}
    with open(os.path.join(here, "questions.json"), encoding="utf-8") as f:
        names = list(json.load(f))
    for name in names:
        with open(os.path.join(here, name, "items.txt"), encoding="utf-8") as f:
            lines = f.read().split("\n")
        out[name] = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))
    return out


def load_answers(here=None):
    """{case name: {grader name: True for PASS, False for FAIL}} from the `expect:` line in the front
    matter of each grader file under <case>/graders/. A grader without a valid line is not judged."""
    here = here or os.path.dirname(os.path.abspath(__file__))
    out = {}
    with open(os.path.join(here, "questions.json"), encoding="utf-8") as f:
        names = list(json.load(f))
    for name in names:
        out[name] = {}
        gdir = os.path.join(here, name, "graders")
        for fn in sorted(os.listdir(gdir)):
            if not fn.endswith(".md"):
                continue
            with open(os.path.join(gdir, fn), encoding="utf-8") as f:
                lines = f.read().split("\n")
            front = lines[1:lines.index("---", 1)] if lines[0] == "---" and "---" in lines[1:] else []
            vals = [l.partition(":")[2].strip() for l in front if l.partition(":")[0].strip() == "expect"]
            if len(vals) != 1 or vals[0] not in ("PASS", "FAIL"):
                raise NotJudged(f"{name}/graders/{fn}: no `expect: PASS` or `expect: FAIL` line in the front matter")
            out[name][fn[:-3]] = vals[0] == "PASS"
    return out


def tally(data, expect_model, max_wrong=0, max_split=1, expected=None, answers=None):
    """Returns (exit code, lines). `expected` is {case name: item count}; None = no outside list,
    only what each case's own graders[] and runsPerCase say. `answers` is {case name: {grader name:
    expected verdict, True = PASS}} (load_answers); without it nothing says what is right."""
    if answers is None:
        raise NotJudged("no expected answers given (the `expect:` lines of the grader files)")
    suite = data.get("suite", {})
    if suite.get("judgeModel") != expect_model:
        raise NotJudged(f"suite.judgeModel is {suite.get('judgeModel')!r}, expected {expect_model!r}")
    if data.get("partial"):
        raise NotJudged(f"the run is partial: {data.get('partialReason', 'no partialReason given')}")
    lines, code = [], 0
    cost = judge_cost = 0.0
    cases = data.get("cases") or []
    if not cases:
        raise NotJudged("the file holds no cases")
    if expected:
        missing = [n for n in expected if n not in {c.get("name") for c in cases}]
        if missing:
            raise NotJudged("missing case(s): " + ", ".join(missing))
    for case in cases:
        items = {}   # grader name -> list of vote lists, one per run
        arms = case.get("arms") or {}
        if not arms or not any(arms.values()):
            raise NotJudged(f"{case['name']}: no runs")
        if case.get("name") not in answers:
            raise NotJudged(f"{case.get('name')}: no grader files with expected answers")
        known = answers[case["name"]]
        want_items = {g["name"] for g in case.get("graders", []) if g.get("type") == "llm"}
        for g in sorted(want_items - set(known)):
            raise NotJudged(f"{case['name']}: grader {g} has no stored expected answer")
        if expected and case["name"] in expected and len(want_items) != expected[case["name"]]:
            raise NotJudged(f"{case['name']}: {len(want_items)} item graders in the result, {expected[case['name']]} in items.txt")
        if not want_items:
            raise NotJudged(f"{case['name']}: no llm graders listed")
        for arm_name, runs in arms.items():
            want_runs = case.get("runsPerCase") or len(runs)
            if len(runs) != want_runs:
                raise NotJudged(f"{case['name']} ({arm_name}): {len(runs)} runs of {want_runs} expected")
            for n, run in enumerate(runs, 1):
                if run.get("error"):
                    raise NotJudged(f"{case['name']} ({arm_name} run {n}): the run errored ({str(run['error'])[:80]}), no graders judged")
                got = {g.get("name") for g in run.get("graders", [])}
                absent = sorted(want_items - got)
                if absent:
                    raise NotJudged(f"{case['name']} ({arm_name} run {n}): {len(absent)} of {len(want_items)} items not judged (first: {absent[0]})")
                if run.get("skippedPaidGraders"):
                    raise NotJudged(f"{case['name']} ({arm_name} run {n}): skippedPaidGraders (the cost cap stopped the judge)")
                cost += run.get("costUsd") or 0
                judge_cost += run.get("judgeCostUsd") or 0
                for g in run.get("graders", []):
                    if g["name"] not in want_items:
                        continue
                    votes = g.get("judgeVotes")
                    if not isinstance(votes, list) or len(votes) != 3:
                        raise NotJudged(f"{case['name']} {g['name']} (run {n}): not judged ({'no' if not votes else len(votes)} votes, 3 expected)")
                    items.setdefault(g["name"], []).append(votes)
        if sorted(items) != sorted(want_items):
            raise NotJudged(f"{case['name']}: judged items differ from the case's graders")
        wrong = split = wrong_votes = runs_total = 0
        for name, per_run in sorted(items.items()):
            want = known[name]
            flat = [v for votes in per_run for v in votes]
            runs_total += len(per_run)
            wrong_here = sum(1 for votes in per_run if (sum(votes) >= 2) != want)
            wrong += wrong_here
            wrong_votes += sum(1 for v in flat if v != want)
            if len(set(flat)) > 1:
                split += 1
            if wrong_here:
                lines.append(f"    wrong: {name} judged {wrong_here} of {len(per_run)} runs the wrong way")
        ok = wrong <= max_wrong and split <= max_split
        code = max(code, 0 if ok else 1)
        lines.append(f"{'PASS' if ok else 'FAIL'} {case['name']}: {wrong} wrong verdicts of {runs_total} (max {max_wrong}), "
                     f"{split} split items of {len(items)} (max {max_split}), {wrong_votes} wrong votes of {runs_total * 3}")
    lines.append(f"judge model {expect_model}; cost ${cost:.3f}, of which the judge ${judge_cost:.3f}")
    return code, lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json")
    ap.add_argument("--expect-model", required=True, choices=["haiku", "sonnet", "opus"])
    ap.add_argument("--max-wrong", type=int, default=0, choices=range(0, 3))
    ap.add_argument("--max-split", type=int, default=1, choices=range(0, 4))
    a = ap.parse_args()
    try:
        try:
            with open(a.json, encoding="utf-8") as f:
                data = json.load(f)
            code, lines = tally(data, a.expect_model, a.max_wrong, a.max_split, load_expected(), load_answers())
        except (OSError, ValueError) as e:   # unreadable file, bad UTF-8 or bad JSON (UnicodeDecodeError is a ValueError)
            raise NotJudged(f"cannot read {a.json}: {e}")
        except (KeyError, TypeError, AttributeError) as e:   # JSON of another shape than the eval tool writes
            raise NotJudged(f"{a.json} does not have the shape of an eval result ({type(e).__name__}: {e})")
    except NotJudged as e:
        print(f"tally: NOT JUDGED, no verdict: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
