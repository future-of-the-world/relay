"""From transcripts and the ledger to a report: where the money went, and what to change.

`collect(claude_dir, since, until)` reads every session touched in the period
and its subagents. `report(data)` renders tables; `findings(data)` lists
measured anti-patterns with the lever that fixes each (a profile key or a
rule), so `relay improve suggest` can print them as numbered choices.
"""

import datetime as dt
import os
from collections import defaultdict

import relay_ledger
import relay_prices
import relay_transcripts as tr

BUILD_WORDS = ("worker", "fixer", "builder", "apply", "implement", "build")
LOOK_WORDS = ("scout", "explore", "runner", "status", "lookup")


def classify(agent_type):
    """build | look | think | general | fork | other, from an agent type's name."""
    name = (agent_type or "").lower()
    if not name or name == "general-purpose":
        return "general"
    if name == "fork":
        return "fork"
    if any(w in name for w in BUILD_WORDS):
        return "build"
    if any(w in name for w in LOOK_WORDS):
        return "look"
    if any(w in name for w in ("review", "critic", "thinker", "author", "plan", "design", "spec")):
        return "think"
    return "other"


def _ts(value):
    return relay_ledger.parse_ts(value) if value else None


def collect(claude_dir, since=None, until=None, session_ids=None):
    since_m = since.timestamp() if since else 0.0
    paths = tr.find_sessions(claude_dir, since_mtime=since_m)
    sessions = []
    for path in paths:
        sid = os.path.basename(path)[:-len(".jsonl")]
        if session_ids and sid not in session_ids:
            continue
        main = tr.read_trace(path, kind="session")
        main.session_id = main.session_id or sid
        if until and _ts(main.started) and _ts(main.started) > until:
            continue
        if since and _ts(main.ended) and _ts(main.ended) < since:
            continue
        if main.total.requests == 0:
            continue
        agents = tr.session_agents(path)
        sessions.append({"main": main, "agents": agents, "path": path})
    return {"sessions": sessions, "since": since, "until": until}


def _sum_agg(aggs):
    out = tr.Agg()
    for a in aggs:
        out.requests += a.requests
        for k in tr.USAGE_KEYS:
            out.usage[k] += a.usage[k]
        out.cost += a.cost
    return out


def totals(data):
    mains = [s["main"] for s in data["sessions"]]
    agents = [a for s in data["sessions"] for a in s["agents"]]
    by_model = defaultdict(list)
    for t in mains + agents:
        for model, agg in t.by_model.items():
            by_model[model].append(agg)
    by_type = defaultdict(list)
    for a in agents:
        by_type[a.agent_type or "general-purpose"].append(a)
    return {
        "sessions": len(mains),
        "agents": len(agents),
        "main": _sum_agg([m.total for m in mains]),
        "agents_total": _sum_agg([a.total for a in agents]),
        "by_model": {m: _sum_agg(v) for m, v in by_model.items()},
        "by_type": by_type,
        "user_turns": sum(m.user_turns for m in mains),
        "reply_chars": sum(m.reply_chars for m in mains),
        "prompt_chars": sum(m.prompt_chars for m in mains),
        "long_prompts": sum(m.long_prompts for m in mains),
        "compactions": sum(m.compactions for m in mains),
    }


def _money(x):
    return f"${x:,.2f}"


def _k(n):
    return f"{n/1000:,.0f}k" if n >= 1000 else str(n)


def _table(rows, headers):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    out = [line, "  ".join("-" * w for w in widths)]
    for row in rows:
        out.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)))
    return "\n".join(out)


