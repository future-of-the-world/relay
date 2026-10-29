#!/usr/bin/env python3
"""The rule text a plugin-eval case gives its session, and the one writer of it.

`claude plugin eval` starts the session with CLAUDE.md loading turned off (CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 and
`--setting-sources user`), so a CLAUDE.md written by a case's scaffold never reaches the session. The one channel the
runner honours is `append_system_prompt` in the case's prompt.md frontmatter. This module builds that text from
rules/*.md, so no copy is kept by hand:

    python3 evals/plugin/system_rules.py        rewrites the `append_system_prompt:` line of every case listed below
    tests/test_eval_system_rules.py             fails when a case's line differs from what this module builds

The spec-step cases are not listed: they get the OpenSpec rule only from the openspec plugin's hook (SessionStart), as a real
session does, so the paid run measures that channel. A system-prompt rule sits higher than a CLAUDE.md rule does in a real session, so pass rates read a little better than life.
"""
import json
import os
from typing import Callable, Dict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
KEY = "append_system_prompt:"


def rule(name: str) -> str:
    with open(os.path.join(ROOT, "rules", name + ".md"), encoding="utf-8") as handle:
        return handle.read()


def language(owner_language: str, glossary: str = "") -> str:
    head = f"My native language: {owner_language}.\n\n"
    if glossary:
        head += f"Project glossary: {glossary}\n\n"
    return head + rule("working-with-me")


def front_rules() -> str:
    return rule("delegation") + rule("working-with-me") + rule("verify")


GLOSSARY = "the gate is this project's full local check before a merge (tests, lint, types)."
CASES: Dict[str, Callable[[], str]] = {
    "it-terms-ru": lambda: language("Russian", GLOSSARY),
    "it-terms-es": lambda: language("Spanish"),
    "design-track": front_rules,
    "explain-existing": front_rules,
    "keep-owner-words": front_rules,
    "keep-owner-words-en": front_rules,
    "no-note-off-topic": front_rules,
    "recall-decision": front_rules,
}


def line(case: str) -> str:
    # The runner closes the frontmatter at the first `---` it finds, even inside a quoted string (a markdown table
    # separator `|---|` cut the spec cases off), so a run of three hyphens is written as \u002d, which both JSON and YAML read as `-`.
    return KEY + " " + json.dumps(CASES[case](), ensure_ascii=False).replace("-", "\\u002d")


def split(case: str):
    """prompt.md as (lines before the closing frontmatter marker, the rest); the second `---` closes the frontmatter."""
    with open(os.path.join(HERE, case, "prompt.md"), encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    marks = [i for i, text in enumerate(lines) if text == "---"]
    return lines, marks[1]


def current(case: str):
    """The case's `append_system_prompt` value, or None."""
    lines, end = split(case)
    for text in lines[:end]:
        if text.startswith(KEY):
            return json.loads(text[len(KEY):].strip())
    return None


def write(case: str) -> None:
    lines, end = split(case)
    lines = [text for i, text in enumerate(lines) if i >= end or not text.startswith(KEY)]
    end = [i for i, text in enumerate(lines) if text == "---"][1]
    lines.insert(end, line(case))
    with open(os.path.join(HERE, case, "prompt.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


if __name__ == "__main__":
    for name in CASES:
        write(name)
