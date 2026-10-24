# Python
> Relay's Python is standard library at run time, typed, formatted before every commit, and tested away from live files; anything beyond a thin wrapper is Python, not bash.

- Run time uses the standard library only. The tools the gate needs (formatter, linter, type checker) are
  pinned and installed by the install script, never imported by relay's own programs.
- Every new or changed function has types. A record that several programs read (a queue item, a verdict)
  has one typed record and one parser, shared by all of them. Data relay does not control (Claude Code
  transcripts, hook input) goes through one checking parser at the boundary; past it, the code trusts
  the typed record and does not re-check.
- The formatter and the auto-fix step run before every commit, as the gate's step; the linter is there
  to report bugs, not style.
- Run other programs with `subprocess` and a list of arguments, never `shell=True`. Time limits are set
  through Python (`timeout=`), not by calling `timeout`. Example, 24 Oct: `templates/bin-check` called
  `timeout` and `md5sum`, which macOS lacks.
- Tests use a temporary folder and never touch the live `.relay/queue`, `.relay/checks` or
  `docs/handover.md`. Example, 24 Oct: a test that read the live queue item broke the inert probe.
- Anything beyond a thin wrapper is Python. Bash is on its way out: do not grow a bash script, move it
  to Python when you next change it.
- Only relay loads this rule for now; other projects do not.
