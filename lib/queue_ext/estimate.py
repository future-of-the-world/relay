"""`relay queue estimate`: each closed item's estimate beside the minutes its agents and the clock really took, and the estimate for a
new item. Derived from the agent transcripts when read; nothing is stored."""

import os

import relay_estimate


def run(items, args):
    projects = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"), "projects")
    measured = relay_estimate.by_change(relay_estimate.agent_rows(projects))
    lines = relay_estimate.compare_lines(items, measured)
    for line in lines:
        print(line)
    history = [measured[i["taken_by"].removeprefix("wt/")] for i in items
               if not i["problems"] and i["closed_at"] and i["taken_by"] and i["taken_by"].removeprefix("wt/") in measured]
    print(relay_estimate.next_estimate_text(history))
    return 0
