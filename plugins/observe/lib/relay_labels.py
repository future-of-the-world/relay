"""The label an agent is started with: `<stage>[ n]: <unit>`, optionally followed by ` - ` and free words for the person.
The workflow scripts give it, the routing guard demands it of agents started by hand, the ledger hook keeps it (never the free words)."""

from __future__ import annotations   # the hooks may run under Python 3.9

import re
from typing import Optional

STAGES = ("build", "gate", "fix red gate", "review", "fix", "check", "check item", "close queue item", "check show",
          "design", "design review", "design revise", "land", "other")
STAGE_LABEL = re.compile(r"^(" + "|".join(STAGES) + r")( \d+)?: [a-z0-9][a-z0-9-]{0,63}$")
FREE = " - "


def label_of(description: str) -> Optional[str]:
    """The label at the start of a description (the free words after ` - ` dropped), or None when it has no label."""
    head = description.split(FREE, 1)[0].strip()
    return head if STAGE_LABEL.match(head) else None
