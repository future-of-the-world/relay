"""Role bases: one shared text per agent role, assembled into the agent files.

roles/<role>.md is a base, roles/parts/<name>.md a part. An agent file marks
the regions that hold them:

    <!-- relay:base judge -->
    ...exact body of roles/judge.md...
    <!-- relay:end judge -->

Assembly replaces what lies between a pair of markers with the body of the
named file (its frontmatter stripped) and touches nothing outside markers. A
base or part may hold a line `<!-- relay:include tests -->`, expanded to that
part's body (one level). `{maxTurns}` becomes the agent's own frontmatter value.

assemble(root) writes <root>/plugins/*/agents/*.md and plugins/core/lib/agent-roles.tsv (agent -> role, for the
per-role project files) only; never an installed copy, a bench candidate or another checkout.
"""

import glob
import os
import re


class RolesError(Exception):
    pass


OPEN = re.compile(r"^<!-- relay:(base|part) ([A-Za-z0-9_-]+) -->$")
END = re.compile(r"^<!-- relay:end ([A-Za-z0-9_-]+) -->$")
INCLUDE = re.compile(r"^<!-- relay:include ([A-Za-z0-9_-]+) -->$")
PLACEHOLDER = re.compile(r"\{[A-Za-z0-9_]+\}")


def agent_files(root):
    return sorted(glob.glob(os.path.join(root, "plugins", "*", "agents", "*.md")))


def split_frontmatter(text):
    """(dict of key: value lines, body). No frontmatter: ({}, text)."""
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).split("\n"):
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return meta, text[m.end():]


def _source(root, kind, name):
    sub = os.path.join("roles", "parts", name + ".md") if kind == "part" else os.path.join("roles", name + ".md")
    path = os.path.join(root, sub)
    if not os.path.isfile(path):
        raise RolesError(f"{sub} missing (run from the checkout that has roles/)")
    return path


def read_source(root, kind, name):
    """(meta, body) of a base or a part; the body has no frontmatter and no outer blank lines."""
    with open(_source(root, kind, name), encoding="utf-8") as handle:
        meta, body = split_frontmatter(handle.read())
    return meta, body.strip("\n")


def expanded_body(root, kind, name):
    """The body with its include lines replaced by the parts' bodies (one level)."""
    _, body = read_source(root, kind, name)
    out = []
    for line in body.split("\n"):
        m = INCLUDE.match(line)
        if not m:
            out.append(line)
            continue
        if kind == "part":
            raise RolesError(f"roles/parts/{name}.md: an include inside a part (includes are one level)")
        _, inner = read_source(root, "part", m.group(1))
        if any(INCLUDE.match(x) for x in inner.split("\n")):
            raise RolesError(f"roles/parts/{m.group(1)}.md: an include inside a part (includes are one level)")
        out.append(inner)
    return "\n".join(out)


def parse_regions(text, label="text"):
    """Split an agent file into a list of items: a list of lines (outside text) or a dict
    {kind, name, content, open, close}. Raises RolesError on unbalanced or nested markers."""
    items, outside, current = [], [], None
    for number, line in enumerate(text.split("\n"), 1):
        opened, closed = OPEN.match(line), END.match(line)
        if current is None:
            if closed:
                raise RolesError(f"{label}:{number}: end marker '{closed.group(1)}' with no open marker")
            if opened:
                items.append(outside)
                outside = []
                current = {"kind": opened.group(1), "name": opened.group(2), "lines": [], "open": line, "line": number}
            else:
                outside.append(line)
        else:
            if opened:
                raise RolesError(f"{label}:{number}: region '{opened.group(2)}' opens inside region '{current['name']}' (no nesting)")
            if closed:
                if closed.group(1) != current["name"]:
                    raise RolesError(f"{label}:{number}: end marker '{closed.group(1)}' closes region '{current['name']}'")
                current["close"] = line
                lines = current.pop("lines")
                current["content"] = "\n" + "\n".join(lines) + ("\n" if lines else "")
                items.append(current)
                current = None
            else:
                current["lines"].append(line)
    if current is not None:
        raise RolesError(f"{label}:{current['line']}: region '{current['name']}' is never closed")
    items.append(outside)
    return items


def _regions(items):
    return [i for i in items if isinstance(i, dict)]


def expected_content(root, region, max_turns):
    body = expanded_body(root, region["kind"], region["name"])
    if "{maxTurns}" in body:
        if max_turns is None:
            raise RolesError(f"{region['kind']} '{region['name']}' uses {{maxTurns}} but the agent has no maxTurns")
        body = body.replace("{maxTurns}", str(max_turns))
    return "\n" + body + "\n"


def _render(region, content):
    return region["open"] + content + region["close"]


def assemble_text(text, root, max_turns=None, label="text"):
    """The text with every marked region replaced by its source. Pure: no file is touched."""
    if max_turns is None:
        max_turns = split_frontmatter(text)[0].get("maxTurns")
    out = []
    for item in parse_regions(text, label):
        if isinstance(item, list):
            out += item
        else:
            out += _render(item, expected_content(root, item, max_turns)).split("\n")
    return "\n".join(out)


def has_markers(text):
    return any(OPEN.match(line) or END.match(line) for line in text.split("\n"))


