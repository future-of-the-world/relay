"""Build a worker's brief for one task of an OpenSpec change, or check them all.

    kit packet <change> <task>      print the brief of task <task> (e.g. 4.3)
    kit packet <change> <group>     print one brief for a group's open tasks (e.g. 4),
                                    to run in order in one context
    kit packet --check <change>     check every open task's fields and refs

The brief is everything a worker reads before writing code: the notes at the
top of tasks.md, its group's heading and notes, the task itself, the
scenarios it must test, and only the parts of the artifacts, code, and docs
its `Reads:` line names. It replaces reading tasks.md, design.md, and every
spec delta whole.

Every open task (`- [ ]`) ends with these fields, in this order:

    Reads: <ref>; <ref>; ...
    Tests: <capability> "<Scenario>", "<Scenario>"; ...   or   Tests: none (<reason>)
    Files: <path>, <path>, ...
    Check: `<focused command>`

A task may add `Size: mechanical (<reason>)` before `Files:` to list more than
`max_source_files` source files (a mechanical conversion across many files).
Which files are source files is the project's binding (`source`,
`source_exclude`); with none, size is not checked.

`Reads:` refs, separated by semicolons:

    design D5                     design.md section "### D5. ..."
    design "<heading>"            a design.md section by heading (any level)
    proposal "<heading>"          a proposal.md section by heading
    <capability>                  the whole spec delta specs/<capability>/spec.md
    <capability> "<Requirement>"  one requirement of that delta, with its scenarios
    <capability> "<Requirement>" body
                                  the requirement's heading and text up to its
                                  first `#### Scenario:` line, without scenarios
                                  (the scenarios a task tests are in its brief
                                  under `Tests:`)
    module <ref>                  a module's contract: its docs, types, and
                                  signatures, without bodies or private code.
                                  The ref depends on the project's `module`
                                  binding:
                                    typescript  module <path.ts|path.tsx> (the
                                                compiler's declarations; runs
                                                the project's `tsc` once)
                                    rust        module <path.rs> or
                                                module <crate::a::b>
                                    elixir      module <App.Module.Name>
                                  The module must exist when the plan is
                                  checked: a wave-0 stub or existing code
    file <path>                   a file under the repo, whole
    file <path> "<heading>"       one section of a Markdown file
    file <path>:<from>-<to>       lines <from> to <to> of a file, counted from
                                  1, both included. For a file with no
                                  headings to cut by that is a frozen record,
                                  so its line numbers do not move; a file that
                                  is still edited is named whole or by
                                  heading. The range must exist in the file

`Tests:` names scenarios of the change's spec deltas. A scenario title that
several requirements of one capability share is written
"<Requirement> / <Scenario>", unless only one of those requirements is in
`Reads:`.

`Tests:` also names the kinds of test the project requires for some files
(binding `required_test`), for example:

    Tests: widgets "Fast spin"; e2e "the panel shows its title"
    Tests: none (copy only); e2e none (covered by "the panel shows its title")

A task whose `Files:` match a kind's `files` must name that kind of test (or,
for a kind with `waiver`, `<kind> none (<reason>)`).

--check exits 1 and lists every problem: a missing field, a ref or scenario
that doesn't resolve, a required test missing, more than `max_source_files`
source files without `Size: mechanical`, an artifact over its budget
(design.md ~60 KB, tasks.md ~40 KB, a task's prose ~1 KB, group notes
~2 KB), or, when the tasks run in waves, a design.md without an `Interfaces`
section (the shape and owner of every value that crosses a task boundary:
types, function signatures, stored-data fields, event and prop shapes).
When some group has a `Wave N` line, every group with open tasks needs one and
one of them must be `Wave 1`.
"""
import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

TASK = re.compile(r"^- \[( |x)\] (\d+\.\d+) ")
GROUP = re.compile(r"^## (\d+)\. (.+)$")
FIELD_NAMES = ("Reads", "Tests", "Size", "Files", "Check")
QUOTED = re.compile(r'"([^"]+)"')
LINE_RANGE = re.compile(r"^(.+):(\d+)-(\d+)$")
NONE = re.compile(r"^none \((.+)\)$", re.S)
DEFAULT_MAX_SOURCE_FILES = 4
# Artifact budgets: a wave-plan author reads design.md and tasks.md whole, and
# every section a task names lands in its brief.
DESIGN_BUDGET = 60 * 1024
TASKS_BUDGET = 40 * 1024
TASK_BUDGET = 1024
GROUP_BUDGET = 2 * 1024

CFG: dict[str, Any] = {}  # the [packet] table of .claude/kit.toml


class RefError(Exception):
    pass


# ---------------------------------------------------------------- bindings


def patterns(key):
    return [re.compile(p) for p in CFG.get(key, [])]


def required_tests():
    return CFG.get("required_test", [])


def max_source_files():
    return int(CFG.get("max_source_files", DEFAULT_MAX_SOURCE_FILES))


