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
- A prompt over 3000 characters that names no `Brief:` file gets a note: write
  a brief file; the prompt is re-read on every request of the agent.

Fails open on any error. Tests: plugins/delegate/tests/route-guard.test.sh
"""

import json
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

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
    out = {"typed_only": True, "fork_limit": 100_000, "build_tier_opus": "escalate", "max_parallel": 4}
    try:
        root = cwd or os.getcwd()
        path = os.path.join(root, ".claude", "kit.toml")
        with open(path, "rb") as handle:
            out.update(tomllib.load(handle).get("delegate", {}))
    except Exception:
        pass
    for key in ("typed_only", "fork_limit", "build_tier_opus", "max_parallel"):
        env = os.environ.get("RELAY_DELEGATE_" + key.upper())
        if env is not None:
            out[key] = env if key == "build_tier_opus" else (env.lower() == "true" if key == "typed_only" else int(env))
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
        if policy == "deny" or (policy == "escalate" and not re.search(r"(?mi)^\s*Escalated:\s*\S", prompt)):
            return deny(f"Routing: {sub} runs on the profile's model for its tier; Opus is for thinker and critic. "
                        "To escalate (a Sonnet agent failed the same task, or the project names the case), add a line "
                        "`Escalated: <reason>` to the prompt and keep the same brief.")
    notes = []
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