MAP_FILE = os.path.join("plugins", "core", "lib", "agent-roles.tsv")


def role_map(root):
    """The text of agent-roles.tsv: one line `<plugin>:<name><TAB><role>` per agent with a relay:base region, sorted.
    The core plugin's addition hook reads it to give an agent its role's project file (.claude/kit/<role>.md)."""
    lines = []
    for path in agent_files(root):
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        if not has_markers(text):
            continue
        plugin = os.path.basename(os.path.dirname(os.path.dirname(path)))
        name = split_frontmatter(text)[0].get("name") or os.path.basename(path)[:-3]
        for region in _regions(parse_regions(text, os.path.relpath(path, root))):
            if region["kind"] == "base":
                lines.append(f"{plugin}:{name}\t{region['name']}")
    return "".join(line + "\n" for line in sorted(lines))


def write_role_map(root, dry=False):
    """Write the role map when the checkout has a core plugin; True when it changed (or would)."""
    folder = os.path.dirname(os.path.join(root, MAP_FILE))
    if not os.path.isdir(folder):
        return False
    path = os.path.join(root, MAP_FILE)
    current = open(path, encoding="utf-8").read() if os.path.isfile(path) else None
    text = role_map(root)
    if current == text:
        return False
    if not dry:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    return True


def assemble(root, dry=False):
    """Assemble every agent file under root/plugins/*/agents; return the paths that changed (or would).
    Also writes plugins/core/lib/agent-roles.tsv (not counted in the paths)."""
    changed = []
    for path in agent_files(root):
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        if not has_markers(text):
            continue
        new = assemble_text(text, root, label=os.path.relpath(path, root))
        if new != text:
            changed.append(path)
            if not dry:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(new)
    write_role_map(root, dry=dry)
    return changed


def check(root):
    """[(path, region name)] of regions whose text differs from their source."""
    out = []
    for path in agent_files(root):
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        if not has_markers(text):
            continue
        label = os.path.relpath(path, root)
        max_turns = split_frontmatter(text)[0].get("maxTurns")
        for region in _regions(parse_regions(text, label)):
            if region["content"] != expected_content(root, region, max_turns):
                out.append((path, region["name"]))
    return out


def describe(path, region, root):
    rel = os.path.relpath(path, root)
    return (f"{rel}: text in relay:base {region} differs from roles/{region}.md: "
            f"edit roles/{region}.md, then run bin/relay sync agents from this checkout")


def _tools(meta):
    return [t.strip() for t in meta.get("tools", "").split(",") if t.strip()]


def problems(root, require_base=False):
    """Structure and wording problems of the bases, parts and marked agent files, as strings.
    require_base: an agent file with no relay:base region is a problem too."""
    out = []
    folder = os.path.join(root, "roles")
    names = []
    if os.path.isdir(folder):
        names = [("base", f[:-3]) for f in sorted(os.listdir(folder)) if f.endswith(".md")]
        parts = os.path.join(folder, "parts")
        if os.path.isdir(parts):
            names += [("part", f[:-3]) for f in sorted(os.listdir(parts)) if f.endswith(".md")]
    for kind, name in names:
        try:
            body = expanded_body(root, kind, name)
        except RolesError as error:
            out.append(str(error))
            continue
        for found in sorted(set(PLACEHOLDER.findall(body)) - {"{maxTurns}"}):
            out.append(f"roles/{name}.md: placeholder {found} (only {{maxTurns}} exists)")
    map_path = os.path.join(root, MAP_FILE)
    if os.path.isdir(os.path.dirname(map_path)):
        have = open(map_path, encoding="utf-8").read() if os.path.isfile(map_path) else None
        try:
            if have != role_map(root):
                out.append(f"{MAP_FILE} differs from the agents' relay:base markers: run bin/relay sync agents from this checkout")
        except RolesError:
            pass   # the broken region is reported below
    for path in agent_files(root):
        label = os.path.relpath(path, root)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        meta, _ = split_frontmatter(text)
        if not has_markers(text):
            if require_base:
                out.append(f"{label}: no relay:base region")
            continue
        try:
            regions = _regions(parse_regions(text, label))
        except RolesError as error:
            out.append(str(error))
            continue
        bases = [r for r in regions if r["kind"] == "base"]
        if len(bases) != 1:
            out.append(f"{label}: {len(bases)} relay:base regions (exactly one)")
        for region in regions:
            try:
                expected_content(root, region, meta.get("maxTurns"))
            except RolesError as error:
                out.append(f"{label}: {error}")
        if "{maxTurns}" in text:
            out.append(f"{label}: holds {{maxTurns}} after assembly")
        for base in bases:
            try:
                base_meta, _ = read_source(root, "base", base["name"])
            except RolesError:
                continue
            have = _tools(meta)
            for tool in [t.strip() for t in base_meta.get("needs-tools", "").split(",") if t.strip()]:
                if tool not in have:
                    out.append(f"{label}: tools lack {tool}, which base {base['name']} needs")
            for tool in [t.strip() for t in base_meta.get("never-tools", "").split(",") if t.strip()]:
                if tool in have:
                    out.append(f"{label}: tools hold {tool}, which base {base['name']} forbids")
    return out
