#!/usr/bin/env python3
"""front: SessionStart after a compaction or /clear names the project's handover
file, so the session reads it instead of asking the owner to repeat anything.
Also on startup and resume, when the file exists: a one-line pointer. Fails open."""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import json
import os
import subprocess
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import handover_path  # noqa: E402

try:
    import relay_queue  # noqa: E402
except ImportError:   # a copy of the plugin without the queue module: no queue line
    relay_queue = None  # type: ignore[assignment]

TEXT = {
    "compact": "The conversation was just compacted. The project's handover file is {path}: the record of where the work stands. Read it before acting, continue from it and from the summary, and do not ask the owner to repeat anything.",
    "clear": "The conversation was just cleared. The project's handover file is {path}. Read it before acting and continue from it.",
    "startup": "This project keeps its state in {path}. Read it before the first piece of work.",
    "resume": "This project keeps its state in {path}. If the summary and the file disagree, the file is newer.",
    "fork": "This project keeps its state in {path}.",
}


def _git(cwd: str, *args: str) -> Any:
    """Stdout of a read-only git command, stripped; None when git fails or is missing."""
    try:
        run = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return run.stdout.strip() if run.returncode == 0 else None


def bin_relay_line() -> str:
    """A line when bin/relay in relay's main checkout is not what HEAD holds (the 28 Oct eval stub), else "". It is checked here,
    in the hook's own Python, because a replaced bin/relay is the program that would run `relay doctor`: the check cannot live in it.
    Only rev-parse and hash-object are used: no `git status`, so no index.lock and no index rewrite in the live checkout."""
    root = os.environ.get("RELAY_ROOT") or os.path.join(HERE, "..", "..", "..")
    gitdir, common = (_git(root, "rev-parse", "--path-format=absolute", flag) for flag in ("--git-dir", "--git-common-dir"))
    if not gitdir or not common:
        return ""
    if os.path.realpath(gitdir) != os.path.realpath(common):   # a linked worktree: a branch may edit bin/relay; only the main checkout counts
        if os.path.basename(os.path.realpath(common)) != ".git":
            return ""
        root = os.path.dirname(os.path.realpath(common))
    root = os.path.realpath(root)
    head = _git(root, "rev-parse", "HEAD:bin/relay")
    if head is None or _git(root, "hash-object", "--", "bin/relay") == head:
        return ""
    return (f"relay is broken: bin/relay in {root} differs from HEAD (an eval stub or a stray edit). Restore it in a terminal outside the "
            f"session: git -C {root} restore --source=HEAD --staged --worktree bin/relay")


def main() -> None:
    data = json.load(sys.stdin)
    cwd = data.get("cwd") or os.getcwd()
    parts: list[str] = []
    broken = bin_relay_line()
    if broken:
        parts.append(broken)   # first line: nothing else works until this is fixed
    source = data.get("source") or ""
    text = TEXT.get(source)
    path = handover_path.resolve(cwd) if text else None
    if text and path:
        parts.append(text.format(path=path))
    # the default branch's work queue, the same from every worktree (design 10.5); the owner sees it too
    queue = relay_queue.session_line(cwd) if relay_queue else ""   # type: ignore[no-untyped-call]  # relay_queue is annotated after wt/checks-record merges
    if queue:
        parts.append(queue)
    if not parts:
        return
    out: dict[str, Any] = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(parts)}}
    messages: list[str] = []
    if path and source == "resume" and data.get("prompt_cache_likely_expired") and data.get("estimated_cache_write_usd"):
        messages.append(f"Resuming re-sends {data.get('context_tokens', 0) // 1000}k tokens, about "
                        f"${data['estimated_cache_write_usd']:.2f}; a fresh session from the handover file is cheaper.")
    if broken:
        messages.insert(0, broken)
    if queue:
        messages.append(queue)
    if messages:
        out["systemMessage"] = "\n".join(messages)
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
