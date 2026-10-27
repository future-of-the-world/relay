"""`relay queue json`: the ordered items (closed and dropped ones too, with all their dates) as one JSON list, for scripts. A queue extension reads items and prints; it never writes them."""

import json as jsonlib

import relay_queue


def run(items, args):
    shown = [dict(i, notes=[relay_queue.note_dict(n) for n in i["notes"]]) if i.get("notes") else i for i in items]
    print(jsonlib.dumps(shown, indent=2, ensure_ascii=False))
    return 0