def report(data, title="Usage"):
    t = totals(data)
    grand = t["main"].cost + t["agents_total"].cost
    lines = [f"# {title}", ""]
    span = ""
    if data.get("since"):
        span = f"from {data['since'].strftime('%Y-%m-%d %H:%M')}"
    if data.get("until"):
        span += f" to {data['until'].strftime('%Y-%m-%d %H:%M')}"
    lines.append(f"{t['sessions']} sessions, {t['agents']} agents, {t['user_turns']} of your turns {span}".strip())
    lines.append(f"Estimated cost {_money(grand)} (prices.toml, measured {relay_prices.table().get('measured')}): "
                 f"main sessions {_money(t['main'].cost)}, agents {_money(t['agents_total'].cost)}"
                 + (f" ({t['agents_total'].cost/grand*100:.0f}%)" if grand else ""))
    if t["user_turns"]:
        lines.append(f"Per turn of yours: {_money(grand / t['user_turns'])}; "
                     f"reply length {t['reply_chars'] // t['user_turns']:,} characters on average; "
                     f"your prompts {t['prompt_chars'] // t['user_turns']:,} characters on average, {t['long_prompts']} over 600")
    lines.append(f"Compactions: {t['compactions']}")
    lines.append("")
    lines.append("## By model")
    rows = []
    for model, agg in sorted(t["by_model"].items(), key=lambda kv: -kv[1].cost):
        u = agg.usage
        rows.append([model, agg.requests, _k(u["cache_read_input_tokens"]), _k(u["cache_creation_input_tokens"]),
                     _k(u["input_tokens"]), _k(u["output_tokens"]), _money(agg.cost)])
    lines.append(_table(rows, ["model", "requests", "cache read", "cache write", "input", "output", "cost"]))
    lines.append("")
    lines.append("## By agent type")
    rows = []
    for kind, agents in sorted(t["by_type"].items(), key=lambda kv: -sum(a.total.cost for a in kv[1])):
        agg = _sum_agg([a.total for a in agents])
        models = ",".join(sorted({relay_prices.tier(m) for a in agents for m in a.models})) or "?"
        avg_ctx = sum(a.max_context for a in agents) // max(len(agents), 1)
        rows.append([kind, len(agents), models, agg.requests, _k(avg_ctx), _money(agg.cost),
                     f"{agg.cost/grand*100:.0f}%" if grand else "-"])
    lines.append(_table(rows, ["agent", "count", "models", "requests", "avg max context", "cost", "share"]))
    lines.append("")
    lines.append("## Sessions")
    rows = []
    for s in sorted(data["sessions"], key=lambda s: -(s["main"].total.cost + sum(a.total.cost for a in s["agents"])))[:15]:
        m = s["main"]
        cost = m.total.cost + sum(a.total.cost for a in s["agents"])
        rows.append([m.session_id[:8], os.path.basename(m.cwd or "?"), (m.started or "")[:16], m.user_turns,
                     len(s["agents"]), _k(m.max_context), m.compactions, _money(cost)])
    lines.append(_table(rows, ["session", "project", "started", "turns", "agents", "max context", "compact", "cost"]))
    return "\n".join(lines)


