#!/usr/bin/env python3
"""delegate: the routing guard. PreToolUse on the Agent tool.

Keeps small work on small models and the main session thin, by the rules in
the project's .claude/kit.toml [delegate] section (defaults in brackets):

- typed_only [true]: a `general-purpose` agent is denied when the delegate
  plugin's typed agents cover the job; the reason names them.
- fork_limit [100000]: a `fork` is denied once the session's context is above
  this many tokens (a fork inherits all of it).
- build_tier_opus ["escalate"]: a build- or look-tier agent (worker, fixer,
  scout, runner) started with `model: opus` is denied unless the prompt carries
  a line `Escalated: <reason>` (a Sonnet agent failed the same task, or the
  project names the case). "allow" lets it through; "deny" refuses always.
- max_parallel [4]: when this many agents are already running in the session
  (today's ledger), a note is added rather than a refusal.
- require_skill ["deny"]: an Agent call from the main session before the delegate
  skill was loaded is refused once ("load the delegate skill first"); the session's
  transcript shows whether the skill was loaded or the refusal was already given.
  "note" only notes it, "off" does nothing. Calls from a subagent are not checked.
- A prompt over 3000 characters that names no `Brief:` file gets a note: write
  a brief file; the prompt is re-read on every request of the agent.

Fails open on any error. Tests: plugins/delegate/tests/route-guard.test.sh
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import relay_toml  # noqa: E402

TYPED = {
    "look": "delegate:scout (read-only lookups, file:line answers)",
    "run": "delegate:runner (run a command or API call, 3-line answer)",
    "build": "delegate:worker (build from a brief file in a worktree)",
    "fix": "delegate:fixer (fix listed findings or a red check)",
    "think": "delegate:thinker (design, plan, trade-offs; writes one file)",
    "judge": "delegate:critic (adversarial review; writes findings)",
}
SMALL_TIERS = ("scout", "runner", "worker", "fixer")


def settings(cwd):
    out = {"typed_only": True, "fork_limit": 100_000, "build_tier_opus": "escalate", "max_parallel": 4, "require_skill": "deny"}
    try:
        root = cwd or os.getcwd()
        path = os.path.join(root, ".claude", "kit.toml")
        with open(path, "rb") as handle:
            out.update(relay_toml.load(handle).get("delegate", {}))
    except Exception:
        pass
    for key in ("typed_only", "fork_limit", "build_tier_opus", "max_parallel", "require_skill"):
        env = os.environ.get("RELAY_DELEGATE_" + key.upper())
        if env is not None:
            out[key] = env if key in ("build_tier_opus", "require_skill") else (env.lower() == "true" if key == "typed_only" else int(env))
    return out


def context_tokens(transcript_path):
    try:
        import relay_transcripts
        return relay_transcripts.context_tokens_of(transcript_path) or 0
    except Exception:
        return 0


def running_now(session_id):
    try:
        import relay_ledger
        import datetime as dt
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=12)
        events = relay_ledger.read(since=since)
        return len(relay_ledger.running_agents(events).get(session_id, []))
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


def deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def note(text):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}}


def decide(data):
    if data.get("tool_name") not in ("Agent", "Task"):
        return None
    cfg = settings(data.get("cwd"))
    ti = data.get("tool_input") or {}
    sub = (ti.get("subagent_type") or "general-purpose").strip()
    model = (ti.get("model") or "").lower()
    prompt = ti.get("prompt") or ""
    role = sub.split(":")[-1]

    if sub == "fork":
        tokens = context_tokens(data.get("transcript_path") or "")
        if tokens > int(cfg["fork_limit"]):
            return deny(f"Routing: this session holds about {tokens // 1000}k tokens and a fork inherits all of it "
                        f"(limit {int(cfg['fork_limit']) // 1000}k). Write what the agent needs into a brief file and start a "
                        "typed agent with `Brief: <path>`: " + "; ".join(TYPED.values()))
    if sub == "general-purpose" and cfg["typed_only"]:
        return deny("Routing: no general-purpose agents (every tool loaded, 30-35k tokens re-read on each request). "
                    "Use the typed agent for the job: " + "; ".join(TYPED.values())
                    + ". For a job none of them fits, set [delegate].typed_only = false in .claude/kit.toml.")
    if "opus" in model and role in SMALL_TIERS:
        policy = str(cfg["build_tier_opus"])
        if policy == "deny" or (policy == "escalate" and not is_escalated(prompt)):
            return deny(f"Routing: {sub} runs on the profile's model for its tier; Opus is for thinker and critic. "
                        "To escalate (a Sonnet agent failed the same task, or the project names the case), add a line "
                        "`Escalated: <reason>` to the prompt and keep the same brief.")
    notes = []
    mode = str(cfg["require_skill"])
    if mode not in ("deny", "note", "off"):
        mode = "deny"   # an unknown value takes the default
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
    if running >= int(cfg["max_parallel"]):
        notes.append(f"Routing note: {running} agents are already running in this session (cap {cfg['max_parallel']}). "
                     "Agents started together each pay a first read; let one finish or merge the jobs into one brief.")
    if notes:
        return note("\n".join(notes))
    return None


def main():
    data = json.load(sys.stdin)
    out = decide(data)
    if out:
        json.dump(out, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
