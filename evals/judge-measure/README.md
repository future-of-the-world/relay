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
- Each case holds `answers.json`, `{grader name: "PASS"|"FAIL"}` (make.py writes it from the yes/no of items.txt);
  `tally.py` reads it, never the grader's name, and a grader without an entry is not judged. It is not in the
  grader file: the eval tool refuses a grader file with a key other than type, focus, weight, arm.
- `tally.py` reads the `--json` of a measurement run; exit 2 and no verdict unless every case, every item
  (items.txt) and every run is present, without `error`, and judged with 3 votes.
- The measurement prompts set `max_turns: 1` and nothing else to bound the agent: `allowed_tools: []` is the
  tool's default (it restricts nothing), so it is not set.

Run (paid, 58 items, 870 votes; start only after review), one run per judge model. Cost: not measured yet in
relay's own records (`bin/paid-cost` reads only the stored batches of `bin/ci`, a different eval set at about 30
times the cost per run, so do not use it for these runs). Real figures of 2026-10-22: $0.49 on haiku (one full
run) and $6.32 on sonnet for a run stopped partial at a $4 ceiling at `-j 4`; a full sonnet run costs more
(about $7.5-8, not measured in full). The ceiling is not hard: runs in flight finish after it trips, and a run
stopped at the ceiling is partial, so tally answers NOT JUDGED. With no stored record of these runs, use `-j 1`
and set the ceiling (`--max-cost-usd`) at your cap, above the expected cost (the overshoot is then one run, about
$0.03):

    claude plugin eval . --eval-dir evals/judge-measure --runs 5 -j 1 --judge-model haiku  --ablation none --no-publish --trust-plugin --scaffold --max-cost-usd <cap, above 0.5> --json <scratch>/measure-haiku.json
    claude plugin eval . --eval-dir evals/judge-measure --runs 5 -j 1 --judge-model sonnet --ablation none --no-publish --trust-plugin --scaffold --max-cost-usd <cap, above 8> --json <scratch>/measure-sonnet.json
    python3 evals/judge-measure/tally.py <scratch>/measure-haiku.json --expect-model haiku

A question passes when wrong verdicts <= 0 and split items <= 1 (`--max-wrong`, `--max-split`).
Result of 2026-10-22: haiku failed the off-by-one question (7 wrong verdicts of 120 on two right items; it keys
on words of the rubric's FAIL clause), sonnet passed all four questions (0 wrong of 870 votes). So sonnet is
the default judge of `bin/ci` (`EVALS_JUDGE_MODEL`, still overridable, e.g. `EVALS_JUDGE_MODEL=haiku bin/ci`).
Re-measured 2026-10-27 after the FAIL clause dropped "stays within size" and "as the doc says" (`--case measure-off-by-one --runs 5 -j 1`, haiku, $0.06): 0 wrong verdicts of 120 but 2 split items (yes-03, yes-06; max 1), 4 wrong votes of 360: still FAIL by the bar above. Re-measured with `--runs 20 -j 1`, haiku, $0.25: PASS, 0 wrong verdicts of 480, 1 split item of 24 (yes-04; max 1), 4 wrong votes of 1440; yes-03, yes-05, yes-06 PASS in every run. Sonnet (the judge of `bin/ci`) on the new wording, `--case measure-off-by-one -j 1`, 5 runs ($1.02) and 14 runs ($2.83), 19 runs in all (the $4 cap allowed 19, not 20), read as one file: PASS, 0 wrong verdicts of 456, 0 split items of 24, 0 wrong votes of 1368; no--12, no--16, no--24 FAIL in every run.
Cost: see above; a sonnet-judged batch costs more than a haiku one per vote (the ledger and `bin/paid-cost estimate` hold the measured figures). A grader that
fails on sonnet too comes out of its case until its rubric is reworded and measured again. The eval
writes `results/` here (ignored by git); `git status --short` must be empty afterwards.

`measure-ru-style` (the it-terms-ru judge `gender-and-opener`; whole recorded replies with no template, short, see `whole_reply` and
`min_len` in questions.json): result of 2026-10-25 on sonnet, `--case measure-ru-style --runs 3 -j 1`, $0.095: the 6 live bad replies
of 25 Oct (feminine branch, the "project not named" opener, or both) were judged FAIL and the owner-approved good reply PASS in all
3 runs, 21 of 21 verdicts and 63 of 63 votes right. tally.py wants every case, so for this one case read the `--json` by hand.
Re-measured 2026-10-26 after the rubric named gate and the gloss case (9 items, `--case measure-ru-style --runs 3 -j 1`, $0.185):
the 7 bad replies, among them run 3 of the 26 Oct paid run ("Gate, то есть ... проверка, тоже зелёная"), were judged FAIL and the 2
good ones, among them run 2 of that run (a pronoun after a gloss), PASS in all 3 runs: 27 of 27 verdicts, 81 of 81 votes right.