def findings(data):
    """Measured anti-patterns. Each: dict(id, title, evidence, saving_usd, lever)."""
    out = []
    agents = [a for s in data["sessions"] for a in s["agents"]]
    mains = [s["main"] for s in data["sessions"]]
    rates = relay_prices.table()["models"]

    # F1: build-class agents on Opus
    opus_build = [a for a in agents if classify(a.agent_type) == "build" and relay_prices.tier(a.model) == "opus"]
    if opus_build:
        cost = sum(a.total.cost for a in opus_build)
        as_sonnet = sum(relay_prices.cost("sonnet", a.total.usage) for a in opus_build)
        out.append({
            "id": "F1", "title": "Build agents ran on Opus",
            "evidence": f"{len(opus_build)} agents ({', '.join(sorted({a.agent_type for a in opus_build}))}), {_money(cost)}",
            "saving_usd": cost - as_sonnet,
            "lever": "profile: [models].build = \"sonnet\"; delegate hook build_tier_opus = \"escalate\"",
        })

    # F2: general-purpose agents (every tool loaded: 30-35k first read vs 10-17k)
    gp = [a for a in agents if classify(a.agent_type) == "general"]
    if gp:
        extra_tokens = sum(a.total.requests for a in gp) * 20_000
        saving = extra_tokens * rates["default"]["cache_read"] / 1_000_000
        out.append({
            "id": "F2", "title": "general-purpose agents (carry every tool, re-read on every request)",
            "evidence": f"{len(gp)} agents, {sum(a.total.requests for a in gp)} requests, {_money(sum(a.total.cost for a in gp))}",
            "saving_usd": saving,
            "lever": "delegate hook typed_only = true; give the role to delegate:scout/worker/runner",
        })

    # F3: forks from big sessions
    forks = sum(m.agents_started.get("fork", 0) for m in mains)
    if forks:
        out.append({
            "id": "F3", "title": "Forks (a fork inherits the whole conversation)",
            "evidence": f"{forks} forks started", "saving_usd": 0.0,
            "lever": "delegate hook fork_limit (default 100k): write a brief file and start a typed agent",
        })

    # F4: sessions over the context line
    big = [m for m in mains if m.max_context > 400_000]
    if big:
        out.append({
            "id": "F4", "title": "Sessions above 400k context",
            "evidence": f"{len(big)} sessions, largest {_k(max(m.max_context for m in big))}",
            "saving_usd": sum(m.total.cost for m in big) * 0.25,
            "lever": "front: handover at 350k and a fresh session per change (front plugin budget.py)",
        })

    # F5: agents that lost their cache (pause > 5 min between requests)
    stale = [a for a in agents if a.gaps_over_5m > 0]
    if stale:
        rewrite = sum(a.total.usage["cache_creation_input_tokens"] for a in stale)
        out.append({
            "id": "F5", "title": "Agents that waited over 5 minutes and re-paid their context",
            "evidence": f"{len(stale)} agents, {sum(a.gaps_over_5m for a in stale)} pauses, {_k(rewrite)} tokens written to cache",
            "saving_usd": rewrite * (rates["sonnet"]["cache_write"] - rates["sonnet"]["cache_read"]) / 1_000_000,
            "lever": "rules/delegation.md: a waiter is a session, not an agent; no command over 4 minutes",
        })

    # F6: many tiny agents (each pays a first read)
    tiny = [a for a in agents if 0 < a.total.requests <= 3]
    if len(tiny) >= 10:
        first_reads = sum(a.first_read for a in tiny)
        out.append({
            "id": "F6", "title": "Many short agents (each pays its first read of CLAUDE.md + brief + code)",
            "evidence": f"{len(tiny)} agents with 3 requests or fewer; first reads {_k(first_reads)} tokens",
            "saving_usd": first_reads * 0.5 * rates["sonnet"]["cache_write"] / 1_000_000,
            "lever": "rules/delegation.md: one agent, one brief, a group of tasks per agent; batch lookups into one scout",
        })

    # F7: compactions
    compactions = sum(m.compactions for m in mains)
    if compactions:
        out.append({
            "id": "F7", "title": "Compactions (every later turn re-reads what survived)",
            "evidence": f"{compactions} compactions in {len(mains)} sessions", "saving_usd": 0.0,
            "lever": "front: one session per change; handover file at 350k",
        })

    # F8: front noise: long replies
    turns = sum(m.user_turns for m in mains)
    if turns:
        avg = sum(m.reply_chars for m in mains) / turns
        if avg > 2500:
            out.append({
                "id": "F8", "title": "Long replies in the main session",
                "evidence": f"{avg:,.0f} characters per turn on average (target under 1,500)", "saving_usd": 0.0,
                "lever": "rules/front.md: one screen per reply; detail goes to a report file the user can open",
            })
    # F9: long prompts from the owner: what repeats belongs in the setup
    if turns:
        avg_prompt = sum(m.prompt_chars for m in mains) / turns
        long_n = sum(m.long_prompts for m in mains)
        if avg_prompt > 300 or long_n >= 3:
            out.append({
                "id": "F9", "title": "Long prompts from you (a good setup takes short ones)",
                "evidence": f"{avg_prompt:,.0f} characters per prompt on average, {long_n} prompts over 600 characters",
                "saving_usd": 0.0,
                "lever": "what you keep writing belongs in the setup: a rule (rules/), a project addition (.claude/kit/<role>.md), "
                         "a skill, or a bench scenario; the front skill asks to fold a long prompt in",
            })
    out.sort(key=lambda f: -f["saving_usd"])
    return out


