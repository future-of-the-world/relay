"""relay license: set a project up for a license in the REUSE layout, and check it.

`add` writes LICENSE (root, for GitHub), LICENSES/<id>.txt (the same text), REUSE.toml (one annotation for "**") and
`[license] id, holder` in .claude/kit.toml; the texts live in data/licenses/<SPDX id>.txt (README there names the pinned tag).
`check` runs on every gate when kit.toml has `[license]`; without that table nothing is checked. Per-file header lines are
only for the groups named in `--headers code|config|docs` (kit.toml `headers = [...]`).
"""

import datetime as dt
import json
import os
import re
import subprocess
import tomllib

import relay_config
from relay_config import ROOT

LICENSE_DIR = os.path.join(ROOT, "data", "licenses")
YEAR, HOLDER_MARKS = "<year>", ("<copyright holders>", "<owner>")
# The ISC text in the SPDX list carries ISC's own two copyright lines as an example; a project's LICENSE names its own holder.
ISC_EXAMPLE = ('Copyright (c) 2004-2010 by Internet Systems Consortium, Inc. ("ISC")\n'
               "Copyright (c) 1995-2003 by Internet Software Consortium")
# Header groups: file extension (or exact file name) -> the comment style of its one-line header. JSON, lock files,
# binaries and generated files are in no group.
GROUPS: dict[str, dict[str, str]] = {
    "code": {**{e: "#" for e in ("py", "sh", "bash", "zsh", "fish", "rb", "pl", "ex", "exs", "r", "jl", "cr", "nim", "tcl", "ps1", "gd",
                                  "Dockerfile", "Makefile", "Rakefile", "Gemfile")},
             **{e: "//" for e in ("js", "mjs", "cjs", "jsx", "ts", "tsx", "go", "rs", "c", "h", "cc", "cpp", "cxx", "hpp", "java", "kt", "kts",
                                  "swift", "scala", "cs", "dart", "zig", "sol", "groovy", "proto")},
             **{e: "--" for e in ("sql", "lua", "hs", "elm")}},
    "config": {"yaml": "#", "yml": "#", "toml": "#", "ini": ";", "xml": "html"},
    "docs": {"md": "html", "rst": "rst"},
}
SPDX = "SPDX-License-Identifier:"
HEADER_LINES = 5
VENDORED = {"vendor", "third_party", "node_modules"}
SKIP_DIRS = VENDORED | {".git", ".worktrees", ".venv", "venv", "__pycache__", ".ci", "_build", "deps", "dist", "build", "target"}


class Refused(Exception):
    pass


def ids() -> list[str]:
    return sorted(f[:-4] for f in os.listdir(LICENSE_DIR) if f.endswith(".txt"))


def template(license_id: str) -> str:
    if license_id not in ids():
        raise ValueError(f"no bundled license '{license_id}' (bundled: {', '.join(ids())})")
    with open(os.path.join(LICENSE_DIR, license_id + ".txt"), encoding="utf-8", newline="") as handle:
        text = handle.read()
    if license_id == "ISC":
        text = text.replace(ISC_EXAMPLE, "Copyright (c) <year> <copyright holders>")
    return text


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


def comment_mark(name: str, groups: list[str] | None = None) -> str | None:
    """The comment style for a file name in the given groups (all groups when None); None when it is in none of them."""
    base = os.path.basename(name)
    for group in groups if groups is not None else GROUPS:
        table = GROUPS[group]
        key = base if base in table else os.path.splitext(base)[1][1:]
        if key in table:
            return table[key]
    return None


def header_line(license_id: str, name: str) -> str:
    mark = comment_mark(name)
    if mark == "html":
        return f"<!-- {SPDX} {license_id} -->"
    return f"{mark} {SPDX} {license_id}"


def license_path(root: str) -> str:
    return os.path.join(root, "LICENSE")


def is_vendored(name: str) -> bool:
    return any(part in VENDORED for part in name.split("/")[:-1])


