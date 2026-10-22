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
  recorded wrong reply that is in no items.txt.
- `tally.py` reads the `--json` of a measurement run; exit 2 and no verdict when a grader was not judged.

Run (paid, about $0.90 on haiku, $2.55 on sonnet; start only after review), one run per judge model:

    claude plugin eval . --eval-dir evals/judge-measure --runs 5 -j 4 --judge-model haiku  --ablation none --no-publish --trust-plugin --scaffold --max-cost-usd 4 --json <scratch>/measure-haiku.json
    claude plugin eval . --eval-dir evals/judge-measure --runs 5 -j 4 --judge-model sonnet --ablation none --no-publish --trust-plugin --scaffold --max-cost-usd 4 --json <scratch>/measure-sonnet.json
    python3 evals/judge-measure/tally.py <scratch>/measure-haiku.json --expect-model haiku

A question passes when wrong verdicts <= 0 and split items <= 1 (`--max-wrong`, `--max-split`). If haiku
fails any question, sonnet judges the whole batch: `EVALS_JUDGE_MODEL=sonnet bin/ci`. A grader that
fails on sonnet too comes out of its case until its rubric is reworded and measured again. The eval
writes `results/` here (ignored by git); `git status --short` must be empty afterwards.
