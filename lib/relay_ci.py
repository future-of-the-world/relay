"""The single gate of the relay repository (`bin/ci` is a thin wrapper that runs this file). Quiet: one line per step; a
failing step's first findings; the full log in .ci/ci.log. Exit 0 only when green.

    bin/ci              every step, the paid ones included (plugin evals need `claude`)
    bin/ci --quick      the free steps only; ends "QUICK MODE" and never releases

Steps: library tests (python), types and lint (mypy + ruff pyflakes rules through uv; needs uv and, the first time, the
network), hook tests (bash: every plugins/*/tests/*.test.sh runs in quick mode too; bun/jq must be on PATH or the step
FAILS naming the tool; only hooks-live, which makes a paid claude call, is left for the full run), lib copies identical,
plugin evals' grader tests, `claude plugin validate` (skipped loudly without claude), the inert step, plugin evals (full
mode only; compared with evals/plugin/baseline), then the record step (bin/eval-record: files .ci/evals.json under
$RELAY_HOME/evals, prints failed meaning graders, split votes and rule-file reads; it fails the gate when the copy fails,
when a case failed its majority of runs (2 of 3 pass), or when a run was not judged).

A change of only rules/*.md files (lib/relay_textonly.py) runs just the step "rules text tests" under --quick.

The step `inert` runs only under `relay gate` (RELAY_GATE = the commit gated). The inert probe is a second quick run of
this gate in a temporary worktree of that commit where every inert file has a line appended and probe files sit in the
inert folders. It is started BEFORE the first step and runs beside the outer steps; at the `inert` step the gate waits
for it and fails when a step's result or the test count differs, which proves no outcome depends on an inert file
(design section 12.6). A probe that dies is a failed `inert`, never an ok one. The probe's output is kept in
.ci/steps/inert-nested.log.
"""
from __future__ import annotations

import difflib
import filecmp
import glob
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from typing import Any, Callable, TextIO

StepFn = Callable[[TextIO], int]

FINDING = re.compile(r"FAIL|Error|error|✗|^ERROR: ")   # "ERROR: <test id>" names a test that raised, not failed
MAX_FINDINGS = 8            # lines of a failing step shown under its line (the full log is in .ci/ci.log)
STOP_GRACE = 10.0           # seconds a stopped probe has to end after SIGTERM before it is killed
PROBE_LINE = "inert probe line"
HOOK_TOOLS = (("git", "install git"), ("jq", "brew install jq"), ("python3", "install python3"),
              ("bun", "curl -fsSL https://bun.sh/install | bash (the packet and check-contract tests run on it)"))


def outcome(directory: str) -> list[str]:
    """What a run did, as lines that must not change when an inert file does: each step's result, the library test count
    ("Ran N tests"), and the number of passing hook-test cases (not hooks-live's lines: only a full run runs it, with a
    live model, so they would differ from the nested quick run's)."""
    lines: list[str] = []
    lines += _read_lines(os.path.join(directory, ".ci", "results.txt"))
    lines += [re.sub(r" in [0-9.]+s", "", ln, count=1)
              for ln in _read_lines(os.path.join(directory, ".ci", "steps", "library-tests.log")) if ln.startswith("Ran ")]
    skip, cases = False, 0
    for ln in _read_lines(os.path.join(directory, ".ci", "steps", "hook-tests.log")):
        if ln.startswith("--- "):
            skip = "hooks-live" in ln
        if not skip and ln.startswith("ok"):
            cases += 1
    lines.append("hook cases ok: %d" % cases)
    return lines


