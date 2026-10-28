"""`relay queue estimate`: each closed item's estimate beside the minutes its agents and the clock really took, and the estimate for a
new item. Derived from the agent transcripts when read; nothing is stored."""

import os

import relay_estimate


def run(items: list[dict], args: list[str]) -> int:
    """`args` may carry `--root <repo folder>`; without it the current folder is the repo."""
    root = os.getcwd()
    if "--root" in args and args.index("--root") + 1 < len(args):
        root = args[args.index("--root") + 1]
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
    top = root
    if os.path.basename(os.path.dirname(top)) == ".worktrees":
        top = os.path.dirname(os.path.dirname(top))
    home = os.path.expanduser(os.environ.get("RELAY_HOME") or "~/.relay")
    print(relay_estimate.paid_run_text(os.path.join(home, "evals", os.path.basename(top))))
    closed = [i for i in items if i.get("closed_at") and i.get("taken_by") and not i["problems"]]
    print(f"coverage: {len(measured)} of {len(closed)} closed items have agents in the transcripts")
    return 0
