# Measuring the meaning judge

The paid evals in `evals/plugin/` use `llm` graders (the eval tool's built-in judge, 3 votes, majority)
for meaning questions: does the reply report the planted defect? This folder measures that judge on
recorded replies before it gates anything. Nothing here runs in `bin/ci`.

- `questions.json`: per question, the production grader, its code graders, and the regexes make.py uses.
- `measure-<question>/items.txt`: `yes|no <recorded reply> [into <template>]`. A template is a real full
  reply with one `{{FINDING}}` slot; the recorded reply's finding lines go there, so every item has the
  length and form of a real reply (1,000+ characters). A template never mentions the finding outside
  its slot.
- `make.py` writes `judged/NN.txt` and `graders/<yes|no>--NN-name.md` (the grader body is the production
  rubric byte for byte); `make.py --check` (also run by `evals/plugin/graders.test.sh`) fails on any
  difference, a short item, an item the code check refuses, a template that mentions the finding, or a
  recorded wrong reply that is in no items.txt, or a known wrong answer (`known_wrong` in questions.json:
  wrong replies the code graders let through, so only the judge refuses them) that no "no" item says.
- `tally.py` reads the `--json` of a measurement run; exit 2 and no verdict unless every case, every item
  (items.txt) and every run is present, without `error`, and judged with 3 votes.
- The measurement prompts set `max_turns: 1` and nothing else to bound the agent: `allowed_tools: []` is the
  tool's default (it restricts nothing), so it is not set.

Run (paid, 58 items, 870 votes; real cost on 2026-10-22: $0.49 on haiku, about $7.5-8 on sonnet, which is
~17x haiku per vote; start only after review), one run per judge model. The ceiling is not hard: runs already
started at `-j 4` finish after it trips (a $4 ceiling ran to $6.32), and a run stopped at the ceiling is partial,
so tally answers NOT JUDGED. Set it above the expected cost:

    claude plugin eval . --eval-dir evals/judge-measure --runs 5 -j 4 --judge-model haiku  --ablation none --no-publish --trust-plugin --scaffold --max-cost-usd 2 --json <scratch>/measure-haiku.json
    claude plugin eval . --eval-dir evals/judge-measure --runs 5 -j 4 --judge-model sonnet --ablation none --no-publish --trust-plugin --scaffold --max-cost-usd 10 --json <scratch>/measure-sonnet.json
    python3 evals/judge-measure/tally.py <scratch>/measure-haiku.json --expect-model haiku

A question passes when wrong verdicts <= 0 and split items <= 1 (`--max-wrong`, `--max-split`).
Result of 2026-10-22: haiku failed the off-by-one question (7 wrong verdicts of 120 on two right items; it keys
on words of the rubric's FAIL clause), sonnet passed all four questions (0 wrong of 870 votes). So sonnet is
the default judge of `bin/ci` (`EVALS_JUDGE_MODEL`, still overridable, e.g. `EVALS_JUDGE_MODEL=haiku bin/ci`).
Cost: sonnet is about 17x haiku per vote; a sonnet-judged batch is about $0.34 (haiku about $0.02). A grader that
fails on sonnet too comes out of its case until its rubric is reworded and measured again. The eval
writes `results/` here (ignored by git); `git status --short` must be empty afterwards.
