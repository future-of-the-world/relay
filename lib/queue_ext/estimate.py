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
        found = relay_estimate.measure_item(rows, item)
        if found is not None:
            measured[item["slug"]] = found
    for line in relay_estimate.compare_lines(items, measured):
        print(line)
    print(relay_estimate.next_estimate_text(list(measured.values())))
    return 0