def _read_lines(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().splitlines()
    except FileNotFoundError:
        return []


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


def remove_leftover_probe(root: str) -> None:
    """Remove the probe worktree of an earlier run of THIS worktree that was killed before it could clean up (the path is
    recorded in <root>/.ci/inert-probe by Probe.start; another worktree has its own record, so a live probe is never touched)."""
    record = os.path.join(root, ".ci", "inert-probe")
    lines = _read_lines(record)
    if not lines:
        if os.path.exists(record):
            os.remove(record)
        return
    tmpd = lines[0].strip()
    if tmpd and os.path.isdir(tmpd):
        work = os.path.join(tmpd, "wt")
        subprocess.run(["git", "worktree", "remove", "--force", work], cwd=root, capture_output=True)
        subprocess.run(["git", "worktree", "prune"], cwd=root, capture_output=True)
        shutil.rmtree(tmpd, ignore_errors=True)
    else:
        subprocess.run(["git", "worktree", "prune"], cwd=root, capture_output=True)
    os.remove(record)


class Probe:
    """The inert probe: a temporary worktree of the gated commit with every inert file changed, and a quick run of the gate
    in it, started now and finished by `finish`. `stop` ends it (and removes the worktree) on any way out."""

    def __init__(self, root: str, head: str, quick: bool, env: dict[str, str], log_path: str,
                 nested: tuple[str, ...] = ("bash", "bin/ci", "--quick")) -> None:
        self.root, self.head, self.quick, self.env, self.log_path, self.nested = root, head, quick, env, log_path, nested
        self.tmpd: str | None = None
        self.work = ""
        self.proc: subprocess.Popen[bytes] | None = None
        self.error = ""
        self._log: Any = None
        self.record_path = os.path.join(root, ".ci", "inert-probe")

    def _git(self, *args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=cwd or self.root, capture_output=True, text=True)

    def start(self) -> None:
        """Make the worktree, plant the files, commit, start the nested run. A failure is kept in `self.error`."""
        self.tmpd = tempfile.mkdtemp()
        # recorded BEFORE the worktree exists: a gate killed without a chance to clean up (relay gate SIGKILLs the group)
        # leaves this record, and the next run of this worktree removes the leftover (remove_leftover_probe)
        os.makedirs(os.path.dirname(self.record_path), exist_ok=True)
        with open(self.record_path, "w", encoding="utf-8") as handle:
            handle.write(self.tmpd + "\n")
        self.work = os.path.join(self.tmpd, "wt")
        if self._git("worktree", "add", "-q", "--detach", self.work, self.head).returncode != 0:
            self.error = "FAIL inert: cannot make a worktree at %s" % self.head
            return
        for sub in (".relay/queue", ".relay/checks", "docs"):
            os.makedirs(os.path.join(self.work, sub), exist_ok=True)
        tracked = self._git("ls-files", "-z", "--", "docs/handover.md", ".relay/queue", ".relay/checks", cwd=self.work)
        for rel in [p for p in tracked.stdout.split("\0") if p] + ["docs/handover.md"]:
            with open(os.path.join(self.work, rel), "a", encoding="utf-8") as handle:
                handle.write(PROBE_LINE + "\n")
        # unknown files under the stored names (.json): a reader that lists the folders and breaks on an extra one changes the outcome
        planted = {".relay/queue/zz-probe.json": "not a queue item\n", ".relay/checks/zz.json": "{}\n",
                   ".relay/checks/zz.check.json": "{}\n", ".relay/checks/zz.gate.log": "head 0\nexit 0\n"}
        for rel, text in planted.items():
            with open(os.path.join(self.work, rel), "w", encoding="utf-8") as handle:
                handle.write(text)
        self._git("add", "-A", cwd=self.work)
        self._git("-c", "user.name=relay-ci", "-c", "user.email=ci@relay", "commit", "-q", "--no-verify", "-m", "inert probe",
                  cwd=self.work)
        # a full outer run ran the hook suites in full (guard-main repeats its shared cases per profile); the nested run is quick
        # for the paid steps only, so its hook tests run in full too, or the case counts differ by mode, not by an inert file
        env = {k: v for k, v in self.env.items() if k != "RELAY_GATE"}
        env["RELAY_INERT_PROBE"] = "1"   # the probe run is marked: its test runner only reads the class times; the outer run writes them
        env["RELAY_INERT_FULL_HOOKS"] = "" if self.quick else "1"
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self._log = open(self.log_path, "wb")
        # the same process group as this run: whatever stops the gate's group stops the probe too
        self.proc = subprocess.Popen(list(self.nested), cwd=self.work, env=env, stdin=subprocess.DEVNULL,
                                     stdout=self._log, stderr=subprocess.STDOUT, close_fds=False)   # keeps an inherited lock fd

    def wait(self) -> int | None:
        """The nested run's exit code once it ends (negative: stopped by a signal); None when it never started."""
        if self.proc is None:
            return None
        return self.proc.wait()

    def stop(self) -> None:
        """End the nested run and everything below it, remove the worktree and the temporary folder. Safe to call twice."""
        proc = self.proc
        if proc is not None and proc.poll() is None:
            below = _descendants(proc.pid)
            for pid in [proc.pid] + below:
                self._signal(pid, signal.SIGTERM)
            try:
                proc.wait(timeout=STOP_GRACE)
            except subprocess.TimeoutExpired:
                pass
            for pid in [proc.pid] + below:
                self._signal(pid, signal.SIGKILL)
            proc.wait()
        if self._log is not None:
            self._log.close()
            self._log = None
        if self.tmpd is not None:
            self._git("worktree", "remove", "--force", self.work)
            self._git("worktree", "prune")
            shutil.rmtree(self.tmpd, ignore_errors=True)
            self.tmpd = None
        if os.path.exists(self.record_path):
            os.remove(self.record_path)

    @staticmethod
    def _signal(pid: int, sig: int) -> None:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass  # already gone


class Ci:
    def __init__(self, root: str, quick: bool, env: dict[str, str] | None = None,
                 runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run) -> None:
        self.root, self.quick = root, quick
        self.env = dict(os.environ if env is None else env)
        self.env.update(NO_COLOR="1", RELAY_ROOT=root)
        self.runner = runner
        self.status = 0
        self.probe: Probe | None = None
        self.nested: tuple[str, ...] = ("bash", "bin/ci", "--quick")   # what the probe runs in its worktree (tests replace it)

    # ---- plumbing -------------------------------------------------------------------------------------------------
    def say(self, text: str) -> None:
        print(text, flush=True)

    def path(self, *parts: str) -> str:
        return os.path.join(self.root, *parts)

    def prepare(self) -> None:
        os.makedirs(self.path(".ci", "steps"), exist_ok=True)
        remove_leftover_probe(self.root)
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
        # close_fds=False: a lock fd that relay gate passes to bin/ci stays open in every child until the last one ends
        kwargs: dict[str, Any] = {"cwd": cwd or self.root, "env": env or self.env, "close_fds": False}
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
        start = time.monotonic()
        with open(self.path(log_path), "w", encoding="utf-8") as log:
            try:
                rc = fn(log)
            except Exception:  # a crash in a step is that step's failure, with the traceback in its log
                log.write(traceback.format_exc())
                rc = 1
        seconds = int(time.monotonic() - start)
        text = "".join(_read_lines_keep(self.path(log_path)))
        with open(self.path(".ci", "ci.log"), "a", encoding="utf-8") as ci_log:
            ci_log.write("==> %s\n%s" % (name, text))
        with open(self.path(".ci", "results.txt"), "a", encoding="utf-8") as results:
            results.write("%s %s\n" % (name, "ok" if rc == 0 else "FAILED"))
        if rc == 0:
            self.say("ci: %s ok (%ds)" % (name, seconds))
            return
        self.say("ci: %s FAILED (%ds, log: %s)" % (name, seconds, log_path))
        lines = text.splitlines()
        shown = lines if show_all else [ln for ln in lines if FINDING.search(ln)][:MAX_FINDINGS]
        for ln in shown:
            self.say("    " + ln)
        self.status = 1

    # ---- steps ----------------------------------------------------------------------------------------------------
    def lib_tests(self, log: TextIO) -> int:
        return self.run(["python3", "-W", "ignore::ResourceWarning", "tests/run_unittest.py"], log).returncode

    def types_lint(self, log: TextIO) -> int:
        # mypy and ruff F, pinned, through uv (bin/types-lint, pyproject.toml)
        return self.run(["bash", "bin/types-lint"], log).returncode

    def hook_tests(self, log: TextIO) -> int:
        env = dict(self.env)
        # the guard suite runs its shared cases once in quick mode (not in the inert probe of a full run: see Probe)
        if self.quick and not env.get("RELAY_INERT_FULL_HOOKS"):
            env["RELAY_QUICK"] = "1"
        rc = 0
        # the tools the free tests run on: a missing one FAILS the step (a skipped test would pass a gate that checked nothing)
        for tool, how in HOOK_TOOLS:
            if self.which(tool) is None:
                log.write("FAIL hook tests need %s on PATH: %s\n" % (tool, how))
                rc = 1
        if rc:
            return 1
        for f in sorted(glob.glob(self.path("plugins", "*", "tests", "*.test.sh"))):
            rel = os.path.relpath(f, self.root)
            if "hooks-live" in rel:
                # hooks-live runs a real Claude Code session (claude -p, Haiku, a few cents): the full gate only
                # every --quick run leaves it, the inert probe's nested run too: a second paid call, and a model-dependent count in the comparison
                if self.quick:
                    log.write("--- %s (left for the full bin/ci: it makes a paid claude call)\n" % rel)
                    continue
                if self.which("claude") is None:
                    log.write("FAIL %s needs claude on PATH: install Claude Code\n" % rel)
                    rc = 1
                    continue
                log.write("--- %s\n" % rel)
                if self.run(["bash", rel], log, env=dict(env, HOOKS_LIVE="1")).returncode != 0:
                    log.write("FAIL %s\n" % rel)
                    rc = 1
                continue
            log.write("--- %s\n" % rel)
            if self.run(["bash", rel], log, env=env).returncode != 0:
                log.write("FAIL %s\n" % rel)
                rc = 1
        return rc

    def lib_copies(self, log: TextIO) -> int:
        rc = 0
        for plugin in ("observe", "delegate", "front", "relay", "openspec"):
            for f in sorted(glob.glob(self.path("plugins", plugin, "lib", "relay_*.py"))):
                lib = self.path("lib", os.path.basename(f))
                if not (os.path.exists(lib) and filecmp.cmp(f, lib, shallow=False)):
                    log.write("FAIL %s differs from lib/ (run bin/sync-lib-copies)\n" % os.path.relpath(f, self.root))
                    rc = 1
            prices = self.path("plugins", plugin, "lib", "prices.toml")
            if os.path.exists(prices) and not (os.path.exists(self.path("prices.toml"))
                                               and filecmp.cmp(prices, self.path("prices.toml"), shallow=False)):
                log.write("FAIL plugins/%s/lib/prices.toml differs\n" % plugin)
                rc = 1
        return rc

    def grader_tests(self, log: TextIO) -> int:
        return self.run(["bash", "evals/plugin/graders.test.sh"], log).returncode

    def tracks_something(self, folder: str) -> bool:
        """False only when git answers and tracks no file in `folder` (a renamed plugin's old folder holding ignored files);
        when git cannot answer the folder is kept, so it is still validated."""
        run = self.run(["git", "ls-files", "--", os.path.relpath(folder, self.root)], capture=True)
        return run.returncode != 0 or bool((run.stdout or "").strip())

    def validate_all(self, log: TextIO) -> int:
        if self.which("claude") is None:
            log.write("skipped: claude is not on PATH (install Claude Code to validate plugins)\n")
            return 0
        rc = 0
        dirs = ["."] + [os.path.relpath(d, self.root) + "/" for d in sorted(glob.glob(self.path("plugins", "*/")))
                        if self.tracks_something(d)]
        for d in dirs:
            log.write("--- %s\n" % d)
            if self.run(["claude", "plugin", "validate", d], log).returncode != 0:
                rc = 1
        return rc

    def inert_step(self, log: TextIO) -> int:
        """Wait for the probe started before the first step and compare what the two runs did."""
        probe = self.probe
        assert probe is not None
        if probe.error:
            log.write(probe.error + "\n")
            return 1
        code = probe.wait()
        if code is None or code < 0:
            log.write("FAIL inert: the probe run did not end by itself (%s): its output is in .ci/steps/inert-nested.log\n"
                      % ("it never started" if code is None else "stopped by signal %d" % -code))
            return 1
        outer, nested = outcome(self.root), outcome(probe.work)
        if outer != nested:
            log.write("FAIL inert: a step's result or the test count changed when only inert files changed (the probe's "
                      "output is in .ci/steps/inert-nested.log):\n")
            for ln in difflib.unified_diff(outer, nested, "outer run", "probe run", lineterm="", n=0):
                log.write("    %s\n" % ln)
            return 1
        log.write("inert: the same results with every inert file changed\n")
        return 0

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
            code = self.run(argv, log, cwd=self.path("evals", "plugin"), env=env).returncode
            log.write("claude plugin eval exited %d; the gate judges the record by the majority rule, not this code\n" % code)
            return 0
        self.step("plugin evals", evals)
        return None

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
    def main(self) -> int:
        self.prepare()
        if self.rules_only():
            self.step("rules text tests", self.rules_tests)
            self.say("ci: green (QUICK MODE: rules text only, the short gate; paid steps skipped, not a release gate)"
                     if self.status == 0 else "ci: RED")
            return self.status
        gate = self.env.get("RELAY_GATE")
        try:
            if gate:
                self.probe = Probe(self.root, gate, self.quick, self.env, self.path(".ci", "steps", "inert-nested.log"),
                                   nested=self.nested)
                self.probe.start()   # beside the outer steps, not after them: it is waited for at the `inert` step
            # the seconds-long steps first: a red one ends the gate at once (the probe runs this same order and stops with it)
            self.step("types and lint", self.types_lint)
            self.step("lib copies identical", self.lib_copies)
            if self.status != 0:
                self.say("ci: RED (a fast step failed: the slow steps were not started)")
                return self.status
            self.step("library tests", self.lib_tests)
            self.step("hook tests", self.hook_tests)
            self.step("eval grader tests", self.grader_tests)
            self.step("plugin validate", self.validate_all)
            if self.probe is not None:
                self.step("inert", self.inert_step, show_all=True)
            else:
                self.say("inert: skipped (runs under relay gate)")
        finally:
            if self.probe is not None:
                self.probe.stop()
        if not self.quick:
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


def _read_lines_keep(path: str) -> list[str]:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.readlines()


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
    # a stopped gate leaves through an exception, so the probe is stopped and its worktree removed
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _raise_exit)
    return Ci(root, quick).main()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