def compare(a, b, label_a="A", label_b="B"):
    """Two collected periods side by side, normalised per user turn."""
    ta, tb = totals(a), totals(b)

    def row(name, fa, fb, fmt=lambda x: f"{x:,.2f}"):
        da = fa(ta)
        db = fb(tb)
        delta = db - da
        sign = "+" if delta >= 0 else ""
        return [name, fmt(da), fmt(db), f"{sign}{fmt(delta)}"]

    def per_turn(t, key):
        turns = max(t["user_turns"], 1)
        return (t["main"].cost + t["agents_total"].cost) / turns if key == "cost" else t[key] / turns

    rows = [
        row("sessions", lambda t: t["sessions"], lambda t: t["sessions"], str),
        row("your turns", lambda t: t["user_turns"], lambda t: t["user_turns"], str),
        row("agents", lambda t: t["agents"], lambda t: t["agents"], str),
        row("cost total $", lambda t: t["main"].cost + t["agents_total"].cost, lambda t: t["main"].cost + t["agents_total"].cost),
        row("cost per turn $", lambda t: per_turn(t, "cost"), lambda t: per_turn(t, "cost")),
        row("agent share %", lambda t: (t["agents_total"].cost / max(t["main"].cost + t["agents_total"].cost, 1e-9)) * 100,
            lambda t: (t["agents_total"].cost / max(t["main"].cost + t["agents_total"].cost, 1e-9)) * 100, lambda x: f"{x:.0f}"),
        row("reply chars per turn", lambda t: t["reply_chars"] / max(t["user_turns"], 1), lambda t: t["reply_chars"] / max(t["user_turns"], 1), lambda x: f"{x:,.0f}"),
        row("your prompt chars per turn", lambda t: t["prompt_chars"] / max(t["user_turns"], 1), lambda t: t["prompt_chars"] / max(t["user_turns"], 1), lambda x: f"{x:,.0f}"),
        row("prompts over 600 chars", lambda t: t["long_prompts"], lambda t: t["long_prompts"], str),
        row("compactions", lambda t: t["compactions"], lambda t: t["compactions"], str),
    ]
    for tier_name in ("opus", "sonnet", "haiku"):
        def share(t, tier_name=tier_name):
            total = sum(agg.cost for agg in t["by_model"].values()) or 1e-9
            return sum(agg.cost for m, agg in t["by_model"].items() if relay_prices.tier(m) == tier_name) / total * 100
        rows.append(row(f"{tier_name} share of cost %", share, share, lambda x: f"{x:.0f}"))
    return _table(rows, ["measure", label_a, label_b, "delta"])


def status(events, claude_dir):
    """What is running now, from today's ledger: one line per session."""
    running = relay_ledger.running_agents(events)
    last_seen = {}
    cwd_of = {}
    for e in events:
        last_seen[e.get("session_id")] = e.get("ts")
        if e.get("cwd"):
            cwd_of.setdefault(e.get("session_id"), e.get("cwd"))
    rows = []
    now = dt.datetime.now(dt.timezone.utc)
    for sid, ts in sorted(last_seen.items(), key=lambda kv: kv[1] or "", reverse=True)[:10]:
        when = relay_ledger.parse_ts(ts)
        age = f"{(now - when).total_seconds()/60:.0f} min ago" if when else "?"
        agents = running.get(sid, [])
        names = ", ".join(sorted({a.get("agent_type") or "general-purpose" for a in agents})) or "-"
        path = tr.session_path_for(claude_dir, sid) if sid else None
        ctx = tr.context_tokens_of(path) if path else None
        rows.append([(sid or "?")[:8], os.path.basename(cwd_of.get(sid) or "?"), age, _k(ctx) if ctx else "?", len(agents), names])
    return _table(rows, ["session", "project", "last activity", "context", "running", "agents"])
