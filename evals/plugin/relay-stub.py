#!/usr/bin/env python3
"""A stand-in for `relay queue show|note` inside an eval session.

The session's sandbox cannot run git (`/usr/bin/git` writes an xcrun cache under /var/folders), and the real `relay queue`
needs git, so it can never succeed there. setup-relay-stub.sh puts this file at $HOME/relay/bin/relay, the last place
plugins/front/bin/relay looks. It reads ./.relay/queue/*.json of the working folder, writes nothing, and prints what the
real command prints for the parts it covers (show: title, What, Why and the Notes lines; note: the text back), so the case's judge sees in the reply what was stored.
"""
import datetime as dt
import glob
import json
import os
import sys
import tomllib

KINDS = ("said", "fact", "question", "answer")


def find(words: list[str]) -> list[str]:
    paths = sorted(glob.glob(os.path.join(".relay", "queue", "*.json")))
    # like the real command, a word may be in the name or anywhere in the item (title, notes)
    out = []
    for p in paths:
        text = (os.path.basename(p) + "\n" + open(p, encoding="utf-8").read()).lower()
        if all(w.lower() in text for w in words):
            out.append(p)
    return out


def local(stamp: str) -> str:
    # same as lib/relay_queue.py _local: the run's local time, "27 Oct 03:00"
    when = dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).astimezone()
    return f"{when.day} {when.strftime('%b %H:%M')}"


def quoted(lines: list[str]) -> list[str]:
    body = ["    " + x for x in lines]
    body[0] = "    \u201c" + lines[0]
    body[-1] += "\u201d"
    return body


def notes_text(item: dict) -> list[str]:
    """The "Notes:" lines, copied from lib/relay_queue.py notes_text (tests/test_eval_cases.py compares the two)."""
    out: list[str] = []
    for n in item.get("notes") or []:
        if "said" in n or "fact" in n:
            kind = "said" if "said" in n else "fact"
            out.append(f"  {local(n['at'])} " + ("the owner said:" if kind == "said" else "fact (front):"))
            out += quoted(n[kind]) if kind == "said" else ["    " + x for x in n[kind]]
            continue
        out.append(f"  {local(n['asked_at'])} question {n['number']}, asked:")
        out += ["    " + x for x in n["question"]] + ["    - " + x for x in n["options"]]
        if not n.get("answered_at"):
            out.append("    not answered yet")
            continue
        out.append(f"  {local(n['answered_at'])} the owner answered question {n['number']} (whole reply):")
        out += quoted(n["answer"])
        reading = n.get("reading") or []
        if reading:
            out += ["    front's reading (owner can reverse): " + reading[0]] + ["    " + x for x in reading[1:]]
    return ["Notes:"] + out if out else []


def show_text(slug: str, item: dict) -> str:
    """slug: title, What, Why, Notes: the lines of lib/relay_queue.py show_text that the stub's items can differ in."""
    out = [f"{slug}: {item.get('title', '')}"]
    for title, key in (("What", "what"), ("Why", "why")):
        if item.get(key):
            out += [f"{title}:"] + ["  " + line for line in item[key]]
        if key == "why":
            out += notes_text(item)
    return "\n".join(out)


def show(words: list[str]) -> int:
    hits = find(words)
    if len(hits) > 1:
        # several matches are listed, then one is shown by its name; an exact name always wins
        exact = [h for h in hits if os.path.basename(h)[:-5] == " ".join(words)]
        if exact:
            hits = exact
        else:
            for h in hits:
                print(os.path.basename(h)[:-5])
            return 0
    if not hits:
        print("relay queue: no item matches %r" % " ".join(words), file=sys.stderr)
        return 1
    with open(hits[0], encoding="utf-8") as fh:
        item = json.load(fh)
    print(show_text(os.path.basename(hits[0])[:-5], item))
    return 0


def note(args: list[str]) -> int:
    if len(args) != 3 or args[1] != "--input":
        print("relay queue note <slug> --input <file.toml>", file=sys.stderr)
        return 2
    # the real command takes the exact slug only (lib/relay_queue.py: reader.items().get(slug))
    if not os.path.exists(os.path.join(".relay", "queue", args[0] + ".json")):
        print("relay queue: no item %s" % args[0], file=sys.stderr)
        return 1
    with open(args[2], "rb") as fh:
        try:
            data = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            print("relay queue: the input is not TOML: %s" % exc, file=sys.stderr)
            return 1
    kinds = [k for k in KINDS if k in data]
    if len(kinds) != 1:
        print("relay queue: the input holds exactly one of said, fact, question, answer", file=sys.stderr)
        return 1
    print("noted %s: %s: %s" % (args[0], kinds[0], json.dumps(data[kinds[0]], ensure_ascii=False)))
    return 0


def main(argv: list[str]) -> int:
    if argv[:2] == ["queue", "show"]:
        return show(argv[2:])
    if argv[:2] == ["queue", "list"]:
        for p in find([]):
            print(os.path.basename(p)[:-5])
        return 0
    if argv[:2] == ["queue", "note"]:
        return note(argv[2:])
    print("relay queue show <slug or words>\nrelay queue note <slug> --input <file.toml>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
