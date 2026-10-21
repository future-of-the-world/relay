"""The inert list: files whose content never decides a check or a merge (state files, not code).

The list is fixed here, not a setting. A pattern matches a path relative to the repository root, with "/" as the
separator: "*" matches inside one path part (any characters but "/"), "**" matches any number of whole parts (zero
or more). `changed()` lists what changed since a commit and is not inert: it is the file list the checker works from.
"""

import re
import subprocess

INERT = (
    "docs/handover.md",
    ".relay/queue/**",
    ".relay/checks/**",
)


def _regex(pattern):
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


_COMPILED = [_regex(p) for p in INERT]


def matches(path):
    """True when `path` (repository-relative) is on the inert list."""
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return any(rx.match(path) for rx in _COMPILED)


def changed(repo, since, until="HEAD"):
    """Files changed from `since` to `until` in `repo` (git diff --name-only since..until) that are not inert."""
    run = subprocess.run(["git", "-C", repo, "diff", "--name-only", f"{since}..{until}"], capture_output=True, text=True)
    if run.returncode != 0:
        raise ValueError(f"git diff {since}..{until} failed in {repo}: {run.stderr.strip()}")
    return [line for line in run.stdout.splitlines() if line and not matches(line)]