def _git_names(root: str, *args: str) -> list[str]:
    out = subprocess.run(["git", "-C", root, "ls-files", *args, "-z"], capture_output=True, text=True, check=True, timeout=60).stdout
    return [n for n in out.split("\0") if n]


def code_files(root: str, groups: list[str]) -> list[str]:
    """The project's files of the given header groups (relative paths, sorted), never under vendor/, third_party/, node_modules/."""
    if os.path.exists(os.path.join(root, ".git")):
        names = _git_names(root, "-co", "--exclude-standard")
    else:
        names = []
        for here, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            names += [os.path.relpath(os.path.join(here, f), root) for f in files]
    return sorted(n for n in names if not is_vendored(n) and comment_mark(n, groups) and os.path.isfile(os.path.join(root, n)))


def vendored_dirs(root: str) -> dict[str, list[str]]:
    """The tracked vendored folders (vendor/, third_party/, node_modules/, at any depth) and their tracked files; {} outside git."""
    if not os.path.exists(os.path.join(root, ".git")):
        return {}
    found: dict[str, list[str]] = {}
    for name in _git_names(root):
        parts = name.split("/")
        for i, part in enumerate(parts[:-1]):
            if part in VENDORED:
                found.setdefault("/".join(parts[:i + 1]), []).append(name)
                break
    return found


def _read(path: str) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def spdx_ids(text: str) -> list[str]:
    """The ids of the SPDX-License-Identifier lines in the first lines of a file."""
    found = []
    for line in text.splitlines()[:HEADER_LINES]:
        if SPDX in line:
            rest = line.split(SPDX, 1)[1].strip()
            for tail in ("-->", "*/"):
                if rest.endswith(tail):
                    rest = rest[:-len(tail)].strip()
            found.append(rest)
    return found


def has_header(text: str, license_id: str) -> bool:
    return license_id in spdx_ids(text)


def insert_header(text: str, license_id: str, name: str) -> str:
    """The text with the header line after a shebang, an encoding line or an xml prolog; unchanged when the file already
    carries any SPDX-License-Identifier line (our id: done; another id: not ours to overrule)."""
    if spdx_ids(text):
        return text
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    at = 0
    if lines and (lines[0].startswith("#!") or lines[0].startswith("<?xml")):
        at = 1
    if name.endswith(".py") and at < len(lines) and re.match(r"[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+", lines[at]) and at < 2:
        at += 1
    if at and not lines[at - 1].endswith(("\n", "\r")):
        lines[at - 1] += eol
    lines.insert(at, header_line(license_id, name) + eol)
    return "".join(lines)


def license_block(license_id: str, holder: str | None, headers: list[str] | None = None) -> str:
    """The kit.toml [license] table, as text."""
    lines = ["[license]", f"id = {json.dumps(license_id)}"]
    if holder:
        lines.append(f"holder = {json.dumps(holder, ensure_ascii=False)}")
    if headers:
        lines.append(f"headers = {json.dumps(headers)}")
    return "\n".join(lines) + "\n"


def reuse_text(license_id: str, holder: str, year: str) -> str:
    return ("version = 1\n\n[[annotations]]\n" 'path = "**"\n' 'precedence = "closest"\n'
            f"SPDX-FileCopyrightText = {json.dumps(f'{year} {holder}', ensure_ascii=False)}\n"
            f"SPDX-License-Identifier = {json.dumps(license_id)}\n")


def _annotations(root: str) -> list[dict]:
    with open(os.path.join(root, "REUSE.toml"), "rb") as handle:
        data = tomllib.load(handle)
    return [a for a in data.get("annotations", []) if isinstance(a, dict)]


def _paths(annotation: dict) -> list[str]:
    path = annotation.get("path", [])
    return [path] if isinstance(path, str) else [p for p in path if isinstance(p, str)]


