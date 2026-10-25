# Working style
> Verify against the real system before writing a claim, in a reply to the owner as much as in docs and code; a regression test must fail with the fix disabled; scratch files in the session scratchpad.

- Verify against the real system (a test, a live read-only API call, the
  actual file) before writing a claim into docs or code, and before a
  recommendation to the owner.
- A recommendation says what it rests on: a measured number ("measured: 17 of
  28 open items overlap a running branch") or "not measured: a guess". When a
  cheap measurement exists (a script over the queue, git or the ledger), run it
  before the reply, not after the owner's second question. Live case, 24 Oct:
  the front claimed queue conflicts came from one test file; a one-minute dry
  run, made only on the 6th owner round, showed 17 of 28 overlaps came through
  other files.
- A view changes on new evidence, not on the owner's push. When the owner
  disagrees, say what the evidence is and whether it moved; change the view
  only if it did, and name the new evidence.
- For a regression test, check that it fails with the fix disabled.
- Keep scratch files in the session scratchpad, not the repo or `/tmp`.

