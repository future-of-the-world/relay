"""Port of plugins/relay/tests/merge.test.sh: cleanup after the allowed merge (hooks/merge.sh -> merge.py), cases T1-T14, T16,
T18-T20 of docs/plans/review-gate.md section 12.1 and the merge gate T15 (a)-(p) of 12.2, on throwaway repositories under a
temp dir (temp HOME)."""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from typing import Callable, Dict, List, Optional

from hook_helpers import ROOT, SoftCases

CORE = os.path.join(ROOT, "plugins", "relay")
HOOK = os.path.join(CORE, "hooks", "merge.sh")
MERGE_PY = os.path.join(CORE, "hooks", "merge.py")
GUARD = os.path.join(CORE, "hooks", "guard-main.sh")
CHECKMARK = os.path.join(CORE, "hooks", "check-mark.py")
LIB = os.path.join(CORE, "lib")
RELAY = os.path.join(ROOT, "bin", "relay")
MERGE = "git merge --ff-only wt/t"
GIT_ENV = dict(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def wait_for(pred: Callable[[], bool], timeout: float = 10.0) -> bool:
    """Poll a detached child's effect until the condition holds, at most `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


class Base(SoftCases):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = os.path.realpath(tempfile.mkdtemp())
        os.makedirs(os.path.join(cls.tmp, "home"))
        cls.saved = dict(os.environ)
        for key in ("CLAUDE_PROJECT_DIR",):
            os.environ.pop(key, None)
        os.environ.update(GIT_ENV, HOME=os.path.join(cls.tmp, "home"))
        cls.n = 0
        if LIB not in sys.path:
            sys.path.insert(0, LIB)

    @classmethod
    def tearDownClass(cls) -> None:
        os.environ.clear()
        os.environ.update(cls.saved)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def sh(self, cwd: str, *cmd: str, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
        return subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, **(env or {})))

    def git(self, cwd: str, *args: str) -> str:
        return self.sh(cwd, "git", *args).stdout.strip()

    def git_ok(self, cwd: str, *args: str) -> bool:
        return self.sh(cwd, "git", *args).returncode == 0

    def locked_lines(self) -> List[str]:
        return self.git(self.M, "worktree", "list", "--porcelain").splitlines()

    def mkrepo(self, norelay: bool = False) -> None:
        """M = main checkout on master; a worktree .worktrees/t on wt/t with one commit."""
        type(self).n += 1
        self.M = os.path.join(self.tmp, "r%d" % self.n)
        os.makedirs(self.M)
        self.git(self.M, "init", "-q", "-b", "master", ".")
        write(os.path.join(self.M, ".gitignore"), ".ci/\n")
        if not norelay:
            write(os.path.join(self.M, ".relay", "README.md"), "x\n")
        self.git(self.M, "add", "-A")
        self.git(self.M, "commit", "-q", "-m", "init")
        self.git(self.M, "worktree", "add", "-q", ".worktrees/t", "-b", "wt/t")
        self.W = os.path.join(self.M, ".worktrees", "t")
        write(os.path.join(self.W, "a.txt"), "a\n")
        self.git(self.W, "add", "a.txt")
        self.git(self.W, "commit", "-q", "-m", "work")

    def event(self, command: str, cwd: Optional[str] = None, sid: str = "s0", name: str = "PostToolUse") -> str:
        return json.dumps({"hook_event_name": name, "tool_name": "Bash", "cwd": cwd or self.M, "session_id": sid, "tool_input": {"command": command}})

    def run_hook(self, command: str, cwd: Optional[str] = None, sid: str = "s0", name: str = "PostToolUse", env: Optional[Dict[str, str]] = None) -> None:
        done = subprocess.run([HOOK], input=self.event(command, cwd, sid, name), capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, **(env or {})))
        self.out, self.rc = done.stdout + done.stderr, done.returncode
        self.set_ctx()

    def set_ctx(self) -> None:
        try:
            self.ctx = json.loads(self.out).get("hookSpecificOutput", {}).get("additionalContext", "")
        except ValueError:
            self.ctx = ""

    def merge_and_hook(self, cwd: Optional[str] = None, sid: str = "s0") -> None:
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.run_hook(MERGE, cwd, sid)

    def gone(self) -> bool:
        return not os.path.exists(self.W) and not self.git_ok(self.M, "show-ref", "--verify", "--quiet", "refs/heads/wt/t")

    def kept(self) -> bool:
        return os.path.isdir(self.W) and self.git_ok(self.M, "show-ref", "--verify", "--quiet", "refs/heads/wt/t")

    def has_branch(self, name: str) -> bool:
        return self.git_ok(self.M, "show-ref", "--verify", "--quiet", "refs/heads/" + name)


class Cleanup(Base):
    def test_T1_removed_folder_and_branch(self) -> None:
        self.mkrepo()
        self.merge_and_hook()
        self.assertTrue(self.gone())
        self.assertIn("Removed .worktrees/t and branch wt/t (merged)", self.ctx)

    def test_T2_git_C_main_from_elsewhere(self) -> None:
        self.mkrepo()
        os.makedirs(os.path.join(self.tmp, "elsewhere"), exist_ok=True)
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.run_hook("git -C %s merge --ff-only wt/t" % self.M, os.path.join(self.tmp, "elsewhere"))
        self.assertTrue(self.gone())
        self.assertIn("Removed .worktrees/t", self.ctx)

    def test_T3_no_relay_dir_keeps_then_committing_it_removes(self) -> None:
        self.mkrepo(norelay=True)
        self.merge_and_hook()
        self.assertTrue(self.kept())
        self.assertEqual((self.out, self.rc), ("", 0))
        write(os.path.join(self.M, ".relay", "README.md"), "x\n")
        self.git(self.M, "add", ".relay")
        self.git(self.M, "commit", "-q", "-m", "relay")
        self.run_hook(MERGE)
        self.assertTrue(self.gone())

    def test_T4_hook_cwd_is_the_worktree_kept_and_locked_with_the_session(self) -> None:
        self.mkrepo()
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.run_hook("git -C %s merge --ff-only wt/t" % self.M, self.W, "s1")
        self.assertTrue(os.path.isdir(self.W))
        self.assertIn("this session runs in it", self.ctx)
        self.assertIn("locked session s1", self.locked_lines())
        # the same through CLAUDE_PROJECT_DIR
        self.mkrepo()
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.run_hook(MERGE, self.M, "s2", env={"CLAUDE_PROJECT_DIR": self.W})
        self.assertIn("locked session s2", self.locked_lines())

    def test_T5_fresh_branch_without_commits_is_kept(self) -> None:
        self.mkrepo()
        self.git(self.M, "worktree", "add", "-q", ".worktrees/n", "-b", "wt/n")
        self.run_hook("git merge --ff-only wt/n")
        self.assertIn("wt/n: it has no commits of its own", self.ctx)
        self.git(self.M, "commit", "-q", "--allow-empty", "-m", "queue")
        self.git(os.path.join(self.M, ".worktrees", "n"), "merge", "-q", "--ff-only", "master")
        self.run_hook("git merge --ff-only wt/n")
        self.assertIn("wt/n: it has no commits of its own", self.ctx)
        self.assertTrue(os.path.isdir(os.path.join(self.M, ".worktrees", "n")) and self.has_branch("wt/n"))

    def test_T6_tracked_file_changed(self) -> None:
        self.mkrepo()
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        with open(os.path.join(self.W, "a.txt"), "a") as handle:
            handle.write("changed\n")
        self.run_hook(MERGE)
        self.assertIn("a.txt", self.ctx)
        self.assertTrue(self.kept())

    def test_T7_untracked_file(self) -> None:
        self.mkrepo()
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        write(os.path.join(self.W, "new.txt"), "u\n")
        self.run_hook(MERGE)
        self.assertIn("kept .worktrees/t", self.ctx)
        self.assertIn("new.txt", self.ctx)
        self.assertTrue(os.path.isdir(self.W))

    def test_T8_locked_worktree(self) -> None:
        self.mkrepo()
        self.git(self.M, "worktree", "lock", "--reason", "other", self.W)
        self.merge_and_hook()
        self.assertIn("locked", self.ctx)
        self.assertTrue(os.path.isdir(self.W))

    def test_T9_refused_merge_removes_nothing_and_control(self) -> None:
        self.mkrepo()
        self.git(self.M, "commit", "-q", "--allow-empty", "-m", "diverge")
        self.sh(self.M, "git", "merge", "-q", "--ff-only", "wt/t")
        self.run_hook(MERGE)
        self.assertTrue(self.kept() and self.out == "")
        self.git(self.M, "merge", "-q", "--no-edit", "wt/t")
        self.git(self.W, "merge", "-q", "--no-edit", "master")
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.run_hook(MERGE)
        self.assertTrue(self.gone())  # control: once merged the same input removes

    def test_T9b_plain_merge_is_not_the_allowed_one(self) -> None:
        self.mkrepo()
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.run_hook("git merge wt/t")
        self.assertTrue(self.out == "" and os.path.isdir(self.W))

    def test_T10_read_only_git_and_merge_inside_a_worktree(self) -> None:
        self.mkrepo()
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.run_hook("git -C %s log" % self.W)
        self.assertTrue(self.out == "" and os.path.isdir(self.W))
        w2 = os.path.join(self.M, ".worktrees", "w")
        self.git(self.M, "worktree", "add", "-q", ".worktrees/w", "-b", "wt/w")
        self.git(w2, "commit", "-q", "--allow-empty", "-m", "c")
        self.sh(w2, "git", "merge", "-q", "--ff-only", "wt/t")
        self.run_hook("git -C %s merge --ff-only wt/t" % w2, w2)
        self.assertTrue(self.out == "" and os.path.isdir(self.W))
        self.run_hook(MERGE)
        self.assertTrue(self.gone())  # control: the merge in main removes

    def test_T11_branch_with_no_worktree(self) -> None:
        self.mkrepo()
        self.git(self.M, "worktree", "remove", "--force", self.W)
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.run_hook(MERGE)
        self.assertFalse(self.has_branch("wt/t"))
        self.assertIn("Removed branch wt/t (merged)", self.ctx)

    def test_T12_two_merges_joined_and_cd_main(self) -> None:
        self.mkrepo()
        u = os.path.join(self.M, ".worktrees", "u")
        self.git(self.M, "worktree", "add", "-q", ".worktrees/u", "-b", "wt/u")
        write(os.path.join(u, "b.txt"), "b\n")
        self.git(u, "add", "b.txt")
        self.git(u, "commit", "-q", "-m", "w2")
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.git(self.M, "merge", "-q", "--no-edit", "wt/u")
        self.run_hook("git merge --ff-only wt/t && git merge --ff-only wt/u")
        self.assertFalse(os.path.exists(self.W) or os.path.exists(u))
        self.assertEqual(len(self.ctx.splitlines()), 2)
        self.mkrepo()
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.run_hook("cd %s && git merge --ff-only wt/t" % self.M, self.tmp)
        self.assertTrue(self.gone())

    def test_T14_ignored_file_under_ci(self) -> None:
        self.mkrepo()
        write(os.path.join(self.W, ".ci", "ci.log"), "log\n")
        self.merge_and_hook()
        self.assertTrue(self.gone())
        self.assertIn("with 1 ignored path gone: .ci/", self.ctx)

    def test_N1_notices_for_agent_texts(self) -> None:
        self.mkrepo()
        write(os.path.join(self.W, "plugins", "p", "agents", "a.md"), "x\n")
        write(os.path.join(self.W, "rules", "r.md"), "y\n")
        self.git(self.W, "add", "-A")
        self.git(self.W, "commit", "-q", "-m", "texts")
        write(os.path.join(self.M, "bin", "relay"), "")
        self.git(self.M, "add", "bin")
        self.git(self.M, "commit", "-q", "-m", "relay")
        self.git(self.W, "merge", "-q", "--no-edit", "master")
        self.merge_and_hook()
        self.assertIn("open sessions keep the old texts", self.ctx)
        self.assertIn("once the wave's paid run is green", self.ctx)

    def mkdefault(self, name: str, branch: str) -> str:
        d = os.path.join(self.tmp, name)
        os.makedirs(d)
        self.git(d, "init", "-q", "-b", branch, ".")
        write(os.path.join(d, ".relay", "README.md"), "x\n")
        self.git(d, "add", "-A")
        self.git(d, "commit", "-q", "-m", "init")
        self.git(d, "worktree", "add", "-q", ".worktrees/t", "-b", "wt/t")
        write(os.path.join(d, ".worktrees", "t", "a.txt"), "a\n")
        self.git(os.path.join(d, ".worktrees", "t"), "add", "a.txt")
        self.git(os.path.join(d, ".worktrees", "t"), "commit", "-q", "-m", "work")
        self.git(d, "merge", "-q", "--ff-only", "wt/t")
        return d

    def test_T18_default_branch_through_the_hook(self) -> None:
        self.M = d = self.mkdefault("dev", "develop")
        self.run_hook(MERGE)
        self.assertTrue(self.out == "" and self.rc == 0 and os.path.isdir(os.path.join(d, ".worktrees", "t")))  # unknown default: silent
        write(os.path.join(d, ".claude", "kit.toml"), '[project]\ndefault_branch = "develop"\n')
        self.run_hook(MERGE)
        self.assertIn("Removed .worktrees/t", self.out)
        self.assertFalse(os.path.exists(os.path.join(d, ".worktrees", "t")))
        self.M = d = self.mkdefault("wtb", "develop")
        write(os.path.join(d, ".claude", "kit.toml"), '[project]\ndefault_branch = "wt/x"\n')
        self.run_hook(MERGE)
        self.assertTrue(self.out == "" and os.path.isdir(os.path.join(d, ".worktrees", "t")))  # a kit.toml naming wt/x is ignored


class Sweep(Base):
    def guard_run(self, cwd: str, command: str, project_dir: str) -> None:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=project_dir)
        done = subprocess.run([GUARD], input=json.dumps({"tool_name": "Bash", "cwd": cwd, "tool_input": {"command": command}}),
                              capture_output=True, text=True, encoding="utf-8", env=env)
        self.out, self.rc = done.stdout + done.stderr, done.returncode

    def sweep(self, cwd: str, sid: str, env: Optional[Dict[str, str]] = None) -> None:
        event = json.dumps({"hook_event_name": "SessionStart", "cwd": cwd, "session_id": sid})
        done = subprocess.run([sys.executable, "-I", MERGE_PY, "sweep"], input=event, capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, **(env or {})))
        self.out, self.rc = done.stdout + done.stderr, done.returncode
        self.set_ctx()

    def end(self, sid: str, cwd: Optional[str] = None) -> None:
        event = json.dumps({"hook_event_name": "SessionEnd", "cwd": cwd or self.M, "session_id": sid})
        subprocess.run([sys.executable, "-I", MERGE_PY, "end"], input=event, capture_output=True, text=True, encoding="utf-8")

    def absent(self, path: str) -> Callable[[], bool]:
        return lambda: not os.path.exists(path)

    def nobranch(self, name: str) -> Callable[[], bool]:
        return lambda: not self.has_branch(name)

    def test_T13_deleted_project_dir_falls_back_to_cwd(self) -> None:
        self.mkrepo()
        self.guard_run(self.M, "touch a", os.path.join(self.tmp, "deleted-folder"))
        self.assertEqual(self.rc, 2)
        self.guard_run(self.W, "touch a", os.path.join(self.tmp, "deleted-folder"))
        self.assertEqual(self.rc, 0)  # control: cwd a worktree
        self.guard_run(os.path.join(self.tmp, "none-1"), "touch a", os.path.join(self.tmp, "none-2"))
        self.assertEqual(self.rc, 2)
        self.assertIn("%s no longer exists" % os.path.join(self.tmp, "none-2"), self.out)
        os.makedirs(os.path.join(self.tmp, "norepo"), exist_ok=True)
        self.guard_run(os.path.join(self.tmp, "norepo"), "touch a", "")
        self.assertEqual(self.rc, 0)

    def test_T3_sweep_needs_relay_dir_then_removes(self) -> None:
        self.mkrepo(norelay=True)
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.sweep(self.M, "s0")
        self.assertTrue(self.out == "" and self.rc == 0 and os.path.isdir(self.W))
        write(os.path.join(self.M, ".relay", "README.md"), "x\n")
        self.git(self.M, "add", ".relay")
        self.git(self.M, "commit", "-q", "-m", "relay")
        self.sweep(self.M, "s0")
        self.assertIn("Removing 1 merged worktree: .worktrees/t (wt/t)", self.ctx)
        self.assertTrue(wait_for(self.absent(self.W)))  # the detached child

    def test_T16_sweep_removes_only_the_merged_unlocked_ones(self) -> None:
        self.mkrepo()
        for x in ("u", "own", "locked"):
            self.git(self.M, "worktree", "add", "-q", ".worktrees/" + x, "-b", "wt/" + x)
            d = os.path.join(self.M, ".worktrees", x)
            write(os.path.join(d, x + ".txt"), x + "\n")
            self.git(d, "add", x + ".txt")
            self.git(d, "commit", "-q", "-m", x)
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.git(self.M, "merge", "-q", "--no-edit", "wt/own")
        self.git(self.M, "merge", "-q", "--no-edit", "wt/locked")
        self.git(self.M, "worktree", "lock", "--reason", "session s9", os.path.join(self.M, ".worktrees", "locked"))
        self.sweep(os.path.join(self.M, ".worktrees", "own"), "s1")
        self.assertEqual(self.ctx, "Removing 1 merged worktree: .worktrees/t (wt/t)")
        self.assertTrue(wait_for(self.absent(self.W)))
        self.assertTrue(wait_for(self.nobranch("wt/t")))
        for x in ("u", "own", "locked"):
            self.assertTrue(os.path.isdir(os.path.join(self.M, ".worktrees", x)), x)
        self.assertIn("locked session s9", self.locked_lines())

    def test_T16b_locked_with_this_sessions_id(self) -> None:
        self.mkrepo()
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.git(self.M, "worktree", "lock", "--reason", "session s1", self.W)
        self.sweep(self.W, "s1")  # started inside its own locked worktree: kept, still locked
        self.assertTrue(os.path.isdir(self.W))
        self.assertIn("locked session s1", self.locked_lines())
        self.sweep(self.M, "s1")  # started elsewhere: unlocked and removed
        self.assertTrue(wait_for(self.absent(self.W)))

    def test_T16c_a_session_inside_a_worktree_locks_it(self) -> None:
        self.mkrepo()
        self.sweep(self.W, "s1")
        self.assertIn("locked session s1", self.locked_lines())
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.run_hook("git -C %s merge --ff-only wt/t" % self.M, self.M, "s2")
        self.assertTrue(os.path.isdir(self.W))
        self.assertIn("kept .worktrees/t: locked (session s1)", self.ctx)
        self.sweep(self.M, "s2")
        self.assertTrue(os.path.isdir(self.W))
        self.end("s1", self.W)
        self.assertTrue(wait_for(self.absent(self.W)))

    def test_T19_session_end_unlocks_and_removes_only_its_own(self) -> None:
        self.mkrepo()
        o = os.path.join(self.M, ".worktrees", "o")
        self.git(self.M, "worktree", "add", "-q", ".worktrees/o", "-b", "wt/o")
        write(os.path.join(o, "o.txt"), "o\n")
        self.git(o, "add", "o.txt")
        self.git(o, "commit", "-q", "-m", "o")
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.git(self.M, "merge", "-q", "--no-edit", "wt/o")
        self.run_hook("git -C %s merge --ff-only wt/t" % self.M, self.W, "s1")
        self.git(self.M, "worktree", "lock", "--reason", "session s9", o)
        self.assertIn("locked session s1", self.locked_lines())
        self.end("s1", self.W)
        self.assertTrue(wait_for(self.absent(self.W)))
        self.assertTrue(os.path.isdir(o))
        self.assertIn("locked session s9", self.locked_lines())

    def wrapper(self) -> str:
        real = shutil.which("git")
        wrap = os.path.join(self.tmp, "wrap")
        os.makedirs(wrap, exist_ok=True)
        write(os.path.join(wrap, "git"), '#!/usr/bin/env bash\ncase " $* " in *" worktree remove "*) case "${WRAP_MODE:-}" in slow) sleep 7 ;; '
              'fail) echo "fatal: simulated refusal" >&2; exit 1 ;; esac ;; esac\nexec "%s" "$@"\n' % real)
        os.chmod(os.path.join(wrap, "git"), 0o755)
        return wrap

    def test_T20_slow_removal_completes_after_the_hook_returned(self) -> None:
        wrap = self.wrapper()
        self.mkrepo()
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        # the hook runs in its own process group, which is killed (as the 5 s timeout would) once the hook has returned
        env = dict(os.environ, PATH=wrap + os.pathsep + os.environ["PATH"], WRAP_MODE="slow")
        p = subprocess.Popen([sys.executable, "-I", MERGE_PY, "sweep"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env, start_new_session=True)
        out, _ = p.communicate(json.dumps({"hook_event_name": "SessionStart", "cwd": self.M, "session_id": "s0"}))
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(os.path.isdir(self.W))  # the sweep returned while the folder is still there
        self.assertIn("Removing 1 merged worktree", ctx)
        self.assertTrue(wait_for(self.absent(self.W), 20) and wait_for(self.nobranch("wt/t"), 20))
        self.sweep(self.M, "s0")
        self.assertEqual(self.out, "")  # the next sweep prints no failure

    def test_T20_failing_removal_is_named_once_next_time(self) -> None:
        wrap = self.wrapper()
        self.mkrepo()
        self.git(self.M, "merge", "-q", "--ff-only", "wt/t")
        self.sweep(self.M, "s0", env={"PATH": wrap + os.pathsep + os.environ["PATH"], "WRAP_MODE": "fail"})
        log = os.path.join(self.git(self.M, "rev-parse", "--path-format=absolute", "--git-common-dir"), "relay-cleanup.log")
        self.assertTrue(wait_for(lambda: os.path.exists(log) and os.path.getsize(log) > 0))
        self.sweep(self.M, "s0")
        self.assertIn("could not remove .worktrees/t: simulated refusal", self.ctx)
        self.sweep(self.M, "s0")
        self.assertNotIn("simulated refusal", self.ctx)  # the failure is named once (log cleared)


def queue_item(state: str = "taken", test: str = "") -> dict:
    """A queue item as lib/relay_queue.py writes it, with dated events (a fix item named x). taken: taken_at and taken_by; done: also
    closed_at and the test; dropped: dropped_at and why, never taken."""
    ev = dict(taken_at="2026-10-22T10:00:00Z", taken_by="wt/other", closed_at=None, test=None, dropped_at=None, dropped_why=None)   # not the branch under test: a taken item of it is refused
    if state == "done":
        ev.update(taken_by="wt/t", closed_at="2026-10-22T12:00:00Z", test=test)
    if state == "dropped":
        ev = dict(taken_at=None, taken_by=None, closed_at=None, test=None, dropped_at="2026-10-22T12:00:00Z", dropped_why=["not wanted"])
    item = dict(kind="fix", ip=5, time=10, found_at="2026-10-22T08:00:00Z", found_in="fixture", title="Item x loses a row", what=["x loses a row"],
                why=["a row is lost"], failing_case=["y"])
    item.update(ev)
    return item


def jtext(obj: dict) -> str:
    return json.dumps(obj, indent=2) + "\n"


class Gate(Base):
    """The merge gate (PreToolUse), T15 (a)-(p) of docs/plans/review-gate.md section 12.2."""
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.fixgate = os.path.join(cls.tmp, "fixgate")
        write(cls.fixgate, '#!/bin/sh\necho "ci: fixture ok"\nexit "${FIXGATE_EXIT:-0}"\n')
        os.chmod(cls.fixgate, 0o755)

    def m15(self, norelay: bool = False) -> None:
        """master holds lib/a.py (v1), bin/x (six lines), .relay/queue/x.json (a taken fix item), a kit.toml whose gate is the fixture
        gate; M = main checkout, W = .worktrees/t on wt/t (no commit yet)."""
        type(self).n += 1
        self.M = os.path.join(self.tmp, "g%d" % self.n)
        self.S = os.path.join(self.tmp, "gs%d" % self.n)
        os.makedirs(self.S)
        os.makedirs(self.M)
        self.git(self.M, "init", "-q", "-b", "master", ".")
        write(os.path.join(self.M, ".gitignore"), ".ci/\n.worktrees/\n")
        write(os.path.join(self.M, "lib", "a.py"), "v1\n")
        write(os.path.join(self.M, "bin", "x"), "1\n2\n3\n4\n5\n6\n")
        write(os.path.join(self.M, ".claude", "kit.toml"), '[gate]\nci = "%s"\n' % self.fixgate)
        if not norelay:
            write(os.path.join(self.M, ".relay", "README.md"), "x\n")
            write(os.path.join(self.M, ".relay", "queue", "x.json"), jtext(queue_item()))
        self.git(self.M, "add", "-A")
        self.git(self.M, "commit", "-q", "-m", "init")
        self.git(self.M, "worktree", "add", "-q", ".worktrees/t", "-b", "wt/t")
        self.W = os.path.join(self.M, ".worktrees", "t")

    def commitf(self, msg: str, files: Dict[str, str]) -> None:
        for rel, text in files.items():
            write(os.path.join(self.W, rel), text)
        self.git(self.W, "add", "-A")
        self.git(self.W, "commit", "-q", "-m", msg)

    def head(self) -> str:
        return self.git(self.W, "rev-parse", "HEAD")

    def mark(self, open_: int = 0) -> None:
        import relay_marks as m
        c = self.X
        q1 = {"id": "Q1", "path": "lib/a.py", "line": 1, "severity": "HIGH", "rank": "high", "kind": "inside", "summary": "Item x loses a row",
              "failing_case": ["y"], "details": ["a row is lost"], "pass_cases": [], "source": "queue", "since": c, "verdict": "MET", "reason": ["tests/t.sh:1"]}
        f1 = dict(q1, id="F1", source="a.json", verdict="NOT MET", summary="a finding")
        record = {"schema": 2, "type": "check", "head": c, "branch": "wt/t", "item": "x", "gate": None, "scope": [], "notes": [],
                  "findings": [q1] + ([f1] * open_)[:1]}
        m.put(self.W, c, {"schema": 2, "commit": c, "verdict": {"open": open_, "queued": 0}, "check": c + ".check.json", "gate": None,
                          "time": "2026-10-22T10:00:00Z"}, {c + ".check.json": json.dumps(record) + "\n"})

    def gate(self, exit_code: int = 0) -> None:
        import relay_marks as m
        c = self.head()
        path = os.path.join(self.W, ".relay", "checks", c + ".gate.log")
        write(path, "head %s\ncmd fixture\nci: fixture\nexit %s\n" % (c, exit_code))
        m.commit_file(self.W, path, "relay: gate of " + c)

    def green(self) -> None:
        """The case's start: a commit touching lib/a.py, a green gate log and a clean mark for it."""
        self.commitf("fix a", {"lib/a.py": "v2\n"})
        self.X = self.head()
        self.gate(0)
        self.mark(0)

    def pre(self, command: str, cwd: Optional[str] = None) -> None:
        self.run_hook(command, cwd, "s0", "PreToolUse")

    def refused(self, text: str) -> bool:
        return self.rc == 2 and text in self.out

    def allowed(self) -> bool:
        return self.rc == 0 and self.out == ""

    def assertRefused(self, text: str) -> None:
        self.assertTrue(self.refused(text), "rc=%s out=%s" % (self.rc, self.out))

    def assertAllowed(self) -> None:
        self.assertTrue(self.allowed(), "rc=%s out=%s" % (self.rc, self.out))

    def test_a_no_mark(self) -> None:
        self.m15()
        self.commitf("fix a", {"lib/a.py": "v2\n"})
        self.gate(0)
        self.pre(MERGE)
        self.assertRefused("no check mark for wt/t")

    def test_b_mark_open_2(self) -> None:
        self.m15()
        self.commitf("fix a", {"lib/a.py": "v2\n"})
        self.X = self.head()
        self.gate(0)
        self.mark(2)
        self.pre(MERGE)
        self.assertRefused("left 2 things open")
        self.assertIn(".relay/checks/%s.check.json" % self.X, self.out)

    def test_c_clean_mark_and_green_gate(self) -> None:
        self.m15()
        self.green()
        self.pre(MERGE)
        self.assertAllowed()
        self.assertTrue(self.git_ok(self.M, "merge", "-q", "--ff-only", "wt/t"))

    def test_d_handover_commit_after(self) -> None:
        self.m15()
        self.green()
        self.commitf("handover", {"docs/handover.md": "state\n"})
        self.pre(MERGE)
        self.assertAllowed()

    def test_e_code_after_the_check(self) -> None:
        self.m15()
        self.green()
        self.commitf("more", {"lib/a.py": "v3\n"})
        self.pre(MERGE)
        self.assertRefused("after the check of %s, wt/t changed lib/a.py" % self.X)

    def test_f_only_inert_files(self) -> None:
        self.m15()
        self.commitf("handover", {"docs/handover.md": "state\n"})
        self.pre(MERGE)
        self.assertAllowed()

    def test_g_no_relay_dir_is_silent_with_control(self) -> None:
        self.m15(norelay=True)
        self.commitf("fix a", {"lib/a.py": "v2\n"})
        self.pre(MERGE)
        self.assertAllowed()
        self.m15()
        self.commitf("fix a", {"lib/a.py": "v2\n"})
        self.pre(MERGE)
        self.assertRefused("no check mark")

    def test_h_behind_master_then_taken(self) -> None:
        self.m15()
        self.green()
        write(os.path.join(self.M, ".relay", "queue", "y.md"), "q\n")
        self.git(self.M, "add", "-A")
        self.git(self.M, "commit", "-q", "-m", "queue y")
        self.pre(MERGE)
        self.assertRefused("wt/t is behind master by 1 commit; run relay land wt/t: it takes master, gates the result and lands it (one landing at a time)")
        self.git(self.W, "merge", "-q", "--no-edit", "master")
        self.pre(MERGE)
        self.assertAllowed()
        self.assertTrue(self.git_ok(self.M, "merge", "-q", "--ff-only", "wt/t"))

    def test_i_code_came_in_until_relay_gate_is_green(self) -> None:
        self.m15()
        self.green()
        write(os.path.join(self.M, "lib", "b.py"), "b\n")
        self.git(self.M, "add", "-A")
        self.git(self.M, "commit", "-q", "-m", "b")
        self.git(self.W, "merge", "-q", "--no-edit", "master")
        self.pre(MERGE)
        self.assertRefused("code changed since: lib/b.py; run relay gate in .worktrees/t")
        done = self.sh(self.M, RELAY, "gate", "-C", self.W)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.pre(MERGE)
        self.assertAllowed()

    def test_j_reverted_checked_fix(self) -> None:
        # the fix also adds lib/c.py, so the branch still differs from master after the revert (a net-empty branch would be all inert)
        self.m15()
        self.commitf("fix a and c", {"lib/a.py": "v2\n", "lib/c.py": "c\n"})
        self.X = self.head()
        self.gate(0)
        self.mark(0)
        self.commitf("revert", {"lib/a.py": "v1\n"})
        self.pre(MERGE)
        self.assertRefused("changed lib/a.py")

    def test_k_combined_file(self) -> None:
        self.m15()
        self.commitf("fix a and x", {"lib/a.py": "v2\n", "bin/x": "1a\n2\n3\n4\n5\n6\n"})
        before = self.X = self.head()
        self.gate(0)
        self.mark(0)
        write(os.path.join(self.M, "bin", "x"), "1\n2\n3\n4\n5\n6a\n")
        self.git(self.M, "commit", "-q", "-am", "x end")
        self.git(self.W, "merge", "-q", "--no-edit", "master")
        self.pre(MERGE)
        # a clean take git did by itself needs no new check (relay land design 4.2), only a new gate: the stale gate refuses, naming bin/x
        self.assertRefused("code changed since: bin/x")
        S = self.S
        write(os.path.join(S, "review.toml"), 'report = "%s/f.json"\nreviewed = "%s"\nbase = "master"\n[[finding]]\nid = "F1"\npath = "bin/x"\nline = 1\n'
              'severity = "MEDIUM"\nkind = "inside"\nsummary = "combined with master\'s change by the merge"\n'
              'failing_case = "the gate fails or the merge does not apply"\n' % (S, before))
        self.sh(self.M, RELAY, "check", "record", "review", "--input", os.path.join(S, "review.toml"))
        headg = self.head()
        self.sh(self.M, RELAY, "gate", "-C", self.W)
        headk = self.head()
        write(os.path.join(S, "check.toml"), 'report = "%s/rep.json"\nhead = "%s"\nworktree = "%s"\ngate = "%s.gate.log"\nreview = ["%s/f.json"]\n'
              '[[status]]\nid = "Q1"\nverdict = "MET"\n[[status]]\nid = "F1"\nverdict = "MET"\n[[status]]\nid = "M1"\nverdict = "MET"\n' % (S, headk, self.W, headg, S))
        self.sh(self.M, RELAY, "check", "record", "check", "--input", os.path.join(S, "check.toml"))
        prompt = "Check: `%s/f.json`. Fixes: `none`. Worktree: `%s`. Check command: `bin/ci --quick`. Gate: `none`. Report: `%s/rep.json`." % (S, self.W, S)
        write(os.path.join(S, "agent.jsonl"), json.dumps({"type": "user", "timestamp": "2026-10-22T10:00:00.000Z", "message": {"role": "user", "content": prompt}}) + "\n")
        subprocess.run([sys.executable, "-I", CHECKMARK], input=json.dumps({"hook_event_name": "SubagentStop", "agent_type": "delegate:checker", "agent_id": "a1",
                                                                             "cwd": self.M, "agent_transcript_path": os.path.join(S, "agent.jsonl")}),
                       capture_output=True, text=True, encoding="utf-8")
        self.pre(MERGE)
        self.assertAllowed()  # the check with the script-made merge finding by the real hook + a green gate

    def test_l_gate_log_of_F_with_mark_and_handover(self) -> None:
        self.m15()
        self.commitf("fix a", {"lib/a.py": "v2\n"})
        self.X = self.head()
        self.gate(0)
        self.mark(0)
        self.commitf("handover", {"docs/handover.md": "state\n"})
        self.pre(MERGE)
        self.assertAllowed()

    def test_m_red_gate_log(self) -> None:
        self.m15()
        self.commitf("fix a", {"lib/a.py": "v2\n"})
        g = self.X = self.head()
        self.gate(1)
        self.mark(0)
        self.pre(MERGE)
        self.assertRefused("last gate %s: exit 1" % g)

    def test_m2_newest_gate_on_unchanged_code_decides(self) -> None:
        self.m15()
        self.commitf("fix a", {"lib/a.py": "v2\n"})
        self.X = self.head()
        self.gate(0)
        self.mark(0)
        g2 = self.head()
        self.gate(1)
        self.pre(MERGE)
        self.assertRefused("last gate %s: exit 1" % g2)
        self.gate(0)
        self.pre(MERGE)
        self.assertAllowed()

    def test_n_item_closed_in_place(self) -> None:
        self.m15()
        self.commitf("fix a, close x", {"lib/a.py": "v2\n", ".relay/queue/x.json": jtext(queue_item("done", "tests/t.sh::case_x"))})
        self.X = self.head()
        self.gate(0)
        self.mark(0)
        self.pre(MERGE)
        self.assertRefused("closed without a test or a check")  # its test file is not in the tree
        self.commitf("test", {"tests/t.sh": "case_x() { :; }\n"})
        self.X = self.head()
        self.gate(0)
        self.mark(0)
        self.pre(MERGE)
        self.assertAllowed()
        self.commitf("name gone", {"tests/t.sh": "other() { :; }\n"})
        self.X = self.head()
        self.gate(0)
        self.mark(0)
        self.pre(MERGE)
        self.assertRefused("closed without a test")

    def test_n2_done_folder_is_gone(self) -> None:
        self.m15()
        os.makedirs(os.path.join(self.W, ".relay", "queue", "done"))
        self.git(self.W, "mv", ".relay/queue/x.json", ".relay/queue/done/x.json")
        self.git(self.W, "commit", "-q", "-m", "move x")
        self.pre(MERGE)
        self.assertRefused("done/, which is gone; run relay queue migrate")
        self.m15()
        os.makedirs(os.path.join(self.W, ".relay", "queue", "done"))
        self.git(self.W, "mv", ".relay/queue/x.json", ".relay/queue/done/x.json")
        self.git(self.W, "commit", "-q", "-m", "move x")
        self.green()
        self.pre(MERGE)
        self.assertRefused("done/, which is gone; run relay queue migrate")  # whatever else the branch holds
        self.m15()
        self.green()
        write(os.path.join(self.M, ".relay", "queue", "y.json"), jtext(queue_item("dropped")))
        self.git(self.M, "add", "-A")
        self.git(self.M, "commit", "-q", "-m", "drop y")
        self.git(self.W, "merge", "-q", "--no-edit", "master")
        self.pre(MERGE)
        self.assertAllowed()  # a dropped item that came through master is not judged

    def newq(self, **extra: object) -> str:
        item = dict(kind="fix", ip=5, time=10, found_at="2026-10-22T08:00:00Z", found_in="fixture", title="Item x loses a row", what=["x loses a row"],
                    why=["a row is lost"], failing_case=["y"], taken_at="2026-10-22T10:00:00Z", taken_by="wt/t")
        item.update(extra, dropped_at=None, dropped_why=None)
        return json.dumps(item) + "\n"

    def checked_commit(self, msg: str, files: Dict[str, str]) -> None:
        self.commitf(msg, files)
        self.X = self.head()
        self.gate(0)
        self.mark(0)

    def test_n3_dated_events(self) -> None:
        self.m15()
        self.checked_commit("fix a, close x", {"lib/a.py": "v2\n", "tests/t.sh": "case_x() { :; }\n",
                                               ".relay/queue/x.json": self.newq(closed_at="2026-10-24T01:00:00Z", test="tests/t.sh::case_x")})
        self.pre(MERGE)
        self.assertAllowed()  # a well-formed new-shape item closed in place
        self.checked_commit("closed_at before taken_at", {".relay/queue/x.json": self.newq(closed_at="2026-10-21T20:00:00Z", test="tests/t.sh::case_x")})
        self.pre(MERGE)
        self.assertRefused("queue item x is malformed")
        self.checked_commit("old shape", {".relay/queue/x.json": '{"kind": "fix", "state": "done", "found": "2026-10-22", "closed_by": "wt/t"}\n'})
        self.pre(MERGE)
        self.assertRefused("relay queue migrate")  # a branch started before the migration
        self.m15()
        self.green()
        write(os.path.join(self.M, ".relay", "queue", "x.json"), self.newq(closed_at="2026-10-24T01:00:00Z", test="tests/t.sh::case_x"))
        self.git(self.M, "add", "-A")
        self.git(self.M, "commit", "-q", "-m", "an older branch closed x")
        self.git(self.W, "merge", "-q", "--no-edit", "master")
        self.pre(MERGE)
        self.assertAllowed()  # x already closed on master, not closed by this branch: not judged
        self.m15()
        self.checked_commit("old shape in the open folder", {".relay/queue/z.json": '{"kind": "feature", "state": "open", "found": "2026-10-22"}\n'})
        self.pre(MERGE)
        self.assertRefused("relay queue migrate")

    def test_n4_old_shape_item_through_master(self) -> None:
        self.m15()
        self.green()
        write(os.path.join(self.M, ".relay", "queue", "late.json"), '{"kind": "feature", "state": "open", "found": "2026-10-22"}\n')
        self.git(self.M, "add", "-A")
        self.git(self.M, "commit", "-q", "-m", "late old-shape item")
        self.git(self.W, "merge", "-q", "--no-edit", "master")
        self.pre(MERGE)
        self.assertRefused("relay queue migrate")

    def test_o_code_moved_into_an_inert_folder(self) -> None:
        self.m15()
        os.makedirs(os.path.join(self.W, ".relay", "queue"), exist_ok=True)
        self.git(self.W, "mv", "lib/a.py", ".relay/queue/a.py")
        self.git(self.W, "commit", "-q", "-m", "move a")
        self.pre(MERGE)
        self.assertRefused("no check mark")
        self.m15()
        self.commitf("handover", {"docs/handover.md": "state\n"})
        self.pre(MERGE)
        self.assertAllowed()  # control (f)

    def test_p_merge_inside_a_task_worktree_is_not_judged(self) -> None:
        self.m15()
        self.commitf("fix a", {"lib/a.py": "v2\n"})
        self.git(self.M, "worktree", "add", "-q", ".worktrees/w", "-b", "wt/w")
        w = os.path.join(self.M, ".worktrees", "w")
        self.pre("git -C %s merge --ff-only wt/t" % w, w)
        self.assertAllowed()
        self.pre(MERGE)
        self.assertRefused("no check mark")  # control (a)


if __name__ == "__main__":
    unittest.main()
