"""The gate's look at the branch's `.claude/kit.toml`: the refusal text for a mistake in it (split out of relay_gate to keep that module small)."""
from __future__ import annotations

from typing import Optional

import relay_git
import relay_kit
from relay_gate_kit import settings_problems


def refusal(worktree: str) -> Optional[str]:
    """The refusal naming each mistake in the branch's .claude/kit.toml (an unknown key, a wrong type, a value outside the allowed ones), None when it holds none."""
    lines = settings_problems(worktree, relay_kit)  # the branch's own lib/relay_kit.py; RuntimeError when it cannot be run
    if not lines:
        return None
    if any("is an old name" in line for line in lines) and kit_unchanged_from_default(worktree):
        # the branch did not write the old name, it inherited it: the step is to take the default branch, not `relay setup`
        lines = [line.replace("`relay setup` renames it", "this branch did not write it: take the default branch") for line in lines]
    return "settings problem in the branch's .claude/kit.toml: " + "; ".join(lines)


def kit_unchanged_from_default(worktree: str) -> bool:
    """True when the branch holds the same .claude/kit.toml as its merge-base with the default branch (it changed nothing there)."""
    main = relay_git.main_checkout(worktree)
    default = relay_git.default_branch(main) if main else None
    if default is None:
        return False
    return relay_git.git(worktree, "diff", "--quiet", f"{default}...HEAD", "--", ".claude/kit.toml")[0] == 0
