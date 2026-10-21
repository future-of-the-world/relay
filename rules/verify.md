# Working style
> Verify against the real system before writing a claim; a regression test must fail with the fix disabled; scratch files in the session scratchpad.

- Verify against the real system (a test, a live read-only API call, the
  actual file) before writing a claim into docs or code.
- For a regression test, check that it fails with the fix disabled.
- Keep scratch files in the session scratchpad, not the repo or `/tmp`.

