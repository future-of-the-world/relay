#!/usr/bin/env python3
"""delegate: the routing guard. PreToolUse on the Agent tool.

Keeps small work on small models and the main session thin, by the rules in
the project's .claude/kit.toml [delegate] section (defaults in brackets):

- typed_agents_only [true]: a `general-purpose` agent is denied when the delegate
  plugin's typed agents cover the job; the reason names them.
- no_session_copy_above_tokens [100000]: a `fork` is denied once the session's context is above
  this many tokens (a fork inherits all of it).
- opus_for_builders ["after_a_failure"]: a build- or look-tier agent (worker, fixer,
  scout, runner) started with `model: opus` is denied unless the prompt carries
  a line `Escalated: <reason>` (a Sonnet agent failed the same task, or the
  project names the case). "always" lets it through; "never" refuses always.
- max_agents_at_once [4]: when this many agents are already running in the session
  (today's ledger), a note is added rather than a refusal.
- require_skill ["deny"]: an Agent call from the main session before the delegate
  skill was loaded is refused once ("load the delegate skill first"); the session's
  transcript shows whether the skill was loaded or the refusal was already given.
  "note" only notes it, "off" does nothing. Calls from a subagent are not checked.
- A prompt over 3000 characters that names no `Brief:` file gets a note: write
  a brief file; the prompt is re-read on every request of the agent.

Fails open on any error. Tests: tests/test_hook_route_guard.py
"""

import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import relay_labels  # noqa: E402
import relay_kit  # noqa: E402

TYPED = {
    "look": "delegate:scout (read-only lookups, file:line answers)",
    "run": "delegate:runner (run a command or API call, 3-line answer)",
    "build": "delegate:worker (build from a brief file in a worktree)",
    "fix": "delegate:fixer (fix listed findings or a red check)",
    "think": "delegate:thinker (design, plan, trade-offs; writes one file)",
    "judge": "delegate:critic (adversarial review; writes findings)",
}
TYPED_ROLES = ("scout", "runner", "worker", "fixer", "thinker", "critic")   # the relay agents; others are not labelled work
SMALL_TIERS = ("scout", "runner", "worker", "fixer")


def project_root(cwd):
    """The git top level of the session's working folder (a worktree reads its own kit.toml), else the folder."""
    import subprocess
    cwd = cwd or os.getcwd()
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return out or cwd


def settings(cwd):
    """The [delegate] values to act on and the problems found in kit.toml and the RELAY_DELEGATE_* overrides (relay_kit)."""
    return relay_kit.delegate_settings(project_root(cwd))


def context_tokens(transcript_path):
    try:
        import relay_transcripts
        return relay_transcripts.context_tokens_of(transcript_path) or 0
    except Exception:
        return 0


def running_now(session_id: "str | None", now: "dt.datetime | None" = None) -> int:
    try:
        import relay_ledger
        now = now or dt.datetime.now(dt.timezone.utc)
        events = relay_ledger.read(since=now - dt.timedelta(hours=12))
        return len(relay_ledger.running_agents(events, now, relay_ledger.AGENT_IDLE).get(session_id, []))
    except Exception:
        return 0


def is_escalated(prompt):
    import relay_transcripts   # the ledger uses the same rule
    return relay_transcripts.is_escalated(prompt)


SKILL_DENIAL = "Routing: load the delegate skill first (brief files, who does what), then start the agent again"
SKILL_NAMES = ("delegate:delegate", "delegate")


def skill_evidence(transcript_path):
    """(loaded, refused) from the session transcript: the delegate skill was called or typed, or this guard already refused once.
    (None, None) when the transcript cannot be read: then the guard cannot tell and lets the call through."""
    try:
        with open(transcript_path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except (OSError, TypeError, ValueError):
        return None, None
    loaded = refused = False

    def walk(node):
        nonlocal loaded, refused
        if isinstance(node, dict):
            if node.get("type") == "tool_use" and node.get("name") == "Skill" and (node.get("input") or {}).get("skill") in SKILL_NAMES:
                loaded = True
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            if "load the delegate skill first" in node:
                refused = True
            if node.lstrip().startswith("/delegate:delegate") or "<command-name>/delegate:delegate</command-name>" in node:
                loaded = True

    for line in lines:
        try:
            walk(json.loads(line))
        except ValueError:
            continue
    return loaded, refused


def deny_with(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def note(text):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}}


