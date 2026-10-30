"""The one checking parser of a project's .claude/kit.toml (and of the env overrides that replace its values).

`load(root)` never raises. It returns a `Kit`: the values to use (a wrong value is replaced by the key's default, and every
guard key's default is its strict setting) and the `problems` found, each a sentence naming the file, the key, the value,
what is wrong and what was used instead. Readers act on the values and show the problems of their sections.

The schema below lists every key relay reads or writes. Relay's own flat sections are closed (an unknown key is a problem);
`[product]` and the nested sections (`packet`, `spec_check`, `guard`, `license`) are open here: their own parsers refuse loudly.

Standard library only; the hooks may run under Python 3.9.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

import relay_toml

KIT_PATH = os.path.join(".claude", "kit.toml")


@dataclass(frozen=True)
class Field:
    kind: str                                  # "bool", "int", "str", "strlist"
    default: Any
    choices: tuple = ()                        # allowed texts, for a "str"
    bounds: Optional[tuple] = None             # (low, high), for an "int"
    outside: str = "default"                   # a number outside the bounds: "clamp" or "default"


@dataclass(frozen=True)
class Problem:
    where: str      # ".claude/kit.toml [delegate] opus_for_builders" or "env RELAY_DELEGATE_TYPED_AGENTS_ONLY"
    value: str      # repr of the wrong value ("" when the problem is the key or file itself)
    wrong: str      # what is wrong
    used: str       # what was used instead ("" when nothing was)

    def line(self) -> str:
        has = f" = {self.value}" if self.value else ""
        used = f"; used {self.used}" if self.used else ""
        return f"{self.where}{has} {self.wrong}{used}"


Schema = dict[str, dict[str, Field]]

SCHEMA: Schema = {
    "project": {"name": Field("str", ""), "default_branch": Field("str", "main"), "worktrees": Field("str", ".worktrees"),
                "stack_skills": Field("strlist", [])},
    "gate": {k: Field("str", "") for k in ("wt", "check", "ci", "ci_quick", "ci_log", "final")},
    "coordination": {"mode": Field("str", "leadless")},
    "rules": {"lanes": Field("int", 4, bounds=(1, 8)), "wave_min": Field("int", 3, bounds=(1, 6)),
              "load": Field("strlist", []), "read": Field("strlist", [])},
    "specs": {"method": Field("str", "none", choices=("none", "openspec"))},   # the spec method plugins: plugins/*/flow.json with "slot": "specs"
    "flow": {"kind": Field("str", "none"), "plugin": Field("str", "")},
    "delegate": {
        "typed_agents_only": Field("bool", True),
        "no_session_copy_above_tokens": Field("int", 100_000, bounds=(100_000, 10**9), outside="default"),
        "max_agents_per_change": Field("int", 4, bounds=(1, 1000)),
        "opus_for_builders": Field("str", "after_a_failure", choices=("after_a_failure", "always", "never")),
        "require_skill": Field("str", "deny", choices=("deny", "note", "off")),
        "label_guard": Field("str", "deny", choices=("deny", "note", "off")),
    },
    "observe": {"log_prompts": Field("bool", False)},
    "metrics": {"enabled": Field("bool", True), "coverage": Field("str", "every", choices=("every", "landing", "off")),
                "sweep_quiet_min": Field("int", 60, bounds=(10, 1440), outside="clamp")},
    "front": {"feature_lanes": Field("int", 0, bounds=(0, 8)),   # out of bounds: 0, as relay_lane_features does
              "ask_reminder_days": Field("int", 7, bounds=(1, 30), outside="clamp"),
              "ask_reminder_lines": Field("int", 5, bounds=(1, 20), outside="clamp"),
              "lanes_line_items": Field("int", 3, bounds=(0, 10)),
              "stop_nudge": Field("int", 1, bounds=(0, 2), outside="clamp"),
              "lane_quiet_hours": Field("int", 3, bounds=(1, 24), outside="clamp")},
    "land": {"land_tries": Field("int", 2, bounds=(1, 3), outside="clamp"),
             "land_inert_tries": Field("int", 10, bounds=(3, 50), outside="clamp"),
             "land_ff_lock_tries": Field("int", 3, bounds=(1, 10), outside="clamp")},
}
# Keys an older kit.toml template wrote that no code reads: (section, key) -> what to say
RETIRED = {("observe", "enabled"): "has no effect (no code reads it); remove the line"}
# [delegate] keys renamed on 31 Oct (they named the code, not what they do): (section, old key) -> new key.
# `relay setup` renames them in a kit.toml; until then the old name is a problem that names the new one.
RENAMED = {("delegate", "typed_only"): "typed_agents_only",
           ("delegate", "fork_limit"): "no_session_copy_above_tokens",
           ("delegate", "max_parallel"): "max_agents_per_change",
           ("delegate", "build_tier_opus"): "opus_for_builders"}
OLD_OPUS_VALUES = {"escalate": "after_a_failure", "allow": "always", "deny": "never"}   # old build_tier_opus -> opus_for_builders
OPEN_SECTIONS = ("product", "packet", "spec_check", "guard", "license")   # relay does not list their keys here
KNOWN_SECTIONS = tuple(SCHEMA) + OPEN_SECTIONS

# Env overrides that replace a hook constant: whole numbers, at least 1000.
CTX_DEFAULTS = {"RELAY_CTX_HANDOVER_AT": 350_000, "RELAY_CTX_WRAP_AT": 200_000, "RELAY_CTX_STEP": 30_000}
CTX_LOW = 1000
ENV_PREFIXES = ("RELAY_DELEGATE_", "RELAY_CTX_")


def _check(where: str, raw: Any, spec: Field) -> tuple[Any, Optional[Problem]]:
    """The value to use for `raw` under `spec`, and the problem when `raw` is wrong."""
    default = spec.default
    shown = repr(raw)

    def bad(wrong: str, used: Any = default) -> tuple[Any, Problem]:
        return used, Problem(where, shown, wrong, repr(used))

    if spec.kind == "bool":
        return (raw, None) if isinstance(raw, bool) else bad("is not true or false (a boolean)")
    if spec.kind == "int":
        if isinstance(raw, bool) or not isinstance(raw, int):
            return bad("is not a whole number")
        if spec.bounds and not spec.bounds[0] <= raw <= spec.bounds[1]:
            low, high = spec.bounds
            used = max(low, min(high, raw)) if spec.outside == "clamp" else default
            return bad(f"is outside {low}..{high}", used)
        return raw, None
    if spec.kind == "strlist":
        if isinstance(raw, list) and all(isinstance(x, str) for x in raw):
            return raw, None
        return bad("is not a list of texts")
    if not isinstance(raw, str):
        return bad("is not text")
    if spec.choices and raw not in spec.choices:
        return bad("is not one of " + ", ".join(spec.choices))
    return raw, None


@dataclass(frozen=True)
class Kit:
    path: str
    values: dict[str, dict[str, Any]] = field(default_factory=dict)    # flat section -> key -> value to use
    raw: dict[str, Any] = field(default_factory=dict)                  # the parsed file, for nested and open sections
    problems: tuple[Problem, ...] = ()
    broken: Optional[Problem] = None                                   # the syntax error, if any

    def get(self, section: str, key: str) -> Any:
        return self.values[section][key]

    def problems_of(self, *sections: str) -> list[Problem]:
        """The problems a reader shows: the syntax error, plus those in its sections (a section's problems start with its [name])."""
        tags = tuple(f"[{s}]" for s in sections)
        return ([self.broken] if self.broken else []) + [p for p in self.problems if p is not self.broken and any(t in p.where for t in tags)]


def _defaults() -> dict[str, dict[str, Any]]:
    return {s: {k: (list(f.default) if isinstance(f.default, list) else f.default) for k, f in keys.items()} for s, keys in SCHEMA.items()}


def parse(text: str, path: str = KIT_PATH) -> Kit:
    """Parse the text of a kit.toml. Never raises."""
    name = KIT_PATH
    values = _defaults()
    try:
        raw = relay_toml.loads(text)
    except Exception as exc:
        broken = Problem(name, "", f"cannot be read: {exc}", "the defaults")
        return Kit(path, values, {}, (broken,), broken)
    problems: list[Problem] = []
    for section, body in raw.items():
        if section not in KNOWN_SECTIONS:
            problems.append(Problem(f"{name} [{section}]", "", "is not a section relay knows", ""))
            continue
        if not isinstance(body, dict):
            problems.append(Problem(f"{name} [{section}]", "", "is not a table", "the defaults"))
            continue
        keys = SCHEMA.get(section)
        if keys is None:
            continue
        for key, value in body.items():
            where = f"{name} [{section}] {key}"
            if (section, key) in RETIRED:
                problems.append(Problem(where, "", RETIRED[(section, key)], ""))
                continue
            if (section, key) in RENAMED:
                new = RENAMED[(section, key)]
                problems.append(Problem(where, "", f"is an old name; it is now {new} (`relay setup` renames it)", ""))
                continue
            if key not in keys:
                problems.append(Problem(where, "", "is not a key relay knows", ""))
                continue
            try:
                used, problem = _check(where, value, keys[key])
            except Exception as exc:   # a schema or value shape this code did not foresee: say so, keep the default
                used, problem = keys[key].default, Problem(where, repr(value), f"could not be checked ({exc})", "the default")
            values[section][key] = used
            if problem:
                problems.append(problem)
    return Kit(path, values, raw, tuple(problems), None)


_cache: dict[str, tuple[tuple[int, int], Kit]] = {}


def load(root: str) -> Kit:
    """The Kit of `<root>/.claude/kit.toml`; defaults and no problems when the file is missing. Never raises.
    One parse per file and modification time in a process."""
    path = os.path.join(root or ".", KIT_PATH)
    try:
        info = os.stat(path)
        stamp = (info.st_mtime_ns, info.st_size)
    except OSError:
        return parse("", path)
    hit = _cache.get(path)
    if hit and hit[0] == stamp:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as handle:
            kit = parse(handle.read(), path)
    except (OSError, UnicodeDecodeError) as exc:
        broken = Problem(KIT_PATH, "", f"cannot be read: {exc}", "the defaults")
        kit = Kit(path, _defaults(), {}, (broken,), broken)
    _cache[path] = (stamp, kit)
    return kit


def env_value(name: str, spec: Field, environ: Optional[dict[str, str]] = None) -> tuple[Any, Optional[Problem]]:
    """The value of the env override `name` under `spec` (the default when it is not set), and the problem when it is wrong.
    Booleans accept only true or false in any letter case."""
    text = (environ if environ is not None else os.environ).get(name)
    where = f"env {name}"
    if text is None:
        return spec.default, None
    if spec.kind == "bool":
        if text.lower() in ("true", "false"):
            return text.lower() == "true", None
        return spec.default, Problem(where, repr(text), "is not true or false", repr(spec.default))
    if spec.kind == "int":
        try:
            number = int(text)
        except ValueError:
            return spec.default, Problem(where, repr(text), "is not a whole number", repr(spec.default))
        return _check(where, number, spec)
    return _check(where, text, spec)


def delegate_settings(root: str, environ: Optional[dict[str, str]] = None) -> tuple[dict[str, Any], list[Problem]]:
    """The [delegate] values the routing guard acts on (kit.toml, then RELAY_DELEGATE_<KEY> overrides) and the problems found,
    the file's syntax error first."""
    kit = load(root)
    out = dict(kit.values["delegate"])
    problems = kit.problems_of("delegate", "metrics")
    for key, spec in SCHEMA["delegate"].items():
        name = "RELAY_DELEGATE_" + key.upper()
        if name in (environ if environ is not None else os.environ):
            out[key], problem = env_value(name, spec, environ)
            if problem:
                problems.append(problem)
    return out, problems


def ctx_value(name: str, environ: Optional[dict[str, str]] = None) -> tuple[int, Optional[Problem]]:
    """RELAY_CTX_* as a whole number of at least 1000; the default and a problem otherwise."""
    return env_value(name, Field("int", CTX_DEFAULTS[name], bounds=(CTX_LOW, 10**12)), environ)


def env_problems(environ: dict[str, str]) -> list[Problem]:
    """Problems in the RELAY_DELEGATE_* and RELAY_CTX_* names of `environ`: an unknown name, a wrong value."""
    out: list[Optional[Problem]] = []
    for name in sorted(environ):
        if not name.startswith(ENV_PREFIXES):
            continue
        key = name[len("RELAY_DELEGATE_"):].lower() if name.startswith("RELAY_DELEGATE_") else None
        if key is not None and key in SCHEMA["delegate"]:
            out.append(env_value(name, SCHEMA["delegate"][key], environ)[1])
        elif name in CTX_DEFAULTS:
            out.append(ctx_value(name, environ)[1])
        elif key is not None and ("delegate", key) in RENAMED:
            out.append(Problem(f"env {name}", "", f"is an old name; it is now RELAY_DELEGATE_{RENAMED[('delegate', key)].upper()}", ""))
        else:
            out.append(Problem(f"env {name}", "", "is not a setting relay knows", ""))
    return [p for p in out if p]


def note(kit: Kit, *sections: str) -> Optional[str]:
    """The text a hook puts in its context for the problems of `sections` (and the file's syntax error), or None."""
    return say(kit.problems_of(*sections))


def say(problems: list[Problem]) -> Optional[str]:
    """The settings note for `problems`, or None when there are none."""
    if not problems:
        return None
    return "Settings note: " + "; ".join(p.line() for p in problems) + ". Fix the line; relay doctor lists every problem."


_said: set[str] = set()


def warn(kit: Kit, *sections: str) -> None:
    """Print the problems of `sections` on stderr, each line once per process (for commands)."""
    for problem in kit.problems_of(*sections):
        line = "relay: " + problem.line()
        if line not in _said:
            _said.add(line)
            print(line, file=sys.stderr)


def rename_old_delegate_keys(text: str) -> tuple[str, list[str]]:
    """`text` of a kit.toml with the old [delegate] key names (RENAMED) and the old opus_for_builders values replaced; the lines it did."""
    out: list[str] = []
    did: list[str] = []
    section = None
    for line in text.split("\n"):
        head = re.match(r"\s*\[([^\]]+)\]", line)
        if head:
            section = head.group(1).strip()
        elif section == "delegate":
            m = re.match(r"(\s*)([A-Za-z_]+)(\s*=\s*)(.*)$", line)
            if m and ("delegate", m.group(2)) in RENAMED:
                old, new, value = m.group(2), RENAMED[("delegate", m.group(2))], m.group(4)
                if old == "build_tier_opus":
                    v = re.match(r'"([^"]*)"(.*)$', value)
                    if v and v.group(1) in OLD_OPUS_VALUES:
                        value = f'"{OLD_OPUS_VALUES[v.group(1)]}"{v.group(2)}'
                line = f"{m.group(1)}{new}{m.group(3)}{value}"
                did.append(f"[delegate] {old} -> {new}")
        out.append(line)
    return "\n".join(out), did
