"""relay license: add a project's LICENSE from a bundled exact SPDX text, and check it (and, when asked, the file headers).

The texts live in data/licenses/<SPDX id>.txt (README there names the pinned tag). The project asks for the check in
.claude/kit.toml: `[license] id, holder` and, for headers, `headers = true`. Without that table nothing is checked.
"""

import datetime as dt
import os
import re
import subprocess

import relay_config
from relay_config import ROOT

LICENSE_DIR = os.path.join(ROOT, "data", "licenses")
YEAR, HOLDER_MARKS = "<year>", ("<copyright holders>", "<owner>")
# Code files by extension; the comment mark each one's one-line header starts with. JSON, md, txt, logs and data never.
COMMENT = {**{e: "#" for e in ("py", "sh", "bash", "zsh", "toml", "yaml", "yml", "ex", "exs")},
           **{e: "//" for e in ("js", "mjs", "ts", "go", "rs", "c", "h", "swift", "kt")}}
SPDX = "SPDX-License-Identifier:"
HEADER_LINES = 5
SKIP_DIRS = {".git", ".worktrees", "node_modules", ".venv", "venv", "__pycache__", ".ci", "_build", "deps", "dist", "build", "target", "vendor"}


class Refused(Exception):
    pass


def ids() -> list[str]:
    return sorted(f[:-4] for f in os.listdir(LICENSE_DIR) if f.endswith(".txt"))


def template(license_id: str) -> str:
    if license_id not in ids():
        raise ValueError(f"no bundled license '{license_id}' (bundled: {', '.join(ids())})")
    with open(os.path.join(LICENSE_DIR, license_id + ".txt"), encoding="utf-8", newline="") as handle:
        return handle.read()


def holder_mark(text: str) -> str | None:
    return next((m for m in HOLDER_MARKS if m in text), None)


def needs_holder(license_id: str) -> bool:
    return holder_mark(template(license_id)) is not None


def license_text(license_id: str, holder: str | None, year: int) -> str:
    """The LICENSE text: the bundled one with the year and the holder filled in where it has them."""
    text = template(license_id)
    mark = holder_mark(text)
    if mark:
        if not holder:
            raise ValueError(f"{license_id} has a holder line: pass --holder <name>")
        if "\n" in holder:
            raise ValueError("the holder is one line")
        text = text.replace(mark, holder)
    return text.replace(YEAR, str(year))


def header_line(license_id: str, ext: str) -> str:
    return f"{COMMENT[ext]} {SPDX} {license_id}"


def license_path(root: str) -> str:
    return os.path.join(root, "LICENSE")


def code_files(root: str) -> list[str]:
    """The project's code files (relative paths, sorted): the ones git lists when it is a git folder, else a walk."""
    if os.path.exists(os.path.join(root, ".git")):
        out = subprocess.run(["git", "-C", root, "ls-files", "-co", "--exclude-standard", "-z"], capture_output=True, text=True, check=True, timeout=60).stdout
        names = [n for n in out.split("\0") if n]
    else:
        names = []
        for here, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            names += [os.path.relpath(os.path.join(here, f), root) for f in files]
    return sorted(n for n in names if os.path.splitext(n)[1][1:] in COMMENT and os.path.isfile(os.path.join(root, n)))


def _read(path: str) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def has_header(text: str, license_id: str) -> bool:
    return any(line.strip().endswith(f"{SPDX} {license_id}") for line in text.splitlines()[:HEADER_LINES])


def insert_header(text: str, license_id: str, ext: str) -> str:
    """The text with the header line after a shebang and an encoding line; unchanged when it is already there."""
    if has_header(text, license_id):
        return text
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    at = 0
    if lines and lines[0].startswith("#!"):
        at = 1
    if ext == "py" and at < len(lines) and re.match(r"[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+", lines[at]) and at < 2:
        at += 1
    if at and not lines[at - 1].endswith(("\n", "\r")):
        lines[at - 1] += eol
    lines.insert(at, header_line(license_id, ext) + eol)
    return "".join(lines)


def add(root: str, license_id: str, holder: str | None = None, year: int | None = None, headers: bool = False) -> list[str]:
    """Write LICENSE (and the header lines with `headers`); the lines to tell the owner. Refuses when LICENSE exists and differs."""
    text = license_text(license_id, holder, year or dt.date.today().year)
    path = license_path(root)
    said = []
    if os.path.exists(path) and _read(path) != text:
        raise Refused(f"LICENSE exists and differs from {license_id}: nothing changed. To replace it, move it aside "
                      f"(`mv LICENSE LICENSE.old`) and run the command again.")
    if os.path.exists(path):
        said.append("LICENSE already is that text, nothing changed")
    else:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        said.append(f"wrote LICENSE ({license_id})")
    if holder and not needs_holder(license_id):
        said.append(f"this text has no holder line; the header you may add to your files: "
                    f"SPDX-FileCopyrightText: {year or dt.date.today().year} {holder}")
    if headers:
        changed = 0
        for name in code_files(root):
            full = os.path.join(root, name)
            old = _read(full)
            new = insert_header(old, license_id, os.path.splitext(name)[1][1:])
            if new != old:
                with open(full, "w", encoding="utf-8", newline="") as handle:
                    handle.write(new)
                changed += 1
        said.append(f"header line added to {changed} file(s)")
    return said


def settings(root: str) -> dict | None:
    """kit.toml [license] as a dict, None when the project did not ask for a license."""
    path = relay_config.bindings_path(root)
    if not os.path.isfile(path):
        return None
    table = relay_config.read_toml(path).get("license")
    if table is None:
        return None
    if not isinstance(table, dict) or not isinstance(table.get("id"), str):
        raise ValueError("kit.toml [license] needs id = \"<SPDX id>\"")
    if not isinstance(table.get("holder", ""), str) or not isinstance(table.get("headers", False), bool):
        raise ValueError("kit.toml [license]: holder is text, headers is true or false")
    return table


def matches(license_id: str, holder: str | None, actual: str) -> bool:
    """LICENSE equals the bundled text for any year (the year is the one thing the owner picks)."""
    text = template(license_id)
    mark = holder_mark(text)
    pattern = re.escape(text)
    if mark:
        pattern = pattern.replace(re.escape(mark), re.escape(holder) if holder else r"[^\n]+")
    pattern = pattern.replace(re.escape(YEAR), r"\d{4}")
    return re.fullmatch(pattern, actual) is not None


def check(root: str) -> list[str]:
    """One line per problem; [] when all is well or when the project asked for no license."""
    cfg = settings(root)
    if cfg is None:
        return []
    license_id, holder = cfg["id"], cfg.get("holder")
    if license_id not in ids():
        return [f"kit.toml [license] id '{license_id}' is not a bundled license ({', '.join(ids())})"]
    problems = []
    path = license_path(root)
    if not os.path.isfile(path):
        problems.append(f"LICENSE is missing: run `relay license add {license_id}" + (f" --holder \"{holder}\"" if holder else "") + "`")
    elif not matches(license_id, holder, _read(path)):
        problems.append(f"LICENSE differs from the bundled {license_id} text")
    if cfg.get("headers", False):
        for name in code_files(root):
            ext = os.path.splitext(name)[1][1:]
            try:
                text = _read(os.path.join(root, name))
            except UnicodeDecodeError:
                problems.append(f"{name}: not readable as text, cannot check the header")
                continue
            if not has_header(text, license_id):
                problems.append(f"{name}: no `{header_line(license_id, ext)}` in the first {HEADER_LINES} lines")
    return problems
