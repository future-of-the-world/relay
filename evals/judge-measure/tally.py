#!/usr/bin/env python3
"""Reads the --json file of a judge-measure eval run and says whether the judge model passes.

  python3 evals/judge-measure/tally.py <eval.json> --expect-model haiku|sonnet [--max-wrong 0] [--max-split 1]

The expected answer comes from the grader name: yes--NN-... must be judged PASS, no--NN-... FAIL.
Per question (one case each), per run, the majority of the 3 votes is the verdict. Printed:
  wrong verdicts   runs whose majority verdict is not the expected answer      (bar --max-wrong, 0-2)
  split items      items whose votes, over all runs, are not all alike          (bar --max-split, 0-3)
  wrong votes      single votes against the expected answer (information only)
and the cost. Exit 0: every question passes; 1: a bar is exceeded; 2: nothing is judged, no verdict
is printed. Exit 2 when a grader was not judged (no judgeVotes, or not 3: the tool returns a skipped
judge as passed=false, which would read as a right "no" and a wrong "yes"), when the run is partial
or skipped a paid grader, or when suite.judgeModel is not the model asked for.
Standard library only; no model is called.
"""
import argparse, json, re, sys


class NotJudged(Exception):
    pass


def tally(data, expect_model, max_wrong=0, max_split=1):
    """Returns (exit code, lines)."""
    suite = data.get("suite", {})
    if suite.get("judgeModel") != expect_model:
        raise NotJudged(f"suite.judgeModel is {suite.get('judgeModel')!r}, expected {expect_model!r}")
    if data.get("partial"):
        raise NotJudged(f"the run is partial: {data.get('partialReason', 'no partialReason given')}")
    lines, code = [], 0
    cost = judge_cost = 0.0
    for case in data.get("cases", []):
        items = {}   # grader name -> list of vote lists, one per run
        for arm_name, runs in case.get("arms", {}).items():
            for n, run in enumerate(runs, 1):
                if run.get("skippedPaidGraders"):
                    raise NotJudged(f"{case['name']} ({arm_name} run {n}): skippedPaidGraders (the cost cap stopped the judge)")
                cost += run.get("costUsd") or 0
                judge_cost += run.get("judgeCostUsd") or 0
                for g in run.get("graders", []):
                    if not re.match(r"^(yes|no)--", g["name"]):
                        continue
                    votes = g.get("judgeVotes")
                    if not isinstance(votes, list) or len(votes) != 3:
                        raise NotJudged(f"{case['name']} {g['name']} (run {n}): not judged ({'no' if not votes else len(votes)} votes, 3 expected)")
                    items.setdefault(g["name"], []).append(votes)
        wrong = split = wrong_votes = runs_total = 0
        for name, per_run in sorted(items.items()):
            want = name.startswith("yes--")
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
        code, lines = tally(json.load(open(a.json, encoding="utf-8")), a.expect_model, a.max_wrong, a.max_split)
    except NotJudged as e:
        print(f"tally: NOT JUDGED, no verdict: {e}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
