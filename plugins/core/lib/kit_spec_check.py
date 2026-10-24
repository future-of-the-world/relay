"""Check the form of an OpenSpec change's spec deltas, then its tasks.

    kit spec-check <change>          check openspec/changes/<change>/specs
    kit spec-check --path <dir>      check every spec.md under <dir>

Every ADDED or MODIFIED requirement:

- states its rule in SHALL or MUST form;
- has at least one `#### Scenario:`, and every scenario has a **WHEN** and a
  **THEN** line.

A project may add kinds of requirement that also need failure scenarios (its
`[[spec_check.group]]` bindings in .claude/kit.toml). A requirement is of a
kind when its name or prose (the text before its first scenario) matches the
group's `trigger`; it then needs one scenario for each of the group's `cases`
(matched in scenario titles and their GIVEN/WHEN/THEN/AND lines). Example:

    [[spec_check.group]]
    name = "stored data"
    trigger = '\\b(stor(e|ed|age)|persist\\w*)\\b'
    [spec_check.group.cases]
    "Corrupt data" = 'corrupt\\w*|garbage|hand[- ]edited'

When a case can't happen for a requirement, keep the scenario and say why in
it, or skip the case with a comment in the requirement body that gives the
reason:

    <!-- spec-check: skip Older data, Storage unavailable (reads only, and the field is new) -->
    <!-- spec-check: skip all (the text is bundled with the app, nothing is read back) -->

A skip without a reason in parentheses is reported as a gap. A line inside a
fenced code block is never a heading or a scenario.

Exits 1 and lists the gaps. For a change (not --path), it then runs
`kit packet --check <change>`: every open task has `Reads:`, `Tests:`,
`Files:`, and `Check:`, its refs resolve, it stays within the task size, its
required tests are named. See `kit packet`.
"""
import glob
import os
import re
import sys

import kit_packet

SKIP = re.compile(r"<!--\s*spec-check:\s*skip\b(.*?)-->", re.I | re.S)
SKIP_REASON = re.compile(r"^\s*([^()]*?)\s*\((.+)\)\s*$", re.S)
SECTION = re.compile(r"(?m)^## (ADDED|MODIFIED|REMOVED|RENAMED) Requirements")
REQUIREMENT = re.compile(r"(?ms)^### Requirement: (.+?)\n(.*?)(?=^### Requirement: |^## |\Z)")
SCENARIO = re.compile(r"(?ms)^#### Scenario: (.+?)\n(.*?)(?=^#### |^### |^## |\Z)")
mask_fences = kit_packet.mask_fences


def load_groups(cfg):
    """[{name, trigger, cases}] from the [[spec_check.group]] bindings."""
    groups = []
    for g in cfg.get("spec_check", {}).get("group", []):
        groups.append({
            "name": g["name"],
            "trigger": re.compile(g["trigger"], re.I),
            "cases": dict(g.get("cases", {})),
        })
    return groups


def checked_blocks(text):
    """Yield (name, body) for requirements in ADDED/MODIFIED sections.

    A file with no delta headers (a main spec) is checked whole.
    """
    masked = mask_fences(text)
    sections = list(SECTION.finditer(masked))
    if not sections:
        yield from ((m.group(1), text[m.start(2) : m.end(2)]) for m in REQUIREMENT.finditer(masked))
        return
    for i, sec in enumerate(sections):
        if sec.group(1) not in ("ADDED", "MODIFIED"):
            continue
        end = sections[i + 1].start() if i + 1 < len(sections) else len(text)
        chunk, mchunk = text[sec.start() : end], masked[sec.start() : end]
        yield from ((m.group(1), chunk[m.start(2) : m.end(2)]) for m in REQUIREMENT.finditer(mchunk))


def skipped(body, all_cases):
    """Cases skipped by spec-check comments, and any skip missing a reason."""
    cases, bad = set(), []
    for m in SKIP.finditer(body):
        parsed = SKIP_REASON.match(m.group(1))
        if not parsed or not parsed.group(2).strip():
            bad.append(m.group(0).strip())
            continue
        names = [n.strip().lower() for n in parsed.group(1).split(",") if n.strip()]
        for case in all_cases:
            if "all" in names or case.lower() in names:
                cases.add(case)
    return cases, bad


def form_problems(name, body):
    prose = re.split(r"(?m)^#### Scenario:", mask_fences(body), maxsplit=1)[0]
    found = []
    if not re.search(r"\b(SHALL|MUST)\b", prose):
        found.append("no SHALL/MUST statement")
    scens = list(SCENARIO.finditer(mask_fences(body)))
    if not scens:
        found.append("no #### Scenario:")
    for s in scens:
        text = s.group(2)
        if not re.search(r"\*\*WHEN\*\*", text) or not re.search(r"\*\*THEN\*\*", text):
            found.append(f'scenario "{s.group(1).strip()}" lacks WHEN or THEN')
    return found


def gaps(body, cases):
    """The cases no scenario of the requirement covers."""
    masked = mask_fences(body)
    text = " ".join(
        re.findall(r"(?m)^#### Scenario: (.+)$", masked)
        + re.findall(r"\*\*(?:GIVEN|WHEN|THEN|AND)\*\* (.+)", masked)
    )
    return [case for case, pattern in cases.items() if not re.search(pattern, text, re.I)]


def main(argv, root, cfg):
    args = argv[1:]
    if len(args) == 1 and not args[0].startswith("-"):
        specs = os.path.join(root, "openspec", "changes", args[0], "specs")
    elif len(args) == 2 and args[0] == "--path":
        specs = args[1]
    else:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    groups = load_groups(cfg)
    all_cases = [case for g in groups for case in g["cases"]]
    files = sorted(glob.glob(os.path.join(specs, "**", "spec.md"), recursive=True))
    if not files:
        print(f"spec-check: no spec.md under {specs}", file=sys.stderr)
        return 2

    checked, touching, problems = 0, 0, []
    for path in files:
        text = open(path, encoding="utf-8").read()
        for name, body in checked_blocks(text):
            checked += 1
            found = form_problems(name, body)
            prose = re.split(r"(?m)^#### Scenario:", mask_fences(body), maxsplit=1)[0]
            prose = SKIP.sub("", prose)
            hit = [g for g in groups if g["trigger"].search(name + " " + prose)]
            if hit:
                touching += 1
                skip, bad = skipped(body, all_cases)
                for group in hit:
                    found += [
                        f"missing failure scenario: {c}" for c in gaps(body, group["cases"]) if c not in skip
                    ]
                found += [f"skip without a reason: {b}" for b in bad]
            if found:
                problems.append((os.path.relpath(path, specs), name.strip(), found))

    for path, name, found in problems:
        print(f"{path}: \"{name}\": {'; '.join(found)}")
    touched = f", {touching} touching {' or '.join(g['name'] for g in groups)}" if groups else ""
    print(f"spec-check: {checked} requirement(s){touched}, {len(problems)} with problems")
    status = 1 if problems else 0
    if len(args) == 1 and os.path.exists(os.path.join(root, "openspec", "changes", args[0], "tasks.md")):
        sys.stdout.flush()
        status = max(status, kit_packet.main(["kit packet", "--check", args[0]], root, cfg.get("packet", {})))
    return status
