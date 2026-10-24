#!/usr/bin/env python3
"""front: SessionStart after a compaction or /clear names the project's handover
file, so the session reads it instead of asking the owner to repeat anything.
Also on startup and resume, when the file exists: a one-line pointer. Fails open."""

from __future__ import annotations   # the hooks may run under Python 3.9: annotations are never evaluated

import json
import os
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


def main() -> None:
    data = json.load(sys.stdin)
    cwd = data.get("cwd") or os.getcwd()
    parts: list[str] = []
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