def reuse_covers_all(root: str, license_id: str) -> bool:
    try:
        return any("**" in _paths(a) and a.get("SPDX-License-Identifier") == license_id for a in _annotations(root))
    except (OSError, ValueError):
        return False


def match_year(license_id: str, holder: str | None, actual: str) -> str | None:
    """The year of `actual` when it equals the bundled text for some year (the year is the one thing the owner picks), else None."""
    text = template(license_id)
    mark = holder_mark(text)
    pattern = re.escape(text)
    if mark:
        pattern = pattern.replace(re.escape(mark), re.escape(holder) if holder else r"[^\n]+")
    first, *rest = pattern.split(re.escape(YEAR))
    pattern = first + (r"(?P<year>\d{4})" + r"\d{4}".join(rest) if rest else "")
    found = re.fullmatch(pattern, actual)
    if found is None:
        return None
    return found.group("year") if rest else ""


def matches(license_id: str, holder: str | None, actual: str) -> bool:
    return match_year(license_id, holder, actual) is not None


def parse_groups(value: str | list[str]) -> list[str]:
    """Group names from a list or a comma list; ValueError on an unknown one."""
    names = [n for chunk in ([value] if isinstance(value, str) else value) for n in chunk.split(",") if n]
    bad = [n for n in names if n not in GROUPS]
    if bad:
        raise ValueError(f"unknown header group '{bad[0]}' (groups: {', '.join(GROUPS)})")
    return sorted(set(names), key=list(GROUPS).index)


