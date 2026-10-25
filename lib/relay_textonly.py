"""The text-only list: files whose edit only the rule readers can see (rule parsing, rule tests, `relay sync --dry`).

The list is fixed here, not a setting. A change whose every non-inert file is on it gets the short rules gate in
`bin/ci --quick`; one file outside it, or any doubt (no default branch, git failing), gets the full quick gate.
Patterns are the ones of `relay_inert` ("*" inside one path part, "**" any number of whole parts).

    python3 lib/relay_textonly.py check   exit 0 when the change since the default branch is text-only, 1 when not
    python3 lib/relay_textonly.py tests   the unittest names the short gate runs, one per line
"""

import os
import sys

import relay_inert

TEXT_ONLY = (
    "rules/*.md",
)

# The tests that read rules/*.md: rule parsing and rendering, the rule texts, the rules the delegation text quotes.
RULE_TESTS = (
    "tests.test_python_rule",
    "tests.test_it_terms.ItTerms",
    "tests.test_sync_refused",
    "tests.test_session_profile",
    "tests.test_net_retry",
    "tests.test_delegate_small_builds",
    "tests.test_queue.TestStructuredRule",
    "tests.test_relay.Rules",
    "tests.test_relay.Roles",
    "tests.test_relay.Agents",
    "tests.test_relay.TestPrinciplesRule",
    "tests.test_relay.AutoMergeTextsTest",
    "tests.test_relay.Bench",
    "tests.test_queue.TestFrontSkill",
    "tests.test_bench_worker",
    "tests.test_paid_batch",
    "tests.test_spec_steps.RenderedRules",
    "tests.test_front_measures",
)

_COMPILED = [relay_inert._regex(p) for p in TEXT_ONLY]


def matches(path: str) -> bool:
    """True when `path` (repository-relative) is on the text-only list."""
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return any(rx.match(path) for rx in _COMPILED)


def only(paths: list[str]) -> bool:
    """True when `paths` is not empty and every path is on the list."""
    return bool(paths) and all(matches(p) for p in paths)


def uncommitted(repo: str) -> list[str]:
    """Paths with uncommitted edits (staged, unstaged, untracked; both ends of a rename) that are not inert."""
    out = relay_inert._git(repo, "status", "--porcelain", "-z", "-uall").split("\0")
    paths: list[str] = []
    i = 0
    while i < len(out):
        entry = out[i]
        i += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC" or entry[1] in "RC":
            paths.append(out[i])  # the other end of a rename or copy
            i += 1
    return [p for p in paths if not relay_inert.matches(p)]


def is_text_only(repo: str, until: str = "HEAD") -> bool:
    """True when what `until` changed since the default branch (inert files left out) is text-only.
    False when it cannot be told: the full gate is the safe answer."""
    try:
        default = relay_inert._default_ref(repo)
        base = relay_inert._git(repo, "merge-base", until, default).strip()
        # A hand run of bin/ci sees uncommitted edits too: one off the list means the full gate.
        return only(relay_inert.changed(repo, base, until) + uncommitted(repo))
    except ValueError:
        return False


def main(argv: list[str]) -> int:
    if argv[1:] == ["check"]:
        return 0 if is_text_only(os.getcwd()) else 1
    if argv[1:] == ["tests"]:
        print("\n".join(RULE_TESTS))
        return 0
    print("usage: relay_textonly.py check|tests", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
