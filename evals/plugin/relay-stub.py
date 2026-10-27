#!/usr/bin/env python3
"""A stand-in for `relay queue show|note` inside an eval session.

The session's sandbox cannot run git (`/usr/bin/git` writes an xcrun cache under /var/folders), and the real `relay queue`
needs git, so it can never succeed there. setup-relay-stub.sh puts this file at $HOME/relay/bin/relay, the last place
plugins/front/bin/relay looks. It reads ./.relay/queue/*.json of the working folder, writes nothing, and prints what the
real command prints (a note: the text back), so the case's judge sees in the reply what was stored.
"""
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
    print(os.path.basename(hits[0])[:-5])
    print(open(hits[0], encoding="utf-8").read())
    return 0


def note(args: list[str]) -> int:
    if len(args) != 3 or args[1] != "--input":
        print("relay queue note <slug> --input <file.toml>", file=sys.stderr)
        return 2
    if len(find([args[0]])) < 1:
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