def add(root: str, license_id: str, holder: str | None = None, year: int | None = None, headers: list[str] | None = None) -> list[str]:
    """Write LICENSE, LICENSES/<id>.txt, REUSE.toml and kit.toml [license] (and header lines for the `headers` groups); the lines
    to tell the owner. Refuses, writing nothing, when an existing file differs from what would be written."""
    if not holder:
        raise ValueError("pass --holder <name>")
    groups = parse_groups(headers) if headers else []
    text = license_text(license_id, holder, year or dt.date.today().year)
    lic, lic_dir = license_path(root), os.path.join(root, "LICENSES")
    spdx_path, reuse_path = os.path.join(lic_dir, license_id + ".txt"), os.path.join(root, "REUSE.toml")
    kit = relay_config.bindings_path(root)
    shown_year = str(year or dt.date.today().year)
    if os.path.exists(lic):
        old = _read(lic)
        found = match_year(license_id, holder, old)
        if found is None:
            raise Refused(f"LICENSE exists and differs from {license_id}: nothing changed. To replace it, move it aside "
                          f"(`mv LICENSE LICENSE.old`) and run the command again.")
        text, shown_year = old, found or shown_year      # the first year stays
    if os.path.exists(spdx_path) and _read(spdx_path) != text:
        raise Refused(f"LICENSES/{license_id}.txt exists and differs from {license_id}: nothing changed. Move it aside and run the command again.")
    if os.path.exists(reuse_path) and not reuse_covers_all(root, license_id):
        raise Refused(f"REUSE.toml exists and has no annotation with path \"**\" and SPDX-License-Identifier \"{license_id}\": "
                      f"nothing changed. Fix it by hand or move it aside.")
    kit_text, wanted = "", {"id": license_id, "holder": holder}
    write_kit = True
    if os.path.isfile(kit):
        kit_text = _read(kit)
        have = tomllib.loads(kit_text).get("license")
        if have is not None:
            same = {k: have.get(k) for k in wanted} == wanted and (not groups or sorted(have.get("headers", [])) == sorted(groups))
            if not same:
                raise Refused("kit.toml [license] already differs from this command: nothing changed. Edit it by hand or make the command match it.")
            write_kit = False
    said = []
    if not os.path.exists(lic):
        with open(lic, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        said.append(f"wrote LICENSE ({license_id})")
    if not os.path.exists(spdx_path):
        os.makedirs(lic_dir, exist_ok=True)
        with open(spdx_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        said.append(f"wrote LICENSES/{license_id}.txt")
    if not os.path.exists(reuse_path):
        with open(reuse_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(reuse_text(license_id, holder, shown_year))
        said.append("wrote REUSE.toml")
    if write_kit:
        os.makedirs(os.path.dirname(kit), exist_ok=True)
        head = kit_text + ("" if not kit_text or kit_text.endswith("\n") else "\n") + ("\n" if kit_text else "")
        with open(kit, "w", encoding="utf-8", newline="") as handle:
            handle.write(head + license_block(license_id, holder, groups))
        said.append("kit.toml: added [license]")
    if not said:
        said.append("LICENSE, LICENSES/, REUSE.toml and kit.toml already are as asked, nothing changed")
    if groups:
        changed = 0
        for name in code_files(root, groups):
            full = os.path.join(root, name)
            try:
                old = _read(full)
            except UnicodeDecodeError:
                said.append(f"{name}: not readable as text, header not added")
                continue
            new = insert_header(old, license_id, name)
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
    headers = table.get("headers", [])
    if not isinstance(table.get("holder", ""), str) or not isinstance(headers, list) or not all(isinstance(h, str) for h in headers):
        raise ValueError("kit.toml [license]: holder is text, headers is a list of groups (code, config, docs)")
    parse_groups(headers)
    return table


def _text_problem(root: str, rel: str, license_id: str, holder: str | None, fix: str) -> str | None:
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        return f"{rel} is missing: {fix}"
    try:
        if not matches(license_id, holder, _read(path)):
            return f"{rel} differs from the bundled {license_id} text"
    except UnicodeDecodeError:
        return f"{rel} differs from the bundled {license_id} text"
    return None


def check(root: str) -> list[str]:
    """One line per problem; [] when all is well or when the project asked for no license."""
    cfg = settings(root)
    if cfg is None:
        return []
    license_id, holder = cfg["id"], cfg.get("holder")
    if license_id not in ids():
        return [f"kit.toml [license] id '{license_id}' is not a bundled license ({', '.join(ids())})"]
    fix = f"run `relay license add {license_id}" + (f" --holder \"{holder}\"" if holder else "") + "`"
    problems = [p for p in (_text_problem(root, "LICENSE", license_id, holder, fix),
                            _text_problem(root, f"LICENSES/{license_id}.txt", license_id, holder, fix)) if p]
    if not os.path.isfile(os.path.join(root, "REUSE.toml")):
        problems.append(f"REUSE.toml is missing: {fix}")
        annotations: list[dict] = []
    else:
        try:
            annotations = _annotations(root)
        except ValueError as exc:
            annotations = []
            problems.append(f"REUSE.toml cannot be read: {exc}")
        else:
            if not reuse_covers_all(root, license_id):
                problems.append(f"REUSE.toml has no annotation with path \"**\" and SPDX-License-Identifier \"{license_id}\"")
    for folder, names in sorted(vendored_dirs(root).items()):
        if any(p == folder + "/**" or p.startswith(folder + "/") for a in annotations for p in _paths(a)):
            continue
        if all(_has_any_spdx(root, n) for n in names):
            continue
        problems.append(f"{folder}/ is tracked and has no REUSE.toml annotation or headers of its own (it would be claimed as ours)")
    groups = cfg.get("headers", [])
    if groups:
        for name in code_files(root, groups):
            try:
                text = _read(os.path.join(root, name))
            except UnicodeDecodeError:
                problems.append(f"{name}: not readable as text, cannot check the header")
                continue
            if not has_header(text, license_id):
                problems.append(f"{name}: no `{header_line(license_id, name)}` in the first {HEADER_LINES} lines")
    return problems


def _has_any_spdx(root: str, name: str) -> bool:
    try:
        return bool(spdx_ids(_read(os.path.join(root, name))))
    except (OSError, UnicodeDecodeError):
        return False
