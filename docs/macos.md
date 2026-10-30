# relay on macOS: what slows it down

Measured on a 12-core Mac. Each item says when it was measured.

## 1. Apple's git launcher (measured 27 Oct)

On macOS, `/usr/bin/git` is not git itself. It is a small launcher that finds the developer tools' git and runs that one. With Xcode that is `/Applications/Xcode.app/Contents/Developer/usr/bin/git`; with only the Command Line Tools it is under `/Library/Developer/CommandLineTools/usr/bin`.

Each start through the launcher costs about 8 ms more: 11.8 ms against 4.1 ms for the real git (30 interleaved rounds). relay's test suite starts git about 29,000 times per run, 81% of them from relay's own code under test. So the launcher costs minutes per test run and slows every relay command a little.

Linux distributions install the real git at `/usr/bin/git`: nothing to do there.

Measured 29 Oct: 20.9 ms per start through the launcher against 6.6 ms for the real git. A library test run starts git 51,000-61,000 times: 1225 s with the launcher, 720 s with the real git.

Fix on a Mac: put the real git first on `PATH`. The simplest way is Homebrew: `brew install git` (its folder comes before `/usr/bin` on a Homebrew machine). Or link the developer tools' git, with all three links, because git started through a bare link looks for its helpers and its built-in settings next to the link: without them `git init` makes `master` instead of `main`, no hook templates are copied, and submodules and the keychain credential helper fail. Once:

```sh
DEV="$(dirname "$(xcrun --find git)")/.."
mkdir -p "$HOME/.local/bin" "$HOME/.local/libexec" "$HOME/.local/share"
ln -sf "$(xcrun --find git)" "$HOME/.local/bin/git"
ln -sfn "$DEV/libexec/git-core" "$HOME/.local/libexec/git-core"
ln -sfn "$DEV/share/git-core" "$HOME/.local/share/git-core"
```

Then in your shell profile put `export PATH="$HOME/.local/bin:$PATH"`. Open a new terminal (or a new Claude Code session) to pick it up. `git --exec-path` must print a folder that exists. Do not put the whole developer-tools folder first on `PATH`: it also carries `python3` 3.9, older than relay needs, and relay would stop starting.

`relay doctor` checks this on macOS ("git first on PATH is the real git") and names this section when the first git is Apple's launcher or its helper folder is missing.

relay does not change `PATH` by itself (decision of 27 Oct: record it, fix it only on your own machine).

## 2. The first-run scan of new executables (measured 26 Oct)

macOS checks every newly written executable the first time it runs:

- a new file, first run: 730-790 ms
- the same file again: 6 ms
- a hardlink or symlink to a file that already ran: about 4 ms
- the whole machine manages about 2.7 such scans per second, however many run at once

For this reason relay's tests reuse fake tools through `tests/fake_tools.py` instead of writing new ones (installer tests went from 72 s to 11 s).

## 3. Python is not the problem (measured 27 Oct)

Python's own logic inside the test process is about 1-1.5% of the test suite's time. The tests also start Python child processes (744 `python3` runs: `bin/relay` and the hooks), and each spends 22-70 ms on interpreter start and imports, about 4-7% of the time in `tests/test_queue.py`; a compiled program would start in 2-5 ms. Both together are what a faster language could shrink, so it would save at most 5-10%. The time goes to starting processes (git above all), the disk, and the two macOS costs above.
