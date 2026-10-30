"""The single gate of the relay repository (`bin/ci` is a thin wrapper that runs this file). Quiet: one line per step; a
failing step's first findings; the full log in .ci/ci.log. Exit 0 only when green.

    bin/ci              every step, the paid ones included (plugin evals need `claude`)
    bin/ci --quick      the free steps only; ends "QUICK MODE" and never releases

Steps: library tests (python), types and lint (mypy + ruff pyflakes rules through uv; needs uv and, the first time, the
network), hook tests (the live session test; bun/jq must be on PATH or the step
FAILS naming the tool; only hooks-live, which makes a paid claude call, is left for the full run), plugin lib links,
plugin evals' grader tests, `claude plugin validate` (skipped loudly without claude), the inert step, clean image quick gate (full mode only: container/Containerfile through podman, about 20 min, red when the quick gate is red there), plugin evals (full
mode only; compared with evals/plugin/baseline), then the record step (bin/eval-record: files .ci/evals.json under
$RELAY_HOME/evals, prints failed meaning graders, split votes and rule-file reads; it fails the gate when the copy fails,
when a case failed its majority of runs (2 of 3 pass), or when a run was not judged).

A change of only rules/*.md files (lib/relay_textonly.py) runs just the step "rules text tests" under --quick.

Under `relay gate` (RELAY_GATE = the commit gated) the six free steps run once, on a copy of that commit without the
inert files (GateCopy: a temporary worktree where docs/handover.md and everything under .relay/queue, .relay/checks and
.relay/changes is deleted, committed as "gate copy"). Two commits that differ only in inert files give the same copy, so a
green gate also stands for them (lib/relay_gate_logs.py `reusable`), and a test that reads one of those files goes red on
its first gate. The step logs and the gate log are written in the real worktree; the paid steps run there too, after the
copy is removed. A plain `bin/ci` makes no copy.
"""
from __future__ import annotations

import contextlib
import glob
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from typing import Any, Callable, NoReturn, TextIO

from relay_ci_copy import remove_leftover_copy, write_shared_record, drop_shared_record
from relay_ci_lines import _read_lines_keep
import relay_inert
import relay_precheck
from relay_ci_image import clean_image
from relay_ci_python import python_problem  # noqa: F401  (re-exported: tests call relay_ci.python_problem)

StepFn = Callable[[TextIO], int]

FINDING = re.compile(r"FAIL|Error|error|✗|^ERROR: ")   # "ERROR: <test id>" names a test that raised, not failed
MAX_FINDINGS = 8            # lines of a failing step shown under its line (the full log is in .ci/ci.log)
STOP_GRACE = 10.0           # seconds a stopped process has to end after SIGTERM before it is killed
# Seconds of its own run (clock starts in Ci.main) after which the quick gate stops itself. Owner, 29 Oct: "30 минут сейчас, 25 после ускорения" (1500 since the single test run). Measured 29 Oct over 579 logs: 20 ran over 30 min (7 normal, 13 hung).
QUICK_LIMIT_SECONDS = 1500
LIMIT_ENV = "RELAY_CI_QUICK_LIMIT"   # whole seconds, 1 or more; replaces QUICK_LIMIT_SECONDS (tests, or a person debugging)
LIMIT_EXIT = 124            # the exit of a gate stopped at its time limit (GNU `timeout`'s code); relay_gate.LIMIT_EXIT is the same number
HOOK_TOOLS = (("git", "install git"), ("jq", "brew install jq"), ("python3", "install python3"),
              ("bun", "curl -fsSL https://bun.sh/install | bash (the packet and check-contract tests run on it)"))


def _descendants(pid: int) -> list[int]:
    """The pids below `pid` (children, their children, ...), from one `ps` listing."""
    done = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True)
    children: dict[int, list[int]] = {}
    for ln in done.stdout.splitlines():
        parts = ln.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    found: list[int] = []
    queue = [pid]
    while queue:
        for child in children.get(queue.pop(), []):
            found.append(child)
            queue.append(child)
    return found