# ---------------------------------------------------------------- tasks.md

FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


def mask_fences(text):
    """`text` with the first character of every line inside a fenced code block (and of its fence
    lines) replaced by a space, so a line-start pattern such as `^#` never matches there. Offsets
    and line breaks are kept. An unclosed fence runs to the end of the text."""
    out, fence = [], None
    for line in text.split("\n"):
        m = FENCE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
                out.append(" " + line[1:])
            else:
                out.append(line)
        else:
            out.append(" " + line[1:])
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
                fence = None
    return "\n".join(out)


def parse_tasks(path):
    """(global notes, {group number: (heading, notes)}, [task]) from tasks.md."""
    text = open(path, encoding="utf-8").read()
    lines = text.split("\n")
    notes, groups, tasks = [], {}, []
    group, current = None, None
    for line, masked in zip(lines, mask_fences(text).split("\n")):
        g = GROUP.match(masked)
        t = TASK.match(masked)
        if g:
            group = g.group(1)
            groups[group] = [line, []]
            current = None
        elif t:
            current = {"id": t.group(2), "done": t.group(1) == "x", "group": group, "lines": [line]}
            tasks.append(current)
        elif current is not None and (line.startswith("  ") or line == ""):
            current["lines"].append(line)
        elif current is not None:
            current = None
            if group:
                groups[group][1].append(line)
        elif group:
            groups[group][1].append(line)
        elif not line.startswith("# "):
            notes.append(line)
    for task in tasks:
        task["text"] = "\n".join(task["lines"]).rstrip()
        task["fields"] = fields(task["text"])
    return "\n".join(notes).strip(), groups, tasks


