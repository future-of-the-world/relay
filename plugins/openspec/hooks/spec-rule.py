#!/usr/bin/env python3
"""openspec: the spec method's one hook (SessionStart, SubagentStart, UserPromptSubmit).

A project turns the spec steps on with `[specs] method = "openspec"` in its committed .claude/kit.toml.
Only then does this hook say anything:
- SessionStart and SubagentStart: the OpenSpec rule (rules/openspec.md of this plugin) and the table of the
  spec steps (rendered from flow.json `steps`), as additional context, so the main session and every agent
  it starts read the same text.
- UserPromptSubmit: a prompt that starts with an /opsx:* trigger gets one line, "load the stage's skill
  first" (or the stage's note), from flow.json `stages`.

The hook is the plugin's own, so it runs only where Claude Code loaded the plugin; there is no settings
file to parse to know that. It reads only files of this plugin (CLAUDE_PLUGIN_ROOT) and the project's
kit.toml, and needs no relay checkout. No method, no manifest or an event it does not know: nothing is
said. Fails open. Runs under python 3.9 (macOS /usr/bin/python3).

Tests: tests/test_openspec_hook.py
"""

import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

METHOD = "openspec"
PLUGIN = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def project_root(cwd: str) -> str:
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        out = ""
    return out or cwd


def project_method(root: str) -> str:
    """The `[specs] method` of the project's .claude/kit.toml; "none" when unset or unreadable."""
    path = os.path.join(root, ".claude", "kit.toml")
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return "none"
    try:
        import tomllib
        method = tomllib.loads(raw.decode("utf-8")).get("specs", {}).get("method", "none")
        return method if isinstance(method, str) else "none"
    except ImportError:
        pass   # python before 3.11: read the one key by hand
    except Exception:
        return "none"
    section = ""
    for text in raw.decode("utf-8", "replace").splitlines():
        text = text.split("#", 1)[0].strip()
        if text.startswith("["):
            section = text.strip("[] ")
        elif section == "specs" and text.startswith("method") and "=" in text:
            return text.split("=", 1)[1].strip().strip("\"'")
    return "none"


def load_manifest() -> Optional[Dict[str, Any]]:
    try:
        with open(os.path.join(PLUGIN, "flow.json"), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def load_rule() -> Optional[Dict[str, str]]:
    """rules/openspec.md as {title, body}: `# Title`, `> gist`, body (the format of relay's rules)."""
    try:
        with open(os.path.join(PLUGIN, "rules", "openspec.md"), encoding="utf-8") as handle:
            lines = handle.read().split("\n")
    except OSError:
        return None
    if len(lines) < 2 or not lines[0].startswith("# ") or not lines[1].startswith("> "):
        return None
    return {"title": lines[0][2:].strip(), "body": "\n".join(lines[2:]).strip("\n")}


def steps_table(manifest: Dict[str, Any]) -> List[str]:
    """The spec method's steps as a table, rendered from flow.json `steps`."""
    lines = ["### Spec steps in the change cycle", "",
             "Each step runs at the step of the change cycle it names (the delegate skill, \"Review loop\").", "",
             "| At step | What happens | Skill or agent |", "|---|---|---|"]
    for step in manifest.get("steps", []):
        who = step.get("skill") or step.get("agent") or ""
        lines.append(f"| {step['at']} | {step['does']} | {('`' + who + '`') if who else ''} |")
    lines.append("")
    return lines


def render(rule: Dict[str, str], manifest: Dict[str, Any]) -> str:
    """The rule and the steps table: what a session with the spec method on reads."""
    out = [f"## {rule['title']}", "", rule["body"], ""] + steps_table(manifest)
    return "\n".join(out).rstrip("\n") + "\n"


def stage_for(prompt: str, manifest: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The stage a prompt starts, by its first word (a slash trigger)."""
    first = prompt.strip().split(None, 1)[0] if prompt.strip() else ""
    if not first.startswith("/"):
        return None
    for stage in manifest.get("stages", []):
        for trigger in stage.get("triggers", []):
            if first == trigger or first.startswith(trigger + ":"):
                return stage
    return None


def line_for(stage: Dict[str, Any]) -> Optional[str]:
    label = "spec steps"
    if stage.get("skill"):
        text = (f"Stage `{stage['name']}` of the {label}: load the `{stage['skill']}` skill with the Skill tool before "
                f"the first step and follow it; where it differs from a command's own text, `{stage['skill']}` wins.")
        return text + (" " + stage["note"] if stage.get("note") else "")
    if stage.get("note"):
        return f"Stage `{stage['name']}` of the {label}: {stage['note']}"
    return None


def answer(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    event = data.get("hook_event_name")
    if event not in ("SessionStart", "SubagentStart", "UserPromptSubmit"):
        return None
    if event == "UserPromptSubmit" and data.get("agent_id"):
        return None
    root = project_root(data.get("cwd") or os.getcwd())
    if project_method(root) != METHOD:
        return None
    manifest = load_manifest()
    if not manifest:
        return None
    if event == "UserPromptSubmit":
        stage = stage_for(data.get("prompt") or "", manifest)
        text = line_for(stage) if stage else None
    else:
        rule = load_rule()
        text = render(rule, manifest) if rule else None
    if not text:
        return None
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def main() -> None:
    out = answer(json.load(sys.stdin))
    if out:
        json.dump(out, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