LABEL_DENIAL = ("Routing: a relay agent started by hand needs a label at the start of its description, `<stage>[ n]: <change>`, so its time "
                "and cost join the change's record. Stages: " + ", ".join(relay_labels.STAGES) + ". Example: `build: refuse-folder-entries - "
                "short words for the person may follow after ' - '`. Work with no change: `other: <name>`.")


def metrics_on(root):
    """Where the label is demanded: a project with .relay/ whose kit.toml does not set [metrics] enabled = false."""
    if not os.path.isdir(os.path.join(root, ".relay")):
        return False
    return relay_kit.load(project_root(root)).get("metrics", "enabled")


def decide(data):
    if data.get("tool_name") not in ("Agent", "Task"):
        return None
    cfg, problems = settings(data.get("cwd"))
    extra = ""
    if problems:
        extra = " Settings note: " + "; ".join(p.line() for p in problems) + ". Fix the line; relay doctor lists every problem."

    def deny(reason):
        return deny_with(reason + extra)

    ti = data.get("tool_input") or {}
    sub = (ti.get("subagent_type") or "general-purpose").strip()
    model = (ti.get("model") or "").lower()
    prompt = ti.get("prompt") or ""
    role = sub.split(":")[-1]

    if sub == "fork":
        tokens = context_tokens(data.get("transcript_path") or "")
        if tokens > int(cfg["no_session_copy_above_tokens"]):
            return deny(f"Routing: this session holds about {tokens // 1000}k tokens and a fork inherits all of it "
                        f"(limit {int(cfg['no_session_copy_above_tokens']) // 1000}k). Write what the agent needs into a brief file and start a "
                        "typed agent with `Brief: <path>`: " + "; ".join(TYPED.values()))
    if sub == "general-purpose" and cfg["typed_agents_only"]:
        return deny("Routing: no general-purpose agents (every tool loaded, 30-35k tokens re-read on each request). "
                    "Use the typed agent for the job: " + "; ".join(TYPED.values())
                    + ". For a job none of them fits, set [delegate].typed_agents_only = false in .claude/kit.toml.")
    if "opus" in model and role in SMALL_TIERS:
        policy = cfg["opus_for_builders"]
        if policy == "never" or (policy == "after_a_failure" and not is_escalated(prompt)):
            return deny(f"Routing: {sub} runs on the profile's model for its tier; Opus is for thinker and critic. "
                        "To escalate (a Sonnet agent failed the same task, or the project names the case), add a line "
                        "`Escalated: <reason>` to the prompt and keep the same brief.")
    guard = str(cfg["label_guard"])
    notes = []
    if guard in ("deny", "note") and role in TYPED_ROLES and not relay_labels.label_of(ti.get("description") or "") \
            and metrics_on(data.get("cwd") or os.getcwd()):
        if guard == "deny":
            return deny(LABEL_DENIAL)
        notes.append("Routing note: " + LABEL_DENIAL[len("Routing: "):])
    mode = str(cfg["require_skill"])
    if mode != "off" and not data.get("agent_id") and sub != "general-purpose":
        loaded, refused = skill_evidence(data.get("transcript_path") or "")
        if loaded is False:
            if mode == "deny" and not refused:
                return deny(SKILL_DENIAL)
            notes.append("Routing note: the delegate skill was not loaded in this session; load it for the brief file and the routing table.")
    if len(prompt) > 3000 and not re.search(r"(?mi)^\s*Brief:\s*\S", prompt):
        notes.append(f"Routing note: this prompt is {len(prompt)} characters and names no `Brief:` file. The agent re-reads "
                     "its prompt on every request; put the material in a brief file in the scratchpad and pass its path.")
    running = running_now(data.get("session_id"))
    if running >= int(cfg["max_agents_at_once"]):
        notes.append(f"Routing note: {running} agents are already running in this session (cap {cfg['max_agents_at_once']}). "
                     "Agents started together each pay a first read; let one finish or merge the jobs into one brief.")
    if extra:
        notes.append(extra.strip())
    if notes:
        return note("\n".join(notes))
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return   # not an event: nothing to guard
    try:
        out = decide(data)
    except Exception as exc:   # fails open, but says why: a guard that silently allows everything is one nobody knows is off
        out = note(f"Routing note: the routing guard crashed and allowed this call ({type(exc).__name__}: {exc}).")
    if out:
        json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
    sys.exit(0)