def fields(text):
    """The task's trailing fields, by name."""
    flat = " ".join(text.split())
    marks = [(m.start(), m.group(1)) for m in re.finditer(r"\b(%s): " % "|".join(FIELD_NAMES), flat)]
    out = {}
    for i, (start, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(flat)
        out[name] = flat[start + len(name) + 2 : end].strip().rstrip(".")
    return out


def split_refs(value, parens=False):
    """Split on semicolons outside quotes (and, with `parens`, outside parentheses)."""
    parts, buf, quoted, depth = [], "", False, 0
    for ch in value:
        if ch == '"':
            quoted = not quoted
        elif parens and not quoted and ch == "(":
            depth += 1
        elif parens and not quoted and ch == ")":
            depth = max(0, depth - 1)
        if ch == ";" and not quoted and depth == 0:
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return parts


def split_tests(value):
    """The parts of a Tests value. A reason in parentheses may hold a semicolon."""
    return split_refs(value, parens=True)


def file_list(value):
    return [p.strip().strip("`") for p in re.split(r",\s*", value) if p.strip()]


# ---------------------------------------------------------------- Markdown


def heading_section(text, title, where):
    """The section under the heading whose text is (or starts with) `title`."""
    lines = text.split("\n")
    masked = mask_fences(text).split("\n")
    for i, line in enumerate(masked):
        m = re.match(r"^(#{1,6}) (.+)$", line)
        if not m:
            continue
        heading = m.group(2).strip()
        if heading == title or heading.startswith(title + ".") or heading.startswith(title + " ") \
                or heading.startswith(title + ":"):
            level = len(m.group(1))
            end = len(lines)
            for j in range(i + 1, len(lines)):
                n = re.match(r"^(#{1,6}) ", masked[j])
                if n and len(n.group(1)) <= level:
                    end = j
                    break
            return "\n".join(lines[i:end]).strip()
    raise RefError(f'no heading "{title}" in {where}')


def requirements(spec_text):
    """{requirement name: block} of a spec delta."""
    found = {}
    for m in re.finditer(r"(?ms)^### Requirement: (.+?)\n(.*?)(?=^### Requirement: |^## |\Z)", mask_fences(spec_text)):
        found[m.group(1).strip()] = spec_text[m.start() : m.end()].strip()
    return found


def requirement_body(block):
    """The block up to its first `#### Scenario:` line (a line inside a fence does not count)."""
    m = re.search(r"(?m)^#### Scenario: ", mask_fences(block))
    return block[: m.start()].strip() if m else block


def scenarios(block):
    return [s.strip() for s in re.findall(r"(?m)^#### Scenario: (.+)$", mask_fences(block))]


def scenario_text(block, name):
    """The WHEN/THEN lines under one scenario heading."""
    m = re.search(r"(?ms)^#### Scenario: " + re.escape(name) + r"[ \t]*\n(.*?)(?=^#{1,4} |\Z)", mask_fences(block))
    return block[m.start(1) : m.end(1)].strip() if m else ""


def scenario_lines(change_dir, cap, req, scen):
    """Brief lines for one scenario: its entry, then its text indented under it."""
    spec = os.path.join(change_dir, "specs", cap, "spec.md")
    block = requirements(open(spec, encoding="utf-8").read())[req]
    lines = [f'- {cap}: "{req}" / "{scen}"']
    lines += ["  " + ln if ln.strip() else "" for ln in scenario_text(block, scen).splitlines()]
    return lines


# ---------------------------------------------------------------- modules: typescript

_declarations: dict[str, Any] = {}


def declarations(root):
    """A directory holding the declaration output (.d.ts) of the whole project.

    The compiler runs once per process. Its exit status is ignored: it emits
    declarations even with type errors, and a wave-0 stub may not type-check yet.
    """
    if root in _declarations:
        return _declarations[root]
    tsc = os.path.join(root, "node_modules", ".bin", "tsc")
    if not os.path.exists(tsc):
        hint = CFG.get("install_hint", "install the project's dependencies")
        raise RefError(f"module refs need node_modules/.bin/tsc: {hint}")
    out = tempfile.mkdtemp(prefix="packet-dts-")
    atexit.register(shutil.rmtree, out, ignore_errors=True)
    subprocess.run(
        [tsc, "-p", os.path.join(root, "tsconfig.json"), "--noEmit", "false", "--declaration",
         "--emitDeclarationOnly", "--rootDir", root, "--outDir", out],
        cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    _declarations[root] = out
    return out


def public_only(text):
    """A declaration file without its private members and their docs."""
    out = []
    for line in text.split("\n"):
        if re.match(r"^\s*(private\b|#private;)", line):
            # Drop the JSDoc block that documents the private member, if any.
            if out and out[-1].strip().endswith("*/"):
                while out and not out[-1].strip().startswith("/**"):
                    out.pop()
                if out:
                    out.pop()
            continue
        out.append(line)
    text = "\n".join(out).rstrip()
    return re.sub(r"\n?export \{\};\s*$", "", text).rstrip()


def ts_contract(root, module):
    """(title, text) of a TypeScript module's contract: its declaration output."""
    if not re.search(r"\.tsx?$", module) or module.endswith(".d.ts"):
        raise RefError(
            f"module {module}: a module ref names a .ts or .tsx file; use `file {module}` for other files"
        )
    if not os.path.exists(os.path.join(root, module)):
        raise RefError(
            f"no file for module {module}; a module ref names a file that exists when the plan "
            "is checked (a wave-0 stub or existing code)"
        )
    emitted = os.path.join(declarations(root), re.sub(r"\.tsx?$", ".d.ts", os.path.normpath(module)))
    if not os.path.exists(emitted):
        raise RefError(
            f"no declaration emitted for module {module} (is it covered by tsconfig.json's `include`?); "
            f"use `file {module}` to read it whole"
        )
    return f"module {module}", "```ts\n" + public_only(open(emitted, encoding="utf-8").read()) + "\n```"


# ---------------------------------------------------------------- modules: rust


def rust_path(root, module):
    """Path of a Rust module ref: a .rs path, or a crate path (crate::a::b, my_core::a::b)."""
    if module.endswith(".rs"):
        path = os.path.join(root, module)
        if os.path.exists(path):
            return path
        raise RefError(f"no file for module {module}")
    parts = module.split("::")
    head, rest = parts[0], parts[1:]
    bases = []
    if head == "crate":
        bases.append(os.path.join(root, "src"))
    else:
        for crate in (head, head.replace("_", "-")):
            bases.append(os.path.join(root, "crates", crate, "src"))
        bases.append(os.path.join(root, "src"))
    for base in bases:
        if not rest:
            for name in ("lib.rs", "main.rs"):
                path = os.path.join(base, name)
                if os.path.exists(path):
                    return path
            continue
        for path in (os.path.join(base, *rest[:-1], rest[-1] + ".rs"), os.path.join(base, *rest, "mod.rs")):
            if os.path.exists(path):
                return path
    raise RefError(
        f"no file for module {module} (looked under src/ and crates/*/src/); a module ref names "
        "a module that exists when the plan is checked (a wave-0 stub or existing code)"
    )


RS_DOC = re.compile(r"^\s*(//!|///)")
RS_ATTR = re.compile(r"^\s*#!?\[")
RS_PUB_ITEM = re.compile(
    r"^\s*pub(\([^)]*\))?\s+(unsafe\s+|async\s+|const\s+|extern\s+\"[^\"]*\"\s+)*"
    r"(fn|struct|enum|trait|type|const|static|mod|use|union)\b"
)
RS_TRAIT_OR_IMPL = re.compile(r"^\s*(pub(\([^)]*\))?\s+)?(unsafe\s+)?(trait|impl)\b")
RS_FN_SIG = re.compile(r"^\s*(pub(\([^)]*\))?\s+)?(unsafe\s+|async\s+|const\s+)*fn\b")


def rs_signature(lines, i):
    """The item signature starting at line i, up to its `{` or `;` (body dropped)."""
    sig = []
    while i < len(lines):
        line = lines[i]
        i += 1
        cut = None
        for ch_i, ch in enumerate(line):
            if ch in "{;":
                cut = ch_i
                break
        if cut is not None:
            head = line[:cut].rstrip()
            sig.append(head + (";" if line[cut] == ";" else " { … }") if head.strip() else line[: cut + 1])
            return sig, i
        sig.append(line)
    return sig, i


def rs_skip_block(lines, i):
    """Skip a `{ … }` block whose opening brace is on line i-1 or later; return the next line."""
    depth = 0
    started = False
    while i < len(lines):
        for ch in lines[i]:
            if ch == "{":
                depth += 1
                started = True
            elif ch == "}":
                depth -= 1
        i += 1
        if started and depth <= 0:
            return i
    return i


def rust_contract(path):
    """The module's public contract: docs, attributes, and public signatures, no bodies."""
    lines = open(path, encoding="utf-8").read().split("\n")
    out, i, pending = [], 0, []
    while i < len(lines):
        line = lines[i]
        if re.match(r"^\s*(//!|#!\[)", line):
            out.append(line)
            i += 1
            continue
        if RS_DOC.match(line) or RS_ATTR.match(line):
            pending.append(line)
            i += 1
            continue
        if RS_PUB_ITEM.match(line) and re.search(r"\b(struct|enum|union)\b", line) and "{" in line:
            start = i
            i = rs_skip_block(lines, i)
            out += pending + lines[start:i]
            pending = []
            continue
        if RS_TRAIT_OR_IMPL.match(line) and ("{" in line or i + 1 < len(lines)):
            header, i = rs_signature(lines, i)
            is_trait = bool(re.search(r"\btrait\b", header[0]))
            body_start = i
            end = rs_skip_block(lines, i - 1)
            members, docs = [], []
            j = body_start
            while j < end - 1:
                inner = lines[j]
                if RS_DOC.match(inner) or RS_ATTR.match(inner):
                    docs.append(inner)
                    j += 1
                    continue
                if RS_FN_SIG.match(inner) and (is_trait or inner.strip().startswith("pub")):
                    sig, k = rs_signature(lines, j)
                    members += docs + sig
                    j = rs_skip_block(lines, k - 1) if sig[-1].endswith("{ … }") else k
                    docs = []
                    continue
                docs = []
                j += 1
            if members or is_trait:
                out += pending + [header[0].replace(" { … }", " {")] + header[1:-1] + members + ["}"]
            pending = []
            i = end
            continue
        if RS_PUB_ITEM.match(line):
            sig, i = rs_signature(lines, i)
            out += pending + sig
            if sig[-1].endswith("{ … }"):
                i = rs_skip_block(lines, i - 1)
            pending = []
            continue
        pending = []
        i += 1
    return "\n".join(out)


def rs_contract(root, module):
    path = rust_path(root, module)
    return f"module {module} ({os.path.relpath(path, root)})", rust_contract(path)


# ---------------------------------------------------------------- modules: elixir


def elixir_path(root, module):
    """Path of an Elixir module (App.Exchange.Matching -> lib/app/exchange/matching.ex)."""
    parts = [re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", p).lower() for p in module.split(".")]
    bases = CFG.get("module_dirs", ["lib", "test/support"])
    for base in bases:
        path = os.path.join(root, base, *parts[:-1], parts[-1] + ".ex")
        if os.path.exists(path):
            return path
    # A directory such as test/support names its files freely, so fall back to the defmodule line.
    line = re.compile(r"^defmodule %s do$" % re.escape(module), re.M)
    for base in bases:
        for dirpath, _dirs, files in os.walk(os.path.join(root, base)):
            for name in files:
                path = os.path.join(dirpath, name)
                if name.endswith(".ex") and line.search(open(path, encoding="utf-8").read()):
                    return path
    raise RefError(
        f"no file for module {module} (looked under {', '.join(b + '/' for b in bases)}); a module ref names "
        "a module that exists when the plan is checked (a wave-0 stub or existing code)"
    )


EX_CONTRACT = re.compile(
    r"^\s*(defmodule |@moduledoc|@doc |@doc$|@typedoc|@type |@typep |@opaque |@spec |@callback |"
    r"@macrocallback |@optional_callbacks|@behaviour |@enforce_keys|defstruct|def |defmacro |use )"
)


def elixir_contract(path):
    """The module's public contract, without function bodies or private code."""
    lines = open(path, encoding="utf-8").read().split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not EX_CONTRACT.match(line):
            i += 1
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if stripped.startswith(("def ", "defmacro ")):
            out.append(re.sub(r",?\s+do:?.*$|\s+do$", "", line))
            i += 1
            continue
        out.append(line)
        i += 1
        if stripped.startswith("defmodule "):
            continue
        if line.count('"""') == 1:
            while i < len(lines):
                out.append(lines[i])
                i += 1
                if '"""' in lines[i - 1]:
                    break
            continue
        # A multi-line attribute or struct: its continuation lines are indented deeper.
        while i < len(lines) and lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) > indent:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def ex_contract(root, module):
    path = elixir_path(root, module)
    return f"module {module} ({os.path.relpath(path, root)})", elixir_contract(path)


MODULE_KINDS = {"typescript": ts_contract, "rust": rs_contract, "elixir": ex_contract}


def module_ref(root, module):
    kind = CFG.get("module")
    if kind not in MODULE_KINDS:
        raise RefError(
            f"module {module}: module refs are not set up; set `module` ({' | '.join(MODULE_KINDS)}) "
            "under [packet] in .claude/kit.toml, or use `file <path>`"
        )
    return MODULE_KINDS[kind](root, module)


# ---------------------------------------------------------------- lines


def line_range(root, ref_path, first, last):
    """Lines `first` to `last` of a file under the repo, counted from 1, both included."""
    path = os.path.join(root, ref_path)
    if not os.path.exists(path):
        raise RefError(f"no file {ref_path}")
    lines = open(path, encoding="utf-8").read().split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if first < 1 or last < first:
        raise RefError(f"bad line range {ref_path}:{first}-{last}: use <from>-<to>, from 1, <from> not above <to>")
    if last > len(lines):
        raise RefError(f"no lines {first}-{last} in {ref_path}: it has {len(lines)} lines")
    return "\n".join(lines[first - 1 : last])


# ---------------------------------------------------------------- refs


def resolve(root, change_dir, ref):
    """(title, text) of one Reads ref."""
    quoted = QUOTED.findall(ref)
    head = QUOTED.sub("", ref).split()
    if not head:
        raise RefError(f"empty ref {ref!r}")
    kind = head[0]
    if kind in ("design", "proposal"):
        path = os.path.join(change_dir, kind + ".md")
        text = open(path, encoding="utf-8").read()
        if len(head) == 2 and re.fullmatch(r"D\d+[a-z]?", head[1]):
            return f"{kind} {head[1]}", heading_section(text, head[1], f"{kind}.md")
        if quoted and len(head) == 1:
            return f'{kind} "{quoted[0]}"', heading_section(text, quoted[0], f"{kind}.md")
        raise RefError(f"bad {kind} ref {ref!r}: use `{kind} D<n>` or `{kind} \"<heading>\"`")
    if kind == "module":
        if len(head) != 2:
            raise RefError(f"bad module ref {ref!r}")
        return module_ref(root, head[1])
    if kind == "file":
        if len(head) != 2:
            raise RefError(f"bad file ref {ref!r}")
        path = os.path.join(root, head[1])
        ranged = LINE_RANGE.match(head[1])
        if ranged and not os.path.exists(path):
            if quoted:
                raise RefError(f"bad file ref {ref!r}: a line range and a heading don't go together")
            first, last = int(ranged.group(2)), int(ranged.group(3))
            return (
                f"{ranged.group(1)}, lines {first} to {last}",
                line_range(root, ranged.group(1), first, last),
            )
        if not os.path.exists(path):
            raise RefError(f"no file {head[1]}")
        text = open(path, encoding="utf-8").read()
        if quoted:
            return f'{head[1]} "{quoted[0]}"', heading_section(text, quoted[0], head[1])
        return head[1], text.strip()
    # A capability of the change.
    spec = os.path.join(change_dir, "specs", kind, "spec.md")
    body_only = len(head) == 2 and head[1] == "body" and bool(quoted)
    if not os.path.exists(spec) or (len(head) != 1 and not body_only):
        raise RefError(f"unknown ref {ref!r} (not design/proposal/module/file or a capability of the change)")
    text = open(spec, encoding="utf-8").read()
    if not quoted:
        return f"{kind} (whole delta)", text.strip()
    reqs = requirements(text)
    if quoted[0] not in reqs:
        raise RefError(f'{kind} has no requirement "{quoted[0]}"')
    if body_only:
        return f'{kind}: "{quoted[0]}" (body)', requirement_body(reqs[quoted[0]])
    return f'{kind}: "{quoted[0]}"', reqs[quoted[0]]


def read_requirements(reads):
    """{capability: {requirement names}} named in Reads."""
    named = {}
    for ref in split_refs(reads):
        head = QUOTED.sub("", ref).split()
        quoted = QUOTED.findall(ref)
        if head and head[0] not in ("design", "proposal", "module", "file") and quoted and len(head) in (1, 2):
            named.setdefault(head[0], set()).add(quoted[0])
    return named


# ---------------------------------------------------------------- required tests


def test_kind(part):
    """The configured required-test kind a Tests entry is of, else None."""
    for k in required_tests():
        if part == k["kind"] or part.startswith(k["kind"] + " "):
            return k
    return None


def kind_none(k, part):
    return re.match(r"^%s none \((.+)\)$" % re.escape(k["kind"]), part, re.S)


def kind_titles(tests, k):
    """The titles of the `<kind> "..."` entries in Tests."""
    return [
        t for part in split_tests(tests)
        if test_kind(part) is k and not kind_none(k, part) for t in QUOTED.findall(part)
    ]


def kind_waivers(tests, k):
    """The reasons of the `<kind> none (...)` entries in Tests."""
    return [m.group(1) for part in split_tests(tests) if test_kind(part) is k and (m := kind_none(k, part))]


def kind_subjects(k, files):
    """[(path, name)] of the files a task lists that need this kind of test; name is the first
    capture group of `files` (a command, a task name), else the path."""
    out = []
    include = [re.compile(p) for p in k.get("files", [])]
    exclude = [re.compile(p) for p in k.get("files_exclude", [])]
    for p in file_list(files):
        if any(x.search(p) for x in exclude):
            continue
        for rx in include:
            m = rx.search(p)
            if m:
                name = m.group(1) if rx.groups else p
                if k.get("name_dash"):
                    name = name.replace("_", "-")
                out.append((p, name))
                break
    return out


def command_for(k, name):
    return k["command"].replace("{name}", name)


def covers(k, name, titles):
    rx = re.compile(r"\b%s(\s|$)" % re.escape(command_for(k, name)))
    return any(rx.search(t) for t in titles)


def missing_required(tests, files):
    """Messages for files that need a kind of test Tests does not name."""
    found = []
    for k in required_tests():
        subjects = kind_subjects(k, files)
        if not subjects:
            continue
        titles, waivers = kind_titles(tests, k), kind_waivers(tests, k)
        kind = k["kind"]
        if k.get("command"):
            for p, name in subjects:
                if not covers(k, name, titles):
                    found.append(k.get("missing", 'Tests: {item} needs {kind} "{command} <args>"')
                                 .format(item=p, name=name, kind=kind, command=command_for(k, name)))
        elif not titles and not waivers:
            found.append(k.get("missing", 'Tests: {item} needs a {kind} test: add {kind} "<test title>"'
                                          + (", or {kind} none (<reason>)" if k.get("waiver") else ""))
                         .format(item=subjects[0][0], name=subjects[0][1], kind=kind, command=""))
    return found


def source_files(files):
    """The files that count towards a task's size."""
    include, exclude = patterns("source"), patterns("source_exclude")
    return [
        p for p in file_list(files)
        if any(rx.search(p) for rx in include) and not any(rx.search(p) for rx in exclude)
    ]


def resolve_tests(change_dir, tests, reads):
    """[(capability, requirement, scenario)] named in Tests (required-test entries aside)."""
    in_reads = read_requirements(reads)
    out, waived = [], False
    for part in split_tests(tests):
        k = test_kind(part)
        if k:
            if kind_none(k, part):
                if not k.get("waiver"):
                    raise RefError(f'bad Tests entry {part!r}: use {k["kind"]} "<test title>"')
                continue
            if not QUOTED.findall(part) or QUOTED.sub("", part).replace(",", " ").split() != [k["kind"]]:
                alt = f' or {k["kind"]} none (<reason>)' if k.get("waiver") else ""
                raise RefError(f'bad Tests entry {part!r}: use {k["kind"]} "<test title>"{alt}')
            continue
        if NONE.match(part):
            waived = True
            continue
        head = QUOTED.sub("", part).replace(",", " ").split()
        names = QUOTED.findall(part)
        if len(head) != 1 or not names:
            raise RefError(f'bad Tests entry {part!r}: use <capability> "<Scenario>", ...')
        cap = head[0]
        spec = os.path.join(change_dir, "specs", cap, "spec.md")
        if not os.path.exists(spec):
            raise RefError(f"Tests: no capability {cap} in the change")
        reqs = requirements(open(spec, encoding="utf-8").read())
        for name in names:
            if " / " in name:
                req, scen = [s.strip() for s in name.split(" / ", 1)]
                if req not in reqs or scen not in scenarios(reqs[req]):
                    raise RefError(f'Tests: {cap} has no scenario "{scen}" under "{req}"')
                out.append((cap, req, scen))
                continue
            owners = [r for r, block in reqs.items() if name in scenarios(block)]
            if len(owners) > 1:
                owners = [r for r in owners if r in in_reads.get(cap, set())] or owners
            if not owners:
                raise RefError(f'Tests: {cap} has no scenario "{name}"')
            if len(owners) > 1:
                raise RefError(
                    f'Tests: {cap} scenario "{name}" is in {len(owners)} requirements; '
                    f'write "<Requirement> / {name}"'
                )
            out.append((cap, owners[0], name))
    if waived and out:
        raise RefError("Tests: names scenarios and says none (<reason>); keep one of the two")
    return out


def required_lines(tests):
    """Brief lines for the required-test entries of a Tests value."""
    out = []
    for k in required_tests():
        template = k.get("brief", '- {kind}: "{title}"')
        out += [template.replace("{kind}", k["kind"]).replace("{title}", t) for t in kind_titles(tests, k)]
        out += [f"- {k['kind']}: none ({reason})" for reason in kind_waivers(tests, k)]
    return out


# ---------------------------------------------------------------- commands


def problems(root, change_dir, task):
    """Every field and ref problem of one task."""
    f = task["fields"]
    found = [f"{name}: missing" for name in ("Reads", "Tests", "Files", "Check") if name not in f]
    if "Reads" in f:
        for ref in split_refs(f["Reads"]):
            try:
                resolve(root, change_dir, ref)
            except (RefError, OSError) as e:
                found.append(f"Reads: {e}")
        if "Tests" in f:
            try:
                resolve_tests(change_dir, f["Tests"], f["Reads"])
            except (RefError, OSError) as e:
                found.append(str(e))
    if "Files" in f:
        found += missing_required(f.get("Tests", ""), f["Files"])
        count = len(source_files(f["Files"]))
        size = f.get("Size", "")
        if count > max_source_files() and not re.match(r"^mechanical \(.+\)$", size):
            found.append(
                f"lists {count} source files: split the task, or add `Size: mechanical (<reason>)`"
            )
    return found


def check(root, change):
    change_dir = os.path.join(root, "openspec", "changes", change)
    path = os.path.join(change_dir, "tasks.md")
    if not os.path.exists(path):
        print(f"packet: no {os.path.relpath(path, root)}", file=sys.stderr)
        return 2
    _notes, _groups, tasks = parse_tasks(path)
    open_tasks = [t for t in tasks if not t["done"]]
    bad = 0
    if open_tasks and re.search(r"(?m)^Wave [1-9]", open(path, encoding="utf-8").read()):
        design = os.path.join(change_dir, "design.md")
        text = open(design, encoding="utf-8").read() if os.path.exists(design) else ""
        if not re.search(r"(?m)^#{2,4} Interfaces\b", mask_fences(text)):
            print("design.md: no \"Interfaces\" section: tasks run in parallel waves, so every value that "
                  "crosses a task boundary needs its shape and owner written there first")
            bad += 1
    wave_line = re.compile(r"(?m)^Wave \d")
    wave_groups = {n: bool(wave_line.search("\n".join(g[1]))) for n, g in _groups.items()}
    if open_tasks and any(wave_groups.values()):
        # The tasks run in waves: sdd:parallel-apply reads each group's `Wave N · depends on:` line.
        for number in sorted({t["group"] for t in open_tasks if t["group"]}, key=int):
            if not wave_groups.get(number):
                print(f"group {number}: no Wave line: the tasks run in waves, so write `Wave N · depends on: ...` under its heading")
                bad += 1
        if not any(re.search(r"(?m)^Wave 1\b", "\n".join(g[1])) for g in _groups.values()):
            print("tasks.md: no Wave 1 line: the first wave after wave 0 is Wave 1")
            bad += 1
    for task in open_tasks:
        if len(task["text"]) > TASK_BUDGET:
            print(f"task {task['id']}: {len(task['text']) // 1024} KB of prose and fields, over the ~{TASK_BUDGET // 1024} KB budget: "
                  "detail lives in the design section the task's `Reads:` names")
            bad += 1
    for number, (_heading, gnotes) in _groups.items():
        gtext = "\n".join(gnotes)
        if len(gtext) > GROUP_BUDGET:
            print(f"group {number}: notes {len(gtext) // 1024} KB, over the ~{GROUP_BUDGET // 1024} KB budget")
            bad += 1
    tasks_text = open(path, encoding="utf-8").read()
    if len(tasks_text) > TASKS_BUDGET:
        print(f"tasks.md: {len(tasks_text) // 1024} KB, over the ~{TASKS_BUDGET // 1024} KB budget: "
              "the wave plan reads it whole; detail lives in the design sections the tasks name")
        bad += 1
    design = os.path.join(change_dir, "design.md")
    if os.path.exists(design):
        size = os.path.getsize(design)
        if size > DESIGN_BUDGET:
            print(f"design.md: {size // 1024} KB, over the ~{DESIGN_BUDGET // 1024} KB budget: a design is "
                  "decisions, not reference (a wave-plan author reads it whole; contracts live in modules)")
            bad += 1
    for task in open_tasks:
        for problem in problems(root, change_dir, task):
            print(f"task {task['id']}: {problem}")
            bad += 1
    print(f"packet: {len(open_tasks)} open task(s), {bad} problem(s)")
    return 1 if bad else 0


def brief(root, change, task_id):
    change_dir = os.path.join(root, "openspec", "changes", change)
    path = os.path.join(change_dir, "tasks.md")
    if not os.path.exists(path):
        print(f"packet: no {os.path.relpath(path, root)}", file=sys.stderr)
        return 2
    notes, groups, tasks = parse_tasks(path)
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task is None:
        print(f"packet: no task {task_id} in {change}", file=sys.stderr)
        return 2
    issues = problems(root, change_dir, task)
    if issues:
        for issue in issues:
            print(f"packet: task {task_id}: {issue}", file=sys.stderr)
        print("packet: fix the task's fields (or ask the coordinator) before starting", file=sys.stderr)
        return 1
    f = task["fields"]
    out = [
        f"# Brief: task {task_id} of {change}",
        "",
        "This brief is your whole briefing. Read the files on your `Files:` list and grep for",
        "anything else; don't read tasks.md, design.md, or the spec deltas whole. If something",
        "you need is missing here, stop and report it: the task's `Reads:` line is incomplete.",
        "",
        "## Notes for every task",
        "",
        notes,
    ]
    if task["group"] in groups:
        heading, gnotes = groups[task["group"]]
        out += ["", "## Group: " + heading.lstrip("# "), "", "\n".join(gnotes).strip()]
    out += ["", "## Your task", "", task["text"]]
    tests = resolve_tests(change_dir, f["Tests"], f["Reads"])
    out += ["", "## Tests to write (one per scenario, before the code)", ""]
    for cap, req, scen in tests:
        out += scenario_lines(change_dir, cap, req, scen)
    out += [f"- {part}" for part in split_tests(f["Tests"]) if NONE.match(part)]
    out += required_lines(f["Tests"])
    out += ["", "## What the task reads"]
    for ref in split_refs(f["Reads"]):
        title, text = resolve(root, change_dir, ref)
        out += ["", f"### {title}", "", text]
    text = "\n".join(out).rstrip() + "\n"
    sys.stdout.write(text)
    sys.stdout.write(f"\n(brief: {len(text) // 1024} KB, about {len(text) // 4000}k tokens)\n")
    return 0


def brief_group(root, change, group_id):
    """One brief for a group's open tasks, to run in order in one context."""
    change_dir = os.path.join(root, "openspec", "changes", change)
    path = os.path.join(change_dir, "tasks.md")
    if not os.path.exists(path):
        print(f"packet: no {os.path.relpath(path, root)}", file=sys.stderr)
        return 2
    notes, groups, tasks = parse_tasks(path)
    if group_id not in groups:
        print(f"packet: no group {group_id} in {change}", file=sys.stderr)
        return 2
    open_tasks = [t for t in tasks if t["group"] == group_id and not t["done"]]
    if not open_tasks:
        print(f"packet: group {group_id} of {change} has no open tasks", file=sys.stderr)
        return 2
    bad = 0
    for task in open_tasks:
        for problem in problems(root, change_dir, task):
            print(f"packet: task {task['id']}: {problem}", file=sys.stderr)
            bad += 1
    if bad:
        print("packet: fix the tasks' fields (or ask the coordinator) before starting", file=sys.stderr)
        return 1
    heading, gnotes = groups[group_id]
    out = [
        f"# Brief: group {group_id} of {change}",
        "",
        "This brief is your whole briefing: the group's tasks, in order, in one",
        "context. Take one task at a time; a task whose `Check:` fails is fixed and",
        "rerun before you move on. Hand back when all are done or at the context",
        "hook's wrap line, with the tasks done and what remains; a fresh worker",
        "continues the rest. Read the files on each task's `Files:` list and grep",
        "for anything else; don't read tasks.md, design.md, or the spec deltas",
        "whole. If something you need is missing here, stop and report it: a",
        "task's `Reads:` line is incomplete.",
        "",
        "## Notes for every task",
        "",
        notes,
        "",
        "## Group: " + heading.lstrip("# "),
        "",
        "\n".join(gnotes).strip(),
    ]
    shared = []  # (title, text) of each unique Reads ref, in first-seen order
    seen = set()
    for task in open_tasks:
        f = task["fields"]
        out += ["", f"## Task {task['id']}", "", task["text"]]
        tests = resolve_tests(change_dir, f["Tests"], f["Reads"])
        out += ["", f"### Tests to write for {task['id']} (one per scenario, before the code)", ""]
        for cap, req, scen in tests:
            out += scenario_lines(change_dir, cap, req, scen)
        out += [f"- {part}" for part in split_tests(f["Tests"]) if NONE.match(part)]
        out += required_lines(f["Tests"])
        for ref in split_refs(f["Reads"]):
            title, text = resolve(root, change_dir, ref)
            if title not in seen:
                seen.add(title)
                shared.append((title, text))
    out += ["", "## What the brief reads"]
    for title, text in shared:
        out += ["", f"### {title}", "", text]
    text = "\n".join(out).rstrip() + "\n"
    sys.stdout.write(text)
    sys.stdout.write(f"\n(brief: {len(text) // 1024} KB, about {len(text) // 4000}k tokens)\n")
    return 0


def main(argv, root, cfg):
    CFG.clear()
    CFG.update(cfg)
    args = argv[1:]
    if len(args) == 2 and args[0] == "--check":
        return check(root, args[1])
    if len(args) == 2 and not args[0].startswith("-"):
        if re.fullmatch(r"\d+", args[1]):
            return brief_group(root, args[0], args[1])
        return brief(root, args[0], args[1])
    print(__doc__.strip(), file=sys.stderr)
    return 2
