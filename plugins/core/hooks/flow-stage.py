#!/usr/bin/env python3
"""core: the flow stage hook (UserPromptSubmit).

A project binds where its work comes from in .claude/kit.toml: [flow] kind =
"issues" (or any plugin that ships a flow.json). When a prompt starts with a
trigger of that manifest (`/issue 42`, ...), this hook adds one line: load the
stage's skill first and follow it, or, for a stage with only a note, the note.
The spec method's own line (`/opsx:*`, [specs] method) is the openspec plugin's
hook, not this one: core cannot know whether that plugin is loaded.

The manifest is found by `kit path <plugin>/flow.json` (the version this
project runs), else beside this plugin in a source checkout. No binding, no
manifest, or no matching trigger: nothing is added. Fails open.

Tests: plugins/core/tests/flow-stage.test.sh
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import relay_toml  # noqa: E402
KIT = os.path.join(HERE, "..", "bin", "kit")


def project_root(cwd):
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        out = ""
    return out or cwd


def bindings(root):
    """[(label, plugin)] for the project's [flow] kind; a name of "none" or unset binds nothing."""
    try:
        with open(os.path.join(root, ".claude", "kit.toml"), "rb") as handle:
            cfg = relay_toml.load(handle)
    except Exception:
        return []
    out = []
    for section, key, label in (("flow", "kind", "flow"),):
        name = cfg.get(section, {}).get(key)
        if isinstance(name, str) and name not in ("", "none"):
            out.append((label, name))
    return out


def manifest(plugin, root):
    candidates = []
    try:
        out = subprocess.run([sys.executable, KIT, "path", f"{plugin}/flow.json"], cwd=root, capture_output=True, text=True, timeout=5).stdout.strip()
        if out:
            candidates.append(out)
    except Exception:
        pass
    candidates.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), plugin, "flow.json"))
    for env in (os.environ.get("RELAY_ROOT"),):
        if env:
            candidates.append(os.path.join(env, "plugins", plugin, "flow.json"))
    for path in candidates:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
    return None


def stage_for(prompt, flow):
    """The stage a prompt starts: by its first word (a slash trigger), else by a keyword
    regex over the prompt (`keywords`, the Arsenal style: `#123`, "issue", "PR")."""
    import re
    first = prompt.strip().split(None, 1)[0] if prompt.strip() else ""
    if first.startswith("/"):
        for stage in flow.get("stages", []):
            for trigger in stage.get("triggers", []):
                if first == trigger or first.startswith(trigger + ":"):
                    return stage
        return None
    for stage in flow.get("stages", []):
        for pattern in stage.get("keywords", []):
            if re.search(pattern, prompt, re.I):
                return stage
    return None


def line_for(label, stage):
    if stage.get("skill"):
        text = (f"Stage `{stage['name']}` of the {label}: load the `{stage['skill']}` skill with the Skill tool before "
                f"the first step and follow it; where it differs from a command's own text, `{stage['skill']}` wins.")
        return text + (" " + stage["note"] if stage.get("note") else "")
    return f"Stage `{stage['name']}` of the {label}: {stage['note']}"


def main():
    data = json.load(sys.stdin)
    if data.get("hook_event_name") != "UserPromptSubmit" or data.get("agent_id"):
        return
    cwd = data.get("cwd") or os.getcwd()
    root = project_root(cwd)
    for label, plugin in bindings(root):
        flow = manifest(plugin, root)
        if not flow:
            continue
        if flow.get("slot") == "specs":
            continue   # [flow] kind takes a work flow; an old [flow] kind = "openspec" binds nothing
        stage = stage_for(data.get("prompt") or "", flow)
        if not stage or not (stage.get("skill") or stage.get("note")):
            continue
        text = line_for(label, stage)
        roles = flow.get("roles")
        if roles:   # the issue flow names its roles
            text += " Roles for this flow: " + ", ".join(f"{k} -> {v}" for k, v in roles.items()) + "."
        json.dump({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}, sys.stdout)
        return


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
