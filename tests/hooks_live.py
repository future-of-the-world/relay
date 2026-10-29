"""Smoke test of the hooks inside a real Claude Code session (claude -p, Haiku, a few cents; port of hooks-live.test.sh).
The plugins load from this checkout with --plugin-dir, in a throwaway repo.
  - a stage typed as a slash command (/openspec:archive) gets the project's addition (UserPromptSubmit);
  - an agent (openspec:author) gets its addition at start (SubagentStart);
  - the guard refuses a shell write in the main checkout, and the same write in a worktree goes through.
The unit tests feed the hooks JSON by hand; this one proves that Claude Code sends what they expect. Skipped, loudly,
when `claude` is missing or HOOKS_LIVE=0 is set. Each session runs with --output-format stream-json (with the hook events):
the checks read only its final "result" line, so a hook's own text cannot pass a case. User-level settings and plugins are
not loaded (--setting-sources project,local). On a failure the four raw outputs are kept in a folder whose path is printed.
  python3 tests/hooks_live.py"""
import os
import shutil
import subprocess
import sys
import tempfile
from typing import List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "plugins", "relay")
OPENSPEC = os.path.join(ROOT, "plugins", "openspec")


def git(cwd: str, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(args), cwd=cwd, check=True, capture_output=True)


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def result_line(path: str) -> str:
    """The session's final answer: not the hook events, which may hold the codeword."""
    with open(path, errors="replace") as handle:
        return "\n".join(line for line in handle.read().splitlines() if '"type":"result"' in line)


def shown(path: str) -> str:
    """The result line; with none (crash, auth error) the raw tail."""
    found = result_line(path)
    if found:
        return found
    with open(path, errors="replace") as handle:
        return handle.read()[-400:]


def main() -> int:
    if os.environ.get("HOOKS_LIVE", "1") == "0" or shutil.which("claude") is None:
        print("hooks-live.test: SKIPPED (claude not on PATH, or HOOKS_LIVE=0): the hooks were not run in a real session")
        return 0
    tmp = os.path.realpath(tempfile.mkdtemp())
    try:
        return run_cases(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_cases(tmp: str) -> int:
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "master", ".")
    write(os.path.join(repo, ".claude", "kit.toml"), '[project]\ndefault_branch = "master"\nworktrees = ".worktrees"\n')
    write(os.path.join(repo, ".claude", "kit", "archive.md"), "The project codeword for the archive stage is OTTER-77.\n")
    write(os.path.join(repo, ".claude", "kit", "author.md"), "The project codeword for the author is BADGER-31.\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "worktree", "add", "-q", ".worktrees/w", "-b", "wt/w")

    probe = "Run exactly this command with the Bash tool, nothing else: echo probe > guard-probe.txt   Then reply "
    sessions = [
        ("stage", repo, "/openspec:archive Do not archive anything. Reply with only the project codeword for the archive stage, or NONE if you were given none.", []),
        ("agent", repo, "Start the agent openspec:author with the Agent tool (subagent_type openspec:author) and this prompt: 'Do not start any work. Reply with only the project codeword for the author, or NONE if you were given none.' Then reply with only what the agent replied.", []),
        ("guard", repo, probe + "with the tool's result text.", ["--allowedTools=Bash"]),
        ("control", os.path.join(repo, ".worktrees", "w"), probe + "DONE.", ["--allowedTools=Bash"]),
    ]
    procs = []
    for name, cwd, prompt, extra in sessions:
        out = open(os.path.join(tmp, name + ".out"), "w")
        cmd = ["claude", "-p", "--model", "haiku", "--max-budget-usd", "0.5", "--plugin-dir", CORE, "--plugin-dir", OPENSPEC,
               "--output-format", "stream-json", "--verbose", "--include-hook-events", "--setting-sources", "project,local"] + extra + [prompt]
        procs.append((subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT), out))
    for proc, out in procs:
        proc.wait()
        out.close()

    out_of = lambda name: os.path.join(tmp, name + ".out")  # noqa: E731
    checks = [
        ("a typed /openspec:archive gets the project's archive addition", "OTTER-77" in result_line(out_of("stage")), "stage"),
        ("openspec:author gets the project's author addition at its start", "BADGER-31" in result_line(out_of("agent")), "agent"),
        ("the guard refuses a shell write in the main checkout",
         not os.path.exists(os.path.join(repo, "guard-probe.txt")) and "guard-main" in result_line(out_of("guard")), "guard"),
        ("the same write in a worktree goes through", os.path.exists(os.path.join(repo, ".worktrees", "w", "guard-probe.txt")), "control"),
    ]
    fails: List[str] = []
    for text, ok, name in checks:
        if ok:
            print("ok    " + text)
        else:
            print("FAIL  %s: %s" % (text, shown(out_of(name))[:400].replace("\n", " ")))
            fails.append(text)
    if not fails:
        print("hooks-live.test: all passed")
        return 0
    kept = tempfile.mkdtemp(prefix="hooks-live-", dir=os.environ.get("TMPDIR", "/tmp"))
    for name, _, _, _ in sessions:
        shutil.copy(out_of(name), os.path.join(kept, name + ".out"))
    print("hooks-live.test: %d failed; the sessions' stream-json output (hook events included) is kept in %s" % (len(fails), kept))
    return 1


if __name__ == "__main__":
    sys.exit(main())