def quick_limit(env: dict[str, str]) -> int:
    """The quick gate's time limit in seconds; ValueError (with the message to print) when the setting is not a whole number >= 1."""
    text = env.get(LIMIT_ENV, str(QUICK_LIMIT_SECONDS))
    if re.fullmatch(r"[0-9]+", text) and int(text) >= 1:
        return int(text)
    raise ValueError("bin/ci: %s must be a whole number of seconds, 1 or more (default %d), not %r"
                     % (LIMIT_ENV, QUICK_LIMIT_SECONDS, text))


def _live(pids: list[int]) -> list[int]:
    """Those of `pids` still running (a zombie, ended but not yet collected by its parent, is gone)."""
    rows = [ln.split() for ln in subprocess.run(["ps", "-A", "-o", "pid=,stat="], capture_output=True, text=True).stdout.splitlines()]
    return [int(p) for p, st in (r for r in rows if len(r) == 2 and r[0].isdigit()) if int(p) in set(pids) and not st.startswith("Z")]


def _signal(pid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError):   # already gone
        os.kill(pid, sig)


def stop_tree(pids: list[int], root: int) -> None:
    """End `pids` (SIGTERM, up to STOP_GRACE seconds to leave), then SIGKILL them and whatever now sits below `root`
    (a process started during the grace). Used for a gate stopped at its time limit."""
    for pid in pids:
        _signal(pid, signal.SIGTERM)
    deadline = time.monotonic() + STOP_GRACE
    while _live(pids) and time.monotonic() < deadline:
        time.sleep(0.1)
    for pid in set(pids) | set(_descendants(root)):
        _signal(pid, signal.SIGKILL)


class GateCopy:
    """The tree the gate's single test run sees: a temporary worktree of the gated commit with every inert file deleted,
    committed as "gate copy". `stop` removes it (and its temporary folder) on any way out."""

    def __init__(self, root: str, head: str) -> None:
        self.root, self.head = root, head
        self.tmpd: str | None = None
        self.work = ""
        self.error = ""
        self.record_path = os.path.join(root, ".ci", "gate-copy")

    def _git(self, *args: str, cwd: str | None = None, text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=cwd or self.root, capture_output=True, text=True, input=text)

    def start(self) -> None:
        """Make the worktree, delete the inert files, commit. A failure is kept in `self.error`."""
        self.tmpd = tempfile.mkdtemp()
        # recorded BEFORE the worktree exists: a gate killed without a chance to clean up (relay gate SIGKILLs the group)
        # leaves this record, and the next run of this worktree removes the leftover (remove_leftover_copy)
        os.makedirs(os.path.dirname(self.record_path), exist_ok=True)
        with open(self.record_path, "w", encoding="utf-8") as handle:
            handle.write(self.tmpd + "\n")
        write_shared_record(self.root, self.tmpd)
        self.work = os.path.join(self.tmpd, "wt")
        if self._git("worktree", "add", "-q", "--detach", self.work, self.head).returncode != 0:
            self.error = "FAIL gate copy: cannot make a worktree at %s" % self.head
            return
        tracked = self._git("ls-files", "-z", cwd=self.work).stdout.split("\0")
        inert = [p for p in tracked if p and relay_inert.matches(p)]
        if inert:   # the paths go through stdin: a long queue folder must not hit the argument limit
            removed = self._git("rm", "-q", "--pathspec-from-file=-", "--pathspec-file-nul", cwd=self.work, text="\0".join(inert) + "\0")
            if removed.returncode != 0:
                self.error = "FAIL gate copy: cannot delete the inert files: %s" % removed.stderr.strip()
                return
        done = self._git("-c", "user.name=relay-ci", "-c", "user.email=ci@relay", "commit", "-q", "--no-verify", "--allow-empty",
                         "-m", "gate copy", cwd=self.work)
        if done.returncode != 0:
            self.error = "FAIL gate copy: cannot commit the copy: %s" % done.stderr.strip()
            return
        # the tests' per-worker logs keep going to the real worktree's .ci/steps
        steps = os.path.join(self.root, ".ci", "steps")
        if os.path.isdir(steps):
            os.makedirs(os.path.join(self.work, ".ci"), exist_ok=True)
            os.symlink(steps, os.path.join(self.work, ".ci", "steps"))

    def stop(self) -> None:
        """Remove the worktree and the temporary folder. Safe to call twice."""
        if self.tmpd is not None:
            if os.path.isdir(self.root):   # a gone worktree: the shared record lets the next gate of any worktree unregister the copy
                self._git("worktree", "remove", "--force", self.work)
                self._git("worktree", "prune")
            shutil.rmtree(self.tmpd, ignore_errors=True)
            if os.path.isdir(self.root):
                drop_shared_record(self.root, self.tmpd)
            self.tmpd = None
        if os.path.exists(self.record_path):
            os.remove(self.record_path)


