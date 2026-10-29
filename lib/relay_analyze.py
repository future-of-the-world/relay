# size: over the 600-line limit until its split item lands
"""From transcripts and the ledger to a report: where the money went, and what to change.

`collect(claude_dir, since, until)` reads every session touched in the period
and its subagents. `report(data)` renders tables; `findings(data)` lists
measured anti-patterns with the lever that fixes each (a profile key or a
rule), so `relay improve suggest` can print them as numbered choices.
"""

import datetime as dt
import os
import statistics
from collections import defaultdict
from typing import Any

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


# Owner decision 24 Oct / 28 Oct: the front keeps Opus; numbers only, no flag and no target. Overspending is relative: the
# figure to watch is the main sessions' share of the cost and their requests per owner turn, expected to fall over time.

def _front_sessions(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Sessions the owner talked to: a program-started (headless, eval, bench) session is no front, and its
    turns are zeroed, so its requests must not count against the owner's turns."""
    return [s for s in data["sessions"] if not s["main"].scripted]


def _front_mains(data: dict[str, Any]) -> list[Any]:
    return [s["main"] for s in _front_sessions(data)]


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
        for a in agents:
            a.escalated = bool(main.agent_briefs.get(a.agent_id, {}).get("escalated"))
        sessions.append({"main": main, "agents": agents, "path": path})
    records = relay_ledger.exact_records()
    return {"sessions": sessions, "since": since, "until": until,
            "exact": {sid: models for sid, (_when, models) in records.items()},
            "exact_at": {sid: when for sid, (when, _models) in records.items()}}


def _exact_usage(numbers):
    return {
        "input_tokens": int(numbers.get("input_tokens", 0)),
        "output_tokens": int(numbers.get("output_tokens", 0)),
        "cache_read_input_tokens": int(numbers.get("cache_read_input_tokens", 0)),
        "cache_creation_input_tokens": int(numbers.get("cache_creation_input_tokens", 0)),
        "web_search_requests": int(numbers.get("web_search_requests", 0)),
    }


def _covers(session, written):
    """True when a total written at `written` is later than everything the session did (a resumed session's
    earlier total does not cover its later work). No tolerance: any later line, even a second later, may carry
    new usage. Unknown times count as covering."""
    if written is None:
        return True
    ends = [_ts(t.ended) for t in [session["main"]] + session["agents"] if t.ended]
    ends = [e for e in ends if e]
    return not ends or max(ends) <= written


def session_figures(session, exact_map, exact_at=None):
    """Per-model tokens and cost of one session, and whether they are exact.

    exact: Claude Code's own totals for the session (what /cost showed), when they were captured and
    written after the session's last activity.
    estimate: the transcripts, whose agent output is a snapshot (so estimated), plus the helper
    requests Claude Code makes that have no transcript (agents' cost x the helper uplift)."""
    main, agents = session["main"], session["agents"]
    transcript_cost = main.total.cost + sum(a.total.cost for a in agents)
    requests = defaultdict(int)
    for trace in [main] + agents:
        for model, agg in trace.by_model.items():
            requests[model] += agg.requests
    exact = exact_map.get(main.session_id)
    if exact and not _covers(session, (exact_at or {}).get(main.session_id)):
        exact = None        # the session went on after Claude Code wrote this total: estimate until it is written again
    models = {}
    if exact:
        for model, numbers in exact.items():
            usage = _exact_usage(numbers)
            cost = numbers["cost_usd"] if "cost_usd" in numbers else relay_prices.cost(model, usage)
            models[model] = {"requests": requests.get(model, 0), "usage": usage, "cost": cost}
        total = sum(m["cost"] for m in models.values())
        return {"label": "exact", "cost": total, "models": models, "transcript_cost": transcript_cost,
                "helpers": max(0.0, total - transcript_cost)}
    uplift = relay_prices.helper_uplift()
    for trace, weight in [(main, 1.0)] + [(a, uplift) for a in agents]:
        for model, agg in trace.by_model.items():
            row = models.setdefault(model, {"requests": 0, "usage": {k: 0 for k in tr.USAGE_KEYS}, "cost": 0.0})
            row["requests"] += agg.requests
            for k in tr.USAGE_KEYS:
                row["usage"][k] += agg.usage[k]
            row["cost"] += agg.cost * weight
    total = sum(m["cost"] for m in models.values())
    return {"label": "estimate", "cost": total, "models": models, "transcript_cost": transcript_cost, "helpers": 0.0}


def calibration_path():
    import relay_config
    return os.path.join(relay_config.home_dir(), "calibration.json")


def load_calibration():
    """What the last `relay calibrate` measured (None when it never ran)."""
    import json
    try:
        with open(calibration_path(), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _save_calibration(data):
    import json
    os.makedirs(os.path.dirname(calibration_path()), exist_ok=True)
    with open(calibration_path(), "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)


def _spread(errors):
    """{n, median, worst, over_10}: absolute relative errors (median and worst), sessions more than 10% off."""
    absolute = [abs(e) for e in errors]
    return {"n": len(errors), "median": statistics.median(absolute), "worst": max(absolute),
            "worst_signed": max(errors, key=abs), "over_10": sum(1 for e in absolute if e > 0.10)}


def price_error(model, numbers, main, agents):
    """(signed relative error of priced tokens against Claude Code's cost, basis) for one model of a session.
    basis 'transcript': cache writes split at the session's own 1-hour share (from its transcripts' usage);
    'band': no transcript, the distance to the range between all-5-minute and all-1-hour writes."""
    cost = numbers["cost_usd"]
    usage = _exact_usage(numbers)
    written = usage["cache_creation_input_tokens"]
    created = one_hour = reads = early_reads = 0
    for trace in ([main] + agents if main else []):
        agg = trace.by_model.get(model)
        if agg:
            created += agg.usage["cache_creation_input_tokens"]
            one_hour += agg.one_hour
            reads += agg.usage["cache_read_input_tokens"]
            early_reads += agg.early_reads
    early = early_reads / reads if reads else 0.0     # the part of the reads priced at the model's earlier rate
    if created:
        priced = relay_prices.cost(model, dict(usage, cache_creation={"ephemeral_1h_input_tokens": round(written * one_hour / created)}), early)
        return (priced - cost) / cost, "transcript"
    # no transcript: when is unknown, so a model with an earlier price may have been all earlier (the high end)
    unknown = main is None and relay_prices.has_earlier(model)
    low = relay_prices.cost(model, usage, early)
    high = relay_prices.cost(model, dict(usage, cache_creation={"ephemeral_1h_input_tokens": written}), 1.0 if unknown else early)
    if cost < low:
        return (low - cost) / cost, "band"
    if cost > high:
        return (high - cost) / cost, "band"
    return 0.0, "band"


def calibrate(claude_dir, now):
    """Backfill the ledger from Claude Code's own per-session totals, then compare them with what the
    transcripts and prices.toml give; store what was measured (relay shows it beside every estimate).
    Returns the text to print."""
    written = relay_ledger.capture(now)
    records = relay_ledger.exact_records()
    sessions = [(sid, models) for sid, (_when, models) in sorted(records.items())]
    skipped = 0
    per_model = defaultdict(lambda: defaultdict(float))
    ratios = defaultdict(list)
    uplifts = []
    errors = defaultdict(list)
    bases = defaultdict(lambda: defaultdict(int))
    est_with, est_without = [], []
    used = 0
    for sid, models in sessions:
        path = tr.session_path_for(claude_dir, sid)
        main = tr.read_trace(path) if path else None
        agents = tr.session_agents(path) if path else []
        if path and not _covers({"main": main, "agents": agents}, records[sid][0]):
            skipped += 1        # the session went on after this total was written: it would measure the estimate against a stale figure
            continue
        for model, numbers in models.items():
            if numbers.get("cost_usd", 0) > 0:
                err, basis = price_error(model, numbers, main, agents)
                errors[relay_prices.tier(model)].append(err)
                bases[relay_prices.tier(model)][basis] += 1
        if not path:
            continue
        used += 1
        for model, numbers in models.items():
            row = per_model[relay_prices.tier(model)]
            row["sessions"] += 1
            row["exact_out"] += numbers.get("output_tokens", 0)
            row["exact_cost"] += numbers.get("cost_usd", 0.0)
            for trace in [main] + agents:
                agg = trace.by_model.get(model)
                if agg:
                    row["tr_out"] += agg.usage["output_tokens"]
                    row["tr_cost"] += agg.cost
            agent_chars = sum(a.chars_by_model.get(model, 0) for a in agents)
            agent_reqs = sum(a.by_model[model].requests for a in agents if model in a.by_model)
            if agent_reqs >= 5 and agent_chars:
                rest = numbers.get("output_tokens", 0) - (main.by_model[model].usage["output_tokens"] if model in main.by_model else 0)
                ratios[relay_prices.family(model)].append(rest / agent_chars)
        agent_cost = sum(a.total.cost for a in agents)
        total = sum(n.get("cost_usd", 0.0) for n in models.values())
        if agent_cost > 0 and total > main.total.cost:
            uplifts.append((total - main.total.cost) / agent_cost)
        if total > 0:
            guess = session_figures({"main": main, "agents": agents}, {})["cost"]
            (est_with if agents else est_without).append((guess - total) / total)
    lines = [f"Claude Code's own totals: {len(sessions)} sessions ({relay_config_json()} and the ledger), {len(written)} newly copied "
             f"into the ledger, {used} with a transcript on this machine, {skipped} skipped (not covered: the session went on after the total).", ""]
    rows = []
    for key, row in sorted(per_model.items()):
        rows.append([key, int(row["sessions"]), _k(int(row["exact_out"])), _k(int(row["tr_out"])), _money(row["exact_cost"]),
                     _money(row["tr_cost"]), f"{(row['tr_cost'] - row['exact_cost']) / row['exact_cost'] * 100:+.0f}%" if row["exact_cost"] else "-"])
    lines.append(_table(rows, ["model", "sessions", "output exact", "output transcripts", "cost exact", "cost transcripts (est.)", "gap"]))
    lines.append("")
    tolerance = relay_prices.calibration_tolerance()
    lines.append(f"Prices (prices.toml, measured {relay_prices.table().get('measured')}) applied to Claude Code's tokens against its cost, per model "
                 f"(cache writes split at the session's own 1-hour share from its transcripts; 'band' = no transcript, distance to the 5-minute..1-hour range):")
    stored = {}
    for key, errs in sorted(errors.items()):
        sp = _spread(errs)
        basis = ", ".join(f"{n} {name}" for name, n in sorted(bases[key].items()))
        stored[key] = dict(sp, basis=dict(bases[key]))
        warn = []
        if sp["median"] > tolerance:
            warn.append(f"median above the {tolerance * 100:.1f}% tolerance, re-measure prices.toml")
        if sp["over_10"]:
            warn.append(f"{sp['over_10']} of {sp['n']} sessions more than 10% off")
        lines.append(f"  {key}: median {sp['median'] * 100:.2f}%, worst {sp['worst_signed'] * 100:+.1f}%, {sp['over_10']} of {sp['n']} over 10% off ({basis})"
                     + (f"  WARNING: {'; '.join(warn)}" if warn else ""))
    lines.append("")
    lines.append("The estimate (transcripts only, no Claude Code total) against Claude Code's total, per session:")
    estimate = {}
    for name, errs in (("with_agents", est_with), ("without_agents", est_without)):
        if errs:
            sp = _spread(errs)
            estimate[name] = sp
            lines.append(f"  {name.replace('_', ' ')}: median {sp['median'] * 100:.1f}%, worst {sp['worst_signed'] * 100:+.1f}%, "
                         f"{sp['over_10']} of {sp['n']} over 10% off")
    lines.append("")
    lines.append("Fitted settings for prices.toml [estimate] (sessions with 5+ agent requests on the model):")
    for key, vals in sorted(ratios.items()):
        lines.append(f"  output_per_char.{key} = {statistics.median(vals):.2f}  (now {relay_prices.output_per_char(key):.2f}; {len(vals)} sessions, range {min(vals):.2f}-{max(vals):.2f})")
    if uplifts:
        lines.append(f"  helper_uplift = {statistics.median(uplifts):.2f}  (now {relay_prices.helper_uplift():.2f}; {len(uplifts)} sessions with agents)")
    _save_calibration({"measured": now[:10] if isinstance(now, str) else str(now)[:10], "sessions": len(sessions),
                       "prices": stored, "estimate": estimate})
    return "\n".join(lines)


def known_error_sentence():
    """The error printed beside an estimate: from the last `relay calibrate`, or an honest 'not measured'."""
    not_yet = "Known error: not measured yet; run relay calibrate."
    cal = load_calibration()
    try:
        est = cal.get("estimate") if isinstance(cal, dict) else None
        if isinstance(est, dict) and not est and cal.get("measured"):
            return f"Known error: relay calibrate ran on {cal['measured']}, but no session had both a transcript and a total to measure."
        if not est:
            return not_yet
        parts = []
        for name, label in (("with_agents", "sessions with agents"), ("without_agents", "sessions without agents")):
            sp = est.get(name)
            if sp:
                parts.append(f"{label}: median {sp['median'] * 100:.0f}%, worst {abs(sp['worst_signed']) * 100:.0f}% "
                             f"{'low' if sp['worst_signed'] < 0 else 'high'}, {sp['over_10']} of {sp['n']} over 10% off")
        if not parts:
            return not_yet
        return f"Known error (measured {cal.get('measured')} against Claude Code's totals): " + "; ".join(parts) + "."
    except (KeyError, TypeError, AttributeError, ValueError):
        return not_yet      # a file of another shape (older or newer fields): treat as not measured


def relay_config_json():
    import relay_config
    return relay_config.claude_json()


def _sum_agg(aggs):
    out = tr.Agg()
    for a in aggs:
        out.requests += a.requests
        for k in tr.USAGE_KEYS:
            out.usage[k] += a.usage[k]
        out.cost += a.cost
    return out


def front_cost_by_day(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The front's (main sessions') cost per UTC day, by the rule `report` uses for "Main sessions' share of cost": the transcript cost of
    the interactive sessions' main threads (`front_cost` in totals). basis is "exact" when every session of the day has Claude Code's own
    total written after its last activity (session_figures), else "estimate", as `report` labels a session."""
    days: dict[str, dict[str, Any]] = {}
    for session in _front_sessions(data):
        label = session_figures(session, data.get("exact") or {}, data.get("exact_at"))["label"]
        for day, cost in session["main"].cost_by_day.items():
            row = days.setdefault(day, {"cost_usd": 0.0, "sessions": 0, "basis": "exact"})
            row["cost_usd"] += cost
            row["sessions"] += 1
            if label != "exact":
                row["basis"] = "estimate"
    return days


def totals(data: dict[str, Any]) -> dict[str, Any]:
    mains = [s["main"] for s in data["sessions"]]
    agents = [a for s in data["sessions"] for a in s["agents"]]
    figures = [session_figures(s, data.get("exact") or {}, data.get("exact_at")) for s in data["sessions"]]
    by_model: dict[str, Any] = {}
    basis = defaultdict(set)
    for fig in figures:
        for model, row in fig["models"].items():
            agg = by_model.setdefault(model, tr.Agg())
            agg.requests += row["requests"]
            for k in tr.USAGE_KEYS:
                agg.usage[k] += row["usage"][k]
            agg.cost += row["cost"]
            basis[model].add(fig["label"])
    exact_figs = [f for f in figures if f["label"] == "exact"]
    estimate_figs = [f for f in figures if f["label"] == "estimate"]
    by_type = defaultdict(list)
    for a in agents:
        by_type[a.agent_type or "general-purpose"].append(a)
    return {
        "sessions": len(mains),
        "agents": len(agents),
        "main": _sum_agg([m.total for m in mains]),
        "agents_total": _sum_agg([a.total for a in agents]),
        "by_model": by_model,
        "basis": basis,
        "grand": sum(f["cost"] for f in figures),
        "exact_cost": sum(f["cost"] for f in exact_figs),
        "estimate_cost": sum(f["cost"] for f in estimate_figs),
        "exact_sessions": len(exact_figs),
        "helpers": sum(f["helpers"] for f in exact_figs),
        "figures": figures,
        "by_type": by_type,
        "user_turns": sum(m.user_turns for m in mains),
        "front_requests": sum(m.total.requests for m in _front_mains(data)),
        "front_tool_calls": sum(sum(m.tools.values()) for m in _front_mains(data)),
        # interactive sessions only (a scripted run is no front): main cost and main + agents cost, transcript estimates
        "front_cost": sum(s["main"].total.cost for s in _front_sessions(data)),
        "interactive_cost": sum(s["main"].total.cost + sum(a.total.cost for a in s["agents"])
                                for s in data["sessions"] if not s["main"].scripted),
        "scripted_sessions": sum(1 for m in mains if m.scripted),
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


def report(data: dict[str, Any], title: str = "Usage") -> str:
    t = totals(data)
    grand = t["grand"]
    lines = [f"# {title}", ""]
    span = ""
    if data.get("since"):
        span = f"from {data['since'].strftime('%Y-%m-%d %H:%M')}"
    if data.get("until"):
        span += f" to {data['until'].strftime('%Y-%m-%d %H:%M')}"
    lines.append(f"{t['sessions']} sessions, {t['agents']} agents, {t['user_turns']} of your turns {span}".strip())
    if t.get("scripted_sessions"):
        lines.append(f"{t['scripted_sessions']} scripted sessions (started by a program: headless runs, benchmarks, evals); "
                     f"their prompts are not counted as your turns")
    exact_share = t["exact_cost"] / grand * 100 if grand else 0
    lines.append(f"Cost {_money(grand)} in notional dollars (list prices, prices.toml measured "
                 f"{relay_prices.table().get('measured')}; your plan is a subscription): exact for {exact_share:.0f}% of usage "
                 f"({t['exact_sessions']} of {t['sessions']} sessions, Claude Code's own totals {_money(t['exact_cost'])}), "
                 f"estimate for the rest ({_money(t['estimate_cost'])})")
    if t["sessions"] > t["exact_sessions"]:
        lines.append(f"  The estimate counts agents' output from what the transcript shows and adds {relay_prices.helper_uplift():.2f}x "
                     f"on agents for Claude Code's own helper requests. {known_error_sentence()} "
                     f"Exact figures are copied from Claude Code when a session closes or at the next session start in the same folder (a session that went on after its total was written stays an estimate).")
    if t["exact_sessions"]:
        lines.append(f"  Claude Code helpers (no transcript), exact sessions only: {_money(t['helpers'])}")
    lines.append(f"  Transcripts explain: main sessions {_money(t['main'].cost)}, agents {_money(t['agents_total'].cost)} "
                 f"(agent output estimated)"
                 + (f" ({t['agents_total'].cost/(t['main'].cost + t['agents_total'].cost)*100:.0f}% agents)" if t['main'].cost + t['agents_total'].cost else ""))
    if t["user_turns"]:
        lines.append(f"Per turn of yours: {_money(grand / t['user_turns'])}; "
                     f"reply length {t['reply_chars'] // t['user_turns']:,} characters on average; "
                     f"your prompts {t['prompt_chars'] // t['user_turns']:,} characters on average, {t['long_prompts']} over 600")
        lines.append(f"Front (main session) per turn of yours: {t['front_requests'] / t['user_turns']:.1f} requests, "
                     f"{t['front_tool_calls'] / t['user_turns']:.1f} tool calls")
    if t["interactive_cost"]:
        lines.append(f"Main sessions' share of cost: {t['front_cost'] / t['interactive_cost'] * 100:.0f}% "
                     f"({_money(t['front_cost'])} of {_money(t['interactive_cost'])}, interactive sessions and their agents)")
    lines.append(f"Compactions: {t['compactions']}")
    lines.append("")
    lines.append("## By model")
    rows = []
    for model, agg in sorted(t["by_model"].items(), key=lambda kv: -kv[1].cost):
        u = agg.usage
        label = "/".join(sorted(t["basis"][model]))
        rows.append([model, agg.requests, _k(u["cache_read_input_tokens"]), _k(u["cache_creation_input_tokens"]),
                     _k(u["input_tokens"]), _k(u["output_tokens"]), _money(agg.cost), label])
    lines.append(_table(rows, ["model", "requests", "cache read", "cache write", "input", "output", "cost", "basis"]))
    lines.append("")
    lines.append("## By agent type (estimate: no agent's own total exists; helpers not included)")
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
    paired = sorted(zip(data["sessions"], t["figures"]), key=lambda p: -p[1]["cost"])[:15]
    for s, fig in paired:
        m = s["main"]
        rows.append([m.session_id[:8], os.path.basename(m.cwd or "?"), (m.started or "")[:16], m.user_turns,
                     len(s["agents"]), _k(m.max_context), m.compactions, _money(fig["cost"]), fig["label"]])
    lines.append(_table(rows, ["session", "project", "started", "turns", "agents", "max context", "compact", "cost", "basis"]))
    return "\n".join(lines)


def findings(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Measured anti-patterns. Each: dict(id, title, evidence, saving_usd, lever)."""
    out = []
    agents = [a for s in data["sessions"] for a in s["agents"]]
    mains = [s["main"] for s in data["sessions"]]
    rates = relay_prices.table()["models"]

    # F1: build-class agents on Opus (an agent whose prompt said `Escalated:` was sent there on purpose)
    opus_build = [a for a in agents if classify(a.agent_type) == "build"
                  and relay_prices.tier(a.model) == "opus" and not a.escalated]
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


def compare(a: dict[str, Any], b: dict[str, Any], label_a: str = "A", label_b: str = "B") -> str:
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
        return t["grand"] / turns if key == "cost" else t[key] / turns

    rows = [
        row("sessions", lambda t: t["sessions"], lambda t: t["sessions"], str),
        row("your turns", lambda t: t["user_turns"], lambda t: t["user_turns"], str),
        row("agents", lambda t: t["agents"], lambda t: t["agents"], str),
        row("cost total $", lambda t: t["grand"], lambda t: t["grand"]),
        row("cost per turn $", lambda t: per_turn(t, "cost"), lambda t: per_turn(t, "cost")),
        row("agent share %", lambda t: (t["agents_total"].cost / max(t["main"].cost + t["agents_total"].cost, 1e-9)) * 100,
            lambda t: (t["agents_total"].cost / max(t["main"].cost + t["agents_total"].cost, 1e-9)) * 100, lambda x: f"{x:.0f}"),
        row("reply chars per turn", lambda t: t["reply_chars"] / max(t["user_turns"], 1), lambda t: t["reply_chars"] / max(t["user_turns"], 1), lambda x: f"{x:,.0f}"),
        row("your prompt chars per turn", lambda t: t["prompt_chars"] / max(t["user_turns"], 1), lambda t: t["prompt_chars"] / max(t["user_turns"], 1), lambda x: f"{x:,.0f}"),
        row("prompts over 600 chars", lambda t: t["long_prompts"], lambda t: t["long_prompts"], str),
        row("main sessions' share of cost %", lambda t: t["front_cost"] / max(t["interactive_cost"], 1e-9) * 100,
            lambda t: t["front_cost"] / max(t["interactive_cost"], 1e-9) * 100, lambda x: f"{x:.0f}"),
        row("front requests per turn", lambda t: t["front_requests"] / max(t["user_turns"], 1),
            lambda t: t["front_requests"] / max(t["user_turns"], 1), lambda x: f"{x:,.1f}"),
        row("front tool calls per turn", lambda t: t["front_tool_calls"] / max(t["user_turns"], 1),
            lambda t: t["front_tool_calls"] / max(t["user_turns"], 1), lambda x: f"{x:,.1f}"),
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
