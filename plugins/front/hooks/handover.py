#!/usr/bin/env python3
"""front: SessionStart after a compaction or /clear names the project's handover
file, so the session reads it instead of asking the owner to repeat anything.
Also on startup and resume, when the file exists: a one-line pointer. Fails open."""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import handover_path  # noqa: E402

TEXT = {
    "compact": "The conversation was just compacted. The project's handover file is {path}: the record of where the work stands. Read it before acting, continue from it and from the summary, and do not ask the owner to repeat anything.",
    "clear": "The conversation was just cleared. The project's handover file is {path}. Read it before acting and continue from it.",
    "startup": "This project keeps its state in {path}. Read it before the first piece of work.",
    "resume": "This project keeps its state in {path}. If the summary and the file disagree, the file is newer.",
    "fork": "This project keeps its state in {path}.",
}


def main():
    data = json.load(sys.stdin)
    text = TEXT.get(data.get("source") or "")
    if not text:
        return
    path = handover_path.resolve(data.get("cwd") or os.getcwd())
    if not path:
        return
    out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text.format(path=path)}}
    if data.get("source") == "resume" and data.get("prompt_cache_likely_expired") and data.get("estimated_cache_write_usd"):
        out["systemMessage"] = (f"Resuming re-sends {data.get('context_tokens', 0) // 1000}k tokens, about "
                                f"${data['estimated_cache_write_usd']:.2f}; a fresh session from the handover file is cheaper.")
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
