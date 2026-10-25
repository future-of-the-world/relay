"""One-off rewrite: the `where` of every queue item, open and done, from one string to a list of places.

Run once: `python3 lib/relay_where_migrate.py <checkout>`. Every file is written through the queue's writer
(relay_queue.serialize), and nothing is written unless every file can be converted. A file whose `where` is already a
list is left alone. Prints each record that could not be split cleanly, with the original and what was written.

How a string is split: at ", " outside parentheses and quotes, where the next word names a place (a path with a "/" or
a "." in it, or one bare word that is the whole piece, as in "docs"). A piece that does not start that way, and the text
after a first word that is not exactly `path`, `path:N` or `path:N-M`, goes into the note of the element before it and
the record is listed as unclean. A string with no place at all gets the item's own file as its place.
"""

import json
import os
import re
import sys

import relay_queue as rq

FIRST = re.compile(r"[^\s:()]+")      # the path part of a first word, as in rq.PLACE_WORD


def _pieces(text: str) -> list[str]:
    """`text` cut at ", " that is outside parentheses, backticks and double quotes."""
    out, depth, quoted, start = [], 0, "", 0
    for at, char in enumerate(text):
        if quoted:
            quoted = "" if char == quoted else quoted
        elif char in "`\"":
            quoted = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0 and text[at + 1:at + 2] == " ":
            out.append(text[start:at])
            start = at + 2
    out.append(text[start:])
    return [piece.strip() for piece in out if piece.strip()]


def _names_place(piece: str) -> bool:
    """True when the piece starts with a place: a path with "/" or "." in it, or one bare word that is the whole piece."""
    found = FIRST.match(piece)
    if found is None:
        return False
    return "/" in found.group() or "." in found.group() or piece == found.group()


def split_where(slug: str, text: str) -> tuple[list[str], bool]:
    """(the elements of the list, True when the split was clean) for the old string `text` of the item `slug`."""
    elements, clean = [], True
    for piece in _pieces(text):
        if not _names_place(piece):
            if elements:
                elements[-1] += ", " + piece
            else:
                elements.append(f"{rq._path(slug)} {piece}")      # no place at all: the item's own file is the place
            clean = False
        elif rq.parse_place(piece) is None:
            path = FIRST.match(piece).group()                     # e.g. "lib/a.py:22,28-35 note": keep the rest as the note
            elements.append(f"{path} {piece[len(path):].strip()}".strip())
            clean = False
        else:
            elements.append(piece)
    return elements, clean


def migrate(root: str) -> tuple[list[str], list[tuple[str, str, list[str]]]]:
    """Rewrite every item under `root`/.relay/queue and its done/ folder. Returns (the paths rewritten, sorted;
    [(slug, original, written)] of the records not split cleanly)."""
    base = os.path.join(root, rq.QDIR)
    if not os.path.isdir(base):
        raise rq.Refused(f"no {rq.QDIR} folder under {root}")
    converted, unclean = [], []
    for sub, folder_kind in (("", "open"), ("done", "done")):
        folder = os.path.join(base, sub)
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if not name.endswith(".json"):
                continue
            path, slug = os.path.join(folder, name), name[:-5]
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data.get("where"), str):
                continue
            original = data["where"]
            if original.strip():
                data["where"], clean = split_where(slug, original)
                if not clean:
                    unclean.append((slug, original, data["where"]))
            else:
                del data["where"]
            converted.append((path, rq.serialize(slug, data, folder_kind)))
    for path, text in converted:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    return sorted(os.path.relpath(p, root) for p, _ in converted), unclean


if __name__ == "__main__":
    done, odd = migrate(sys.argv[1])
    print(f"rewrote {len(done)} records")
    for slug, original, written in odd:
        print(f"UNCLEAN {slug}\n  was: {original}\n  now: {json.dumps(written, ensure_ascii=False)}")
