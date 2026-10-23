"""`relay queue json`: the ordered items (closed and dropped ones too, with all their dates) as one JSON list, for scripts. A queue extension reads items and prints; it never writes them."""

import json as jsonlib


def run(items, args):
    print(jsonlib.dumps(items, indent=2, ensure_ascii=False))
    return 0
