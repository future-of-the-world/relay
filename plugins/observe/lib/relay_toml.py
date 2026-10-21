"""TOML for the hooks, on any Python 3.

Python 3.11 has `tomllib`; the macOS system Python (3.9) does not. The hooks must
run under whichever `python3` the harness finds, so they read TOML through here:
`tomllib` when it exists, else a small reader for the subset relay's files use
(tables, dotted keys, strings, numbers, booleans, arrays, inline tables, comments).
Dates and times are not supported by the fallback and raise ValueError.
"""

import re

try:
    import tomllib as _tomllib
except ImportError:  # Python < 3.11
    _tomllib = None

_BARE = re.compile(r"[A-Za-z0-9_-]+")
_NUM = re.compile(r"[+-]?(inf|nan|\d[\d_]*(\.\d[\d_]*)?([eE][+-]?\d+)?|0x[0-9A-Fa-f_]+|0o[0-7_]+|0b[01_]+)")
_ESC = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}


def load(handle):
    """Like tomllib.load: `handle` is a file opened in binary mode."""
    data = handle.read()
    if _tomllib is not None:
        return _tomllib.loads(data.decode("utf-8"))
    return _loads(data.decode("utf-8"))


def loads(text):
    return _tomllib.loads(text) if _tomllib is not None else _loads(text)


class _P:
    def __init__(self, text):
        self.s, self.i = text, 0

    def fail(self, why):
        raise ValueError(f"TOML: {why} at offset {self.i}")

    def ws(self, newlines=False):
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t" or (newlines and c in "\r\n"):
                self.i += 1
            elif c == "#":
                while self.i < len(self.s) and self.s[self.i] != "\n":
                    self.i += 1
            else:
                break

    def key(self):
        parts = []
        while True:
            self.ws()
            c = self.s[self.i:self.i + 1]
            if c in ('"', "'"):
                parts.append(self.string())
            else:
                m = _BARE.match(self.s, self.i)
                if not m:
                    self.fail("bad key")
                parts.append(m.group())
                self.i = m.end()
            self.ws()
            if self.s[self.i:self.i + 1] == ".":
                self.i += 1
                continue
            return parts

    def string(self):
        q = self.s[self.i]
        triple = self.s.startswith(q * 3, self.i)
        self.i += 3 if triple else 1
        out = []
        if triple and self.s[self.i:self.i + 1] == "\n":
            self.i += 1
        while self.i < len(self.s):
            if triple and self.s.startswith(q * 3, self.i):
                self.i += 3
                return "".join(out)
            c = self.s[self.i]
            if not triple and c == q:
                self.i += 1
                return "".join(out)
            if not triple and c == "\n":
                self.fail("newline in string")
            if q == '"' and c == "\\":
                n = self.s[self.i + 1]
                if n in _ESC:
                    out.append(_ESC[n]); self.i += 2
                elif n in "uU":
                    k = 4 if n == "u" else 8
                    out.append(chr(int(self.s[self.i + 2:self.i + 2 + k], 16))); self.i += 2 + k
                elif triple and n in " \t\r\n":
                    self.i += 1
                    while self.s[self.i] in " \t\r\n":
                        self.i += 1
                else:
                    self.fail("bad escape")
                continue
            out.append(c)
            self.i += 1
        self.fail("unterminated string")

    def value(self):
        self.ws()
        c = self.s[self.i:self.i + 1]
        if c in ('"', "'"):
            return self.string()
        if c == "[":
            self.i += 1
            items = []
            while True:
                self.ws(True)
                if self.s[self.i:self.i + 1] == "]":
                    self.i += 1
                    return items
                items.append(self.value())
                self.ws(True)
                if self.s[self.i:self.i + 1] == ",":
                    self.i += 1
        if c == "{":
            self.i += 1
            table = {}
            while True:
                self.ws()
                if self.s[self.i:self.i + 1] == "}":
                    self.i += 1
                    return table
                path = self.key()
                self.ws()
                if self.s[self.i:self.i + 1] != "=":
                    self.fail("expected =")
                self.i += 1
                _put(table, path, self.value())
                self.ws()
                if self.s[self.i:self.i + 1] == ",":
                    self.i += 1
        for word, val in (("true", True), ("false", False)):
            if self.s.startswith(word, self.i):
                self.i += len(word)
                return val
        m = _NUM.match(self.s, self.i)
        if not m or re.match(r"\d{4}-\d\d-\d\d", self.s[self.i:self.i + 10]):
            self.fail("unsupported value")
        self.i = m.end()
        raw = m.group().replace("_", "")
        if re.fullmatch(r"[+-]?\d+", raw):
            return int(raw)
        if raw[:2] in ("0x", "0o", "0b"):
            return int(raw, 0)
        return float(raw)


def _put(table, path, value):
    for part in path[:-1]:
        table = table.setdefault(part, {})
        if isinstance(table, list):
            table = table[-1]
    table[path[-1]] = value


def _loads(text):
    p = _P(text)
    root = {}
    cur = root
    while True:
        p.ws(True)
        if p.i >= len(p.s):
            return root
        if p.s.startswith("[[", p.i):
            p.i += 2
            path = p.key()
            if not p.s.startswith("]]", p.i):
                p.fail("expected ]]")
            p.i += 2
            parent = root
            for part in path[:-1]:
                parent = parent.setdefault(part, {})
                if isinstance(parent, list):
                    parent = parent[-1]
            cur = {}
            parent.setdefault(path[-1], []).append(cur)
        elif p.s[p.i] == "[":
            p.i += 1
            path = p.key()
            if p.s[p.i:p.i + 1] != "]":
                p.fail("expected ]")
            p.i += 1
            cur = root
            for part in path:
                cur = cur.setdefault(part, {})
                if isinstance(cur, list):
                    cur = cur[-1]
        else:
            path = p.key()
            p.ws()
            if p.s[p.i:p.i + 1] != "=":
                p.fail("expected =")
            p.i += 1
            _put(cur, path, p.value())
        p.ws()
        if p.i < len(p.s) and p.s[p.i] not in "\r\n":
            p.fail("junk after value")