class _LimitStop(Exception): """The gate was stopped at its time limit; raised in the main thread once the step that was running has returned."""


class Ci:
    def __init__(self, root: str, quick: bool, env: dict[str, str] | None = None,
                 runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run) -> None:
        self.root, self.quick = root, quick
        self.coverage_line = ""      # the gate log's coverage line, set by the library tests step
        self.env = dict(os.environ if env is None else env)
        self.env.update(NO_COLOR="1", RELAY_ROOT=root)
        self.real_env = self.env     # the environment of the real worktree, kept while the copy runs
        self.runner = runner
        self.status = 0
        self.work = root             # where the steps run: the real worktree, or the gate copy while the free steps run
        self.copy: GateCopy | None = None
        self.running = ""            # the step being run now (read by the watchdog thread)
        self.stopped = False         # the watchdog has fired
        self.stopped_step = ""       # the step that was running when it fired ("" between steps)
        self.kills_done = threading.Event()   # the watchdog has finished its kills: nothing is cleaned up before this

    # ---- plumbing -------------------------------------------------------------------------------------------------
    def say(self, text: str) -> None:
        print(text, flush=True)

    def path(self, *parts: str) -> str:
        """A path in the real worktree (logs, records, the paid steps' files)."""
        return os.path.join(self.root, *parts)

    def wpath(self, *parts: str) -> str:
        """A path in the tree the steps run on (the gate copy while the free steps run)."""
        return os.path.join(self.work, *parts)

    def enter_copy(self, copy: GateCopy) -> None:
        """Run the steps that follow on `copy`, without RELAY_GATE (a test cannot find the gated sha from it)."""
        self.work = copy.work
        self.real_env = self.env
        self.env = {k: v for k, v in self.env.items() if k != "RELAY_GATE"}
        self.env["RELAY_ROOT"] = copy.work

    def leave_copy(self) -> None:
        """Remove the copy; the steps that follow run on the real worktree again."""
        if self.copy is not None:
            self.copy.stop()
            self.work, self.env = self.root, self.real_env
            self.copy = None

    def prepare(self) -> None:
        os.makedirs(self.path(".ci", "steps"), exist_ok=True)
        remove_leftover_copy(self.root)
        for name in ("ci.log", "results.txt"):
            open(self.path(".ci", name), "w").close()

    def which(self, name: str) -> str | None:
        return shutil.which(name, path=self.env.get("PATH"))

    def run(self, argv: list[str], log: TextIO | None = None, cwd: str | None = None, env: dict[str, str] | None = None,
            capture: bool = False) -> subprocess.CompletedProcess[Any]:
        """Run a program (a list, no shell). Its output goes to `log` (stderr with it); a program that cannot start is
        status 127 with the reason in the log, never a pass."""
        if log is not None:
            log.flush()
        if self.stopped:    # after the watchdog's kill nothing new starts (a step that runs programs in a loop ends at once)
            log and log.write("stopped at the time limit: %s not started\n" % argv[0])
            return subprocess.CompletedProcess(argv, LIMIT_EXIT, "" if capture else None)
        # close_fds=False: a lock fd that relay gate passes to bin/ci stays open in every child until the last one ends
        kwargs: dict[str, Any] = {"cwd": cwd or self.work, "env": env or self.env, "close_fds": False}
        if capture:
            kwargs.update(stdout=subprocess.PIPE, text=True)
        elif log is not None:
            kwargs.update(stdout=log, stderr=subprocess.STDOUT)
        try:
            return self.runner(argv, **kwargs)
        except OSError as err:
            if log is not None:
                log.write("%s: %s\n" % (argv[0], err))
            return subprocess.CompletedProcess(argv, 127, "" if capture else None)

    def step(self, name: str, fn: StepFn, show_all: bool = False) -> None:
        """One step: its output to .ci/steps/<name>.log, appended to .ci/ci.log; its result to .ci/results.txt; one line out."""
        log_path = ".ci/steps/%s.log" % name.replace(" ", "-")
        if self.stopped: self._leave()
        self.running = name
        start = time.monotonic()
        with open(self.path(log_path), "w", encoding="utf-8") as log:
            try:
                rc = fn(log)
            except Exception:  # a crash in a step is that step's failure, with the traceback in its log
                log.write(traceback.format_exc())
                rc = 1
            finally:
                self.running = ""
        seconds = int(time.monotonic() - start)
        text = "".join(_read_lines_keep(self.path(log_path)))
        with open(self.path(".ci", "ci.log"), "a", encoding="utf-8") as ci_log:
            ci_log.write("==> %s\n%s" % (name, text))
        stopped = self.stopped and name == self.stopped_step    # killed by the watchdog: not a failure of the step
        with open(self.path(".ci", "results.txt"), "a", encoding="utf-8") as results:
            results.write("%s %s\n" % (name, "STOPPED" if stopped else "ok" if rc == 0 else "FAILED"))
        if stopped: self._leave()
        if rc == 0:
            self.say("ci: %s ok (%ds)" % (name, seconds))
            return
        self.say("ci: %s FAILED (%ds, log: %s)" % (name, seconds, log_path))
        lines = text.splitlines()
        shown = lines if show_all else [ln for ln in lines if FINDING.search(ln)][:MAX_FINDINGS]
        for ln in shown:
            self.say("    " + ln)
        self.status = 1

    def _leave(self) -> NoReturn:
        self.kills_done.wait()    # the copy's cleanup starts only after the watchdog's kills, never killed under it
        raise _LimitStop()

    # ---- steps ----------------------------------------------------------------------------------------------------
    def lib_tests(self, log: TextIO) -> int:
        import relay_coverage      # lib/ is on the path of the gate (bin/ci); not at the top, like the other relay modules here
        rc, self.coverage_line = relay_coverage.library_tests(self.work, self.env, self.quick, self.run, log, self.which)
        return rc

    def types_lint(self, log: TextIO) -> int:
        # mypy and ruff F, pinned, through uv (bin/types-lint, pyproject.toml)
        return self.run(["bash", "bin/types-lint"], log).returncode

    def hook_tests(self, log: TextIO) -> int:
        env = dict(self.env)
        rc = 0
        # the tools the free tests run on: a missing one FAILS the step (a skipped test would pass a gate that checked nothing)
        for tool, how in HOOK_TOOLS:
            if self.which(tool) is None:
                log.write("FAIL hook tests need %s on PATH: %s\n" % (tool, how))
                rc = 1
        if rc:
            return 1
        # the hook suites are tests/test_hook_*.py: the library tests step runs them. What is left here is the live session.
        rel = os.path.join("tests", "hooks_live.py")
        # hooks-live runs a real Claude Code session (claude -p, Haiku, a few cents): the full gate only
        if self.quick:
            log.write("--- %s (left for the full bin/ci: it makes a paid claude call)\n" % rel)
            return 0
        if not os.path.exists(self.wpath(rel)):
            return 0
        if self.which("claude") is None:
            log.write("FAIL %s needs claude on PATH: install Claude Code\n" % rel)
            return 1
        log.write("--- %s\n" % rel)
        if self.run(["python3", rel], log, env=dict(env, HOOKS_LIVE="1")).returncode != 0:
            log.write("FAIL %s\n" % rel)
            return 1
        return 0

    def lib_links(self, log: TextIO) -> int:
        """Each lib module exists once: the precheck's allow-list over the committed tree (see relay_precheck.check_lib_links)."""
        found = relay_precheck.check_lib_links(self.work)
        for line in found:
            log.write(line + "\n")
        return 0 if all(line.startswith("skipped") for line in found) else 1

    def grader_tests(self, log: TextIO) -> int:
        return self.run(["python3", "-I", "evals/plugin/graders.py"], log).returncode

    def tracks_something(self, folder: str) -> bool:
        """False only when git answers and tracks no file in `folder` (a renamed plugin's old folder holding ignored files);
        when git cannot answer the folder is kept, so it is still validated."""
        run = self.run(["git", "ls-files", "--", os.path.relpath(folder, self.work)], capture=True)
        return run.returncode != 0 or bool((run.stdout or "").strip())

    def validate_all(self, log: TextIO) -> int:
        if self.which("claude") is None:
            log.write("skipped: claude is not on PATH (install Claude Code to validate plugins)\n")
            return 0
        rc = 0
        dirs = ["."] + [os.path.relpath(d, self.work) + "/" for d in sorted(glob.glob(self.wpath("plugins", "*/")))
                        if self.tracks_something(d)]
        for d in dirs:
            log.write("--- %s\n" % d)
            if self.run(["claude", "plugin", "validate", d], log).returncode != 0:
                rc = 1
        return rc

    def rules_tests(self, log: TextIO) -> int:
        done = self.run(["python3", "lib/relay_textonly.py", "tests"], log, capture=True)
        if done.returncode != 0:
            return 1
        names = done.stdout.split()
        if self.run(["python3", "-W", "ignore::ResourceWarning", "tests/run_unittest.py", *names], log).returncode != 0:
            return 1
        return self.run(["python3", "bin/relay", "sync", "--dry"], log).returncode

    def rules_only(self) -> bool:
        """A change of only the rule texts (the fixed list in lib/relay_textonly.py) in the quick gate."""
        if not (self.quick and os.path.isfile(self.path("lib", "relay_textonly.py"))):
            return False
        done = self.run(["python3", "lib/relay_textonly.py", "check"], capture=True)
        return done.returncode == 0

    # ---- the paid part --------------------------------------------------------------------------------------------
    def clean_image(self, log: TextIO) -> int:
        """The clean-image quick gate (podman only; the recipe is in relay_ci_image). Red when the image's gate is."""
        return clean_image(self, log)

    def plugin_evals(self) -> int | None:
        """The paid eval step. Returns the exit code when the gate must end here (the cap, no ceiling), else None."""
        # a leftover file from an earlier run must never be filed or printed as this batch
        evals_json = self.path(".ci", "evals.json")
        if os.path.exists(evals_json):
            os.remove(evals_json)
        if self.run(["python3", "bin/paid-cost", "guard", "eval"]).returncode != 0:   # the owner's daily cap, projects.toml [global]
            self.say("ci: RED (the day's paid-run cap)")
            return 1
        # the ceiling fits the suite (largest stored full batch x 2, $15 when nothing is stored); EVALS_MAX_COST, when set, is the owner's fixed number
        max_cost = self.env.get("EVALS_MAX_COST")
        cap_args = ["--cap", max_cost] if max_cost else ["--from-estimate", "--cap", "15"]
        # the eval tool lets runs already started finish after the ceiling trips: pass the cap minus (jobs - 1) x the largest run, which keeps the batch within one run of the cap (bin/paid-cost)
        got = self.run(["python3", "bin/paid-cost", "ceiling", "--within-day", *cap_args, "--jobs", self.env.get("EVALS_JOBS") or "1"],
                       capture=True)
        words = (got.stdout or "").split()
        if got.returncode != 0 or len(words) != 2:
            self.say("ci: RED (no money ceiling for the plugin evals)")
            return 1
        jobs, ceiling = words
        if not self.note_paid_start():
            return 1
        estimate = self.run(["python3", "bin/paid-cost", "estimate"], capture=True).stdout.strip()
        self.say("plugin evals: estimate %s; -j %s, ceiling $%s (%s)" % (estimate, jobs, ceiling, " ".join(cap_args)))
        env = dict(self.env, PATH=self.path("plugins", "relay", "bin") + os.pathsep + self.env.get("PATH", ""))
        # Write is granted because a real session has it: the Write graders error when it is not granted
        argv = ["claude", "plugin", "eval", self.root, "--eval-dir", "evals/plugin", "--trust-plugin", "--scaffold",
                "--allow-tools", "Bash", "Agent", "Write", "--ablation", "none", "-j", jobs,
                "--judge-model", self.env.get("EVALS_JUDGE_MODEL") or "sonnet", "--no-publish", "--max-cost-usd", ceiling,
                "--keep-temp",   # the run folders stay until bin/eval-record copies the failing ones and removes the rest
                "--json", evals_json]
        def evals(log: TextIO) -> int:
            # the tool exits 1 when any single run failed; the verdict is the record's majority rule (bin/eval-record, in
            # record()), which is also red when the tool wrote no record. The tool's own code goes to the log.
            sys.path.insert(0, self.path("lib"))
            import relay_plugin_links   # the eval's sandbox does not read a link's target outside the plugin: real files for the run
            with relay_plugin_links.real_files(self.root):
                code = self.run(argv, log, cwd=self.path("evals", "plugin"), env=env).returncode
            log.write("claude plugin eval exited %d; the gate judges the record by the majority rule, not this code\n" % code)
            return 0
        self.step("plugin evals", evals)
        return None

    def note_paid_start(self) -> bool:
        """Write the `started` record of the paid run (lib/relay_paid.py) when the tree gated is the default branch's head; a full
        run in a task worktree writes none. False (the run ends, before any money is spent) when the record cannot be written."""
        sys.path.insert(0, self.path("lib"))
        import relay_git   # the lib of the tree being gated
        import relay_paid
        head = self.run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
        branch = (self.run(["git", "symbolic-ref", "--short", "-q", "HEAD"], capture=True).stdout or "").strip() or relay_git.default_branch(self.root) or "detached"
        default = relay_git.default_branch(self.root)
        if not default or branch != default or relay_git.git(self.root, "rev-parse", "--verify", "-q", "refs/heads/" + default)[1] != head:
            return True
        try:
            relay_paid.record(self.root, relay_paid.PaidEvent("started", relay_paid.now(), head=head, pid=os.getpid()))
        except (OSError, ValueError) as exc:
            self.say("ci: RED (the paid run's start could not be recorded: %s)" % exc)
            return False
        return True

    def record(self) -> None:
        """File the eval result; the record names the commit it ran on and the branch it counts for: a detached worktree of
        the default branch's head records the default branch (bin/paid-cost due)."""
        head = self.run(["git", "symbolic-ref", "--short", "-q", "HEAD"], capture=True)
        branch = (head.stdout or "").strip()
        if head.returncode != 0 or not branch:
            sys.path.insert(0, self.path("lib"))
            import relay_git   # the lib of the tree being gated
            branch = relay_git.default_branch(self.root) or "detached"
        sha = self.run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
        rc = self.run(["python3", "bin/eval-record", "--json", ".ci/evals.json", "--branch", branch, "--head", sha]).returncode
        if rc == 1:
            self.say("ci: RED (the eval record could not be stored)")
            self.status = 1
        elif rc != 0:
            self.say("ci: RED (eval runs were not judged or a case failed its majority: not a pass; bin/eval-record --verdict <the stored path eval-record prints> shows why)")
            self.status = 1

    # ---- the whole gate -------------------------------------------------------------------------------------------
    def _stop_at_limit(self) -> None:
        """The watchdog (a timer thread): note the running step, end every process below this one; `step` then raises _LimitStop."""
        self.stopped_step = self.running
        self.stopped = True
        try:
            stop_tree(_descendants(os.getpid()), os.getpid())
        finally:
            self.kills_done.set()

    def main(self) -> int:
        try:
            limit = quick_limit(self.env)
        except ValueError as err:
            print(err, file=sys.stderr)
            return 2
        timer: threading.Timer | None = None
        if self.quick:
            timer = threading.Timer(limit, self._stop_at_limit)
            timer.daemon = True
            timer.start()
        stopped = False
        try:
            code = self._run()
        except _LimitStop:
            stopped, code = True, self.status
        finally:
            if timer is not None:
                timer.cancel()
                timer.join()    # a watchdog in the middle of its kills ends first (at once when it never fired)
        if not stopped:
            return code
        how = "%d-minute" % (limit // 60) if limit % 60 == 0 else "%d-second" % limit
        self.say("gate: stopped at the %s limit, %s" % (how, f"step {self.stopped_step} was running" if self.stopped_step else "between two steps"))
        if self.status != 0:    # an earlier real failure wins: a rerun would meet it again, so the fixer gets it now
            self.say("ci: RED")
            return 1
        log = "; the step's log is .ci/steps/%s.log" % self.stopped_step.replace(" ", "-") if self.stopped_step else ""
        self.say("ci: RED (stopped at the time limit, not a test failure: run the gate again%s)" % log)
        return LIMIT_EXIT

    def _run(self) -> int:
        self.prepare()
        if self.rules_only():
            self.step("rules text tests", self.rules_tests)
            self.say("ci: green (QUICK MODE: rules text only, the short gate; paid steps skipped, not a release gate)"
                     if self.status == 0 else "ci: RED")
            return self.status
        gate = self.env.get("RELAY_GATE")
        try:
            if gate:
                copy = GateCopy(self.root, gate)
                self.copy = copy
                copy.start()
                if copy.error:
                    self.say("ci: " + copy.error)
                    self.say("ci: RED")
                    return 1
                self.enter_copy(copy)
            # the seconds-long steps first: a red one ends the gate at once
            self.step("types and lint", self.types_lint)
            self.step("plugin lib links", self.lib_links)
            if self.status != 0:
                self.say("ci: RED (a fast step failed: the slow steps were not started)")
                return self.status
            self.step("library tests", self.lib_tests)
            if self.coverage_line: self.say(self.coverage_line)
            self.step("hook tests", self.hook_tests)
            self.step("eval grader tests", self.grader_tests)
            self.step("plugin validate", self.validate_all)
            if gate:
                self.say("ran on a copy without queue, handover and check records; covers every commit with the same code")
        finally:
            self.leave_copy()
        if not self.quick:
            # the paid run (once per wave) is where the clean-image gate runs: a container gate takes about 20 minutes on this Mac
            before = self.status
            self.step("clean image quick gate (podman, about 20 min)", self.clean_image)
            if self.status != before:
                self.say("ci: RED (the clean-image quick gate failed: the paid evals were not started)")
                return self.status
            if self.which("claude") is not None:
                stop = self.plugin_evals()
                if stop is not None:
                    return stop
                self.record()
            else:
                self.say("ci: plugin evals skipped: claude is not on PATH")
                self.status = 1
        if self.status != 0:
            self.say("ci: RED")
        elif self.quick:
            self.say("ci: green (QUICK MODE: paid steps skipped, not a release gate)")
        else:
            self.say("ci: green")
        return self.status


def _raise_exit(signum: int, _frame: object) -> None:
    raise SystemExit(128 + signum)


def main(argv: list[str], root: str | None = None) -> int:
    root = root or os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    quick = False
    for arg in argv:
        if arg in ("--quick", "--no-evals"):
            quick = True
        else:
            print("usage: bin/ci [--quick]", file=sys.stderr)
            return 2
    problem = python_problem(root)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    # a stopped gate leaves through an exception, so the copy's worktree is removed
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _raise_exit)
    return Ci(root, quick).main()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
