#!/usr/bin/env python3
"""front: Stop hook. The front's reply to the owner must be in the owner's native
language. When "My native language: <name>" (written by relay sync into
~/.claude/CLAUDE.md) names a language with a non-Latin script, the share of that
script among the reply's prose letters (code blocks, inline code, URLs and paths
removed) is measured; under the threshold the stop is blocked once with a rewrite
request. A share, never a per-character check. Fails open."""

import json
import os
import re
import sys
import unicodedata

# language -> Unicode name prefix of its script; extend only with scripts that are tested
SCRIPTS = {"russian": "CYRILLIC", "ukrainian": "CYRILLIC"}
THRESHOLD = 0.60     # least share of native-script letters in the prose; RELAY_REPLY_LANG_SHARE overrides
MIN_LETTERS = 40     # a reply with fewer prose letters (mostly code or paths) is not checked

FENCE = re.compile(r"(```|~~~).*?(\1|\Z)", re.S)
INLINE = re.compile(r"`[^`\n]*`")
URL = re.compile(r"\w+://\S+")
PATHLIKE = re.compile(r"\S*/\S*")


def native_language():
    # the config folder the session uses, as relay_config.claude_dir() reads it
    folder = os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")
    try:
        with open(os.path.join(folder, "CLAUDE.md"), encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\s*My native language:\s*([^.\n]+)", line)
                if m:
                    return m.group(1).strip()
    except OSError:
        pass
    return ""


def prose_letters(text):
    for rx in (FENCE, INLINE, URL, PATHLIKE):
        text = rx.sub(" ", text)
    return [ch for ch in text if ch.isalpha()]


def share(text, script):
    letters = prose_letters(text)
    if len(letters) < MIN_LETTERS:
        return None
    native = sum(1 for ch in letters if unicodedata.name(ch, "").startswith(script))
    return native / len(letters)


def last_reply(data):
    if isinstance(data.get("last_assistant_message"), str):
        return data["last_assistant_message"]
    last = ""
    try:
        with open(data.get("transcript_path") or "", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                msg = entry.get("message") or {}
                if entry.get("type") == "assistant" and isinstance(msg.get("content"), list):
                    text = "".join(b.get("text", "") for b in msg["content"] if b.get("type") == "text")
                    if text:
                        last = text
    except (OSError, ValueError):
        pass
    return last


def threshold():
    try:
        value = float(os.environ.get("RELAY_REPLY_LANG_SHARE") or THRESHOLD)
    except ValueError:
        return THRESHOLD
    return value / 100 if value > 1 else value


def main():
    data = json.load(sys.stdin)
    if data.get("stop_hook_active") or data.get("agent_id"):
        return
    # a session started by a program (evals, bench graders) is not the owner's: its reply goes to a script
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk") or os.environ.get("RELAY_BENCH"):
        return
    language = native_language()
    script = SCRIPTS.get(language.lower())
    if not script:
        return
    got = share(last_reply(data), script)
    if got is None or got >= threshold():
        return
    json.dump({"decision": "block", "reason": f"Rewrite the reply in {language}, the owner's native language "
                                              f"(only {got:.0%} of its letters are in {language}); code, paths and names stay as they are."}, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
