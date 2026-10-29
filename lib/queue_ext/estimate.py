"""`relay queue estimate`: each closed item's estimate beside the minutes its agents and the clock really took, and the estimate for a
new item. Derived from the agent transcripts when read; nothing is stored."""

import os

import relay_estimate


def repo_top(folder: str) -> str:
    """The repo folder: a `.worktrees/<name>` (or the project's own worktrees folder) working folder stands for the repo above it, whose project folders hold the change's agents."""
    repo = os.path.dirname(os.path.dirname(folder))
    if os.path.basename(os.path.dirname(folder)) in {".worktrees", relay_estimate.worktree_folder(repo)}:
        return repo
    return folder


def run(items: list[dict], args: list[str]) -> int:
    """`args` may carry `--root <repo folder>`; without it the current folder is the repo."""
    root = repo_top(os.getcwd())
    if "--root" in args and args.index("--root") + 1 < len(args):
        root = repo_top(args[args.index("--root") + 1])
    projects = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"), "projects")
    rows = relay_estimate.agent_rows(projects, root)
    measured = {}
    for item in items:
        if item["problems"]:
            continue
        found = relay_estimate.measure_item(rows, item, items)
        if found is not None:
            measured[item["slug"]] = found
    for line in relay_estimate.compare_lines(items, measured):
        print(line)
    print(relay_estimate.next_estimate_text(list(measured.values())))
    top = repo_top(root)
    home = os.path.expanduser(os.environ.get("RELAY_HOME") or "~/.relay")
    print(relay_estimate.paid_run_text(os.path.join(home, "evals", os.path.basename(top))))
    closed = [i for i in items if i.get("closed_at") and i.get("taken_by") and not i["problems"]]
    print(f"coverage: {len(measured)} of {len(closed)} closed items have agents in the transcripts")
    return 0
