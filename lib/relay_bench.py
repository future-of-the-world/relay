"""relay bench: the same work under two setups, side by side.

A *profile* (profiles/<name>.toml) is a setup: the front's model and effort,
the model and effort of each delegation tier, which rules load, which plugins
are on. A *scenario* (evals/scenarios/<name>/scenario.toml) is a job: a fixture
project, a prompt, limits, and graders that say whether the result is right.

For every profile x scenario x run, the bench copies the fixture into a fresh
workspace, runs `claude -p` headless with the profile applied through flags
(--model, --agents, --append-system-prompt, --plugin-dir, env), reads the
result JSON Claude Code prints (cost, duration, turns, tokens per model: these
are authoritative, not estimates), runs the graders, and records one row.
Results go to ~/.relay/bench/<timestamp>/ as results.json and report.md.

The `claude` binary is RELAY_CLAUDE_BIN (default `claude`); tests point it at
a fake that prints a result document, so the whole pipeline is tested without
spending money.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile

import relay_paidcap
from relay_config import ROOT, bench_dir, read_toml

GRADER_TYPES = ("regex", "file_exists", "command", "llm", "agent_used")


# --- profiles ---------------------------------------------------------------

TIERS = ("look", "run", "build", "fix", "think", "judge")


def load_profile(name_or_path):
    path = name_or_path
    if not os.path.isfile(path):
        for candidate in (os.path.join(ROOT, "profiles", f"{name_or_path}.toml"),
                          os.path.join(ROOT, "profiles", "candidates", f"{name_or_path}.toml")):
            if os.path.isfile(candidate):
                path = candidate
                break
    if not os.path.isfile(path):
        raise FileNotFoundError(f"no profile '{name_or_path}' (profiles/<name>.toml or profiles/candidates/<name>.toml)")
    data = read_toml(path)
    data.setdefault("profile", {}).setdefault("name", os.path.basename(path)[:-len(".toml")])
    data["_path"] = path
    return data


def plugin_dir(profile, entry):
    """A plugin entry is a name (plugins/<name>) or a path (relative to the profile's folder or to ROOT)."""
    candidates = [os.path.join(ROOT, "plugins", entry)]
    if "/" in entry or entry.startswith("."):
        base = os.path.dirname(profile.get("_path") or ROOT)
        candidates = [os.path.join(base, entry), os.path.join(ROOT, entry), entry]
    for c in candidates:
        if os.path.isdir(c) and os.path.isfile(os.path.join(c, ".claude-plugin", "plugin.json")):
            return os.path.realpath(c)
    return None


def agent_definitions_dir(profile):
    """Where the delegate agents come from for this profile: a copied plugin when the profile names one."""
    for entry in profile.get("plugins", {}).get("enabled", []):
        folder = plugin_dir(profile, entry)
        if folder and os.path.basename(folder) == "delegate" and os.path.isdir(os.path.join(folder, "agents")):
            return os.path.join(folder, "agents")
    return os.path.join(ROOT, "plugins", "delegate", "agents")


def new_candidate(name, base_name="active", copy_plugins=(), sets=()):
    """profiles/candidates/<name>.toml (+ <name>/plugins/<p>/ copies to edit)."""
    base = load_profile(base_name)
    out = derive_profile(base, list(sets)) if sets else __import__("copy").deepcopy(base)
    folder = os.path.join(ROOT, "profiles", "candidates", name)
    copied = []
    enabled = list(out.get("plugins", {}).get("enabled", []))
    for plugin in copy_plugins:
        src = os.path.join(ROOT, "plugins", plugin)
        if not os.path.isdir(src):
            raise FileNotFoundError(f"no plugin '{plugin}' under plugins/")
        dst = os.path.join(folder, "plugins", plugin)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        rel = os.path.join(name, "plugins", plugin)
        enabled = [rel if e == plugin else e for e in enabled]
        if rel not in enabled:
            enabled.append(rel)
        copied.append(dst)
    out.setdefault("plugins", {})["enabled"] = enabled
    out["profile"] = {"name": name, "description": f"{base['profile']['name']} with " + (", ".join(sets) if sets else "") + (("; edited copies of " + ", ".join(copy_plugins)) if copy_plugins else "")}
    out.pop("_derived", None)
    out["_path"] = os.path.join(ROOT, "profiles", "candidates", f"{name}.toml")
    os.makedirs(os.path.dirname(out["_path"]), exist_ok=True)
    with open(out["_path"], "w", encoding="utf-8") as handle:
        handle.write(f"# Candidate: {out['profile']['description']}\n# Edit the copies under profiles/candidates/{name}/plugins/ ; bench with `relay bench active {name}`.\n\n")
        handle.write(to_toml(out))
    return out, copied


def derive_profile(base, sets):
    """A profile that is `base` with dotted keys changed: ["models.build=haiku", "effort.build=low"].
    Its name lists the changes, so the bench table can name it; it is also
    marked `_derived`: run_bench writes it beside the bench report (never into the repository), and
    `relay improve adopt <path to that file>` adopts it."""
    import copy
    out = copy.deepcopy(base)
    # The derived file moves to the bench folder: keep relative plugin paths pointing where the base's do.
    enabled = out.get("plugins", {}).get("enabled")
    if enabled:
        out["plugins"]["enabled"] = [
            (plugin_dir(base, e) or e) if ("/" in e or e.startswith(".")) else e for e in enabled]
    parts = []
    for item in sets:
        key, _, value = item.partition("=")
        if not key or not value:
            raise ValueError(f"--set wants key=value, got {item!r}")
        node = out
        path = key.split(".")
        for p in path[:-1]:
            node = node.setdefault(p, {})
        if value.lower() in ("true", "false"):
            node[path[-1]] = value.lower() == "true"
        elif value.isdigit():
            node[path[-1]] = int(value)
        elif "," in value:
            node[path[-1]] = [v.strip() for v in value.split(",") if v.strip()]
        else:
            node[path[-1]] = value
        parts.append(f"{path[-1]}-{value}".replace(",", "+"))
    name = "-".join(parts)[:60]
    out["profile"] = {"name": name, "description": f"{base['profile']['name']} with " + ", ".join(sets)}
    out["_derived"] = True
    out["_path"] = None
    return out


def to_toml(data):
    """A small TOML writer for profile dicts (strings, ints, bools, flat lists, one level of tables)."""
    def lit(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, list):
            return "[" + ", ".join(lit(x) for x in v) + "]"
        return '"' + str(v).replace('"', '\\"') + '"'
    lines = []
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict):
            lines.append(f"[{key}]")
            for k, v in value.items():
                lines.append(f"{k} = {lit(v)}")
            lines.append("")
        else:
            lines.append(f"{key} = {lit(value)}")
    return "\n".join(lines) + "\n"


def agent_definitions(profile):
    """The delegate agents with the profile's model and effort per tier, as the
    JSON the `--agents` flag takes: {name: {description, prompt, tools, model, effort}}."""
    folder = agent_definitions_dir(profile)
    out = {}
    models = profile.get("models", {})
    efforts = profile.get("effort", {})
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".md"):
            continue
        front, body = split_frontmatter(open(os.path.join(folder, name), encoding="utf-8").read())
        tier = front.get("relay-tier") or ""
        agent = {
            "description": front.get("description", ""),
            "prompt": body.strip(),
        }
        if front.get("tools"):
            agent["tools"] = [t.strip() for t in front["tools"].split(",") if t.strip()]
        model = models.get(tier) or front.get("model")
        if model:
            agent["model"] = model
        effort = efforts.get(tier) or front.get("effort")
        if effort:
            agent["effort"] = effort
        if front.get("maxTurns"):
            agent["maxTurns"] = int(front["maxTurns"])
        out[front.get("name") or name[:-3]] = agent
    return out


def split_frontmatter(text):
    """({key: value}, body) for a markdown file with a --- front matter block."""
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return {}, text
    front = {}
    for line in m.group(1).split("\n"):
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            front[key.strip()] = value.strip()
    return front, m.group(2)


def rules_text(profile):
    """The rules the profile loads, concatenated, for --append-system-prompt."""
    names = profile.get("rules", {}).get("load", [])
    parts = []
    for name in names:
        path = os.path.join(ROOT, "rules", f"{name}.md")
        if os.path.isfile(path):
            parts.append(open(path, encoding="utf-8").read().strip())
    return "\n\n".join(parts)


# --- scenarios --------------------------------------------------------------

def load_scenario(name_or_path):
    path = name_or_path
    if os.path.isdir(path):
        path = os.path.join(path, "scenario.toml")
    if not os.path.isfile(path):
        candidate = os.path.join(ROOT, "evals", "scenarios", name_or_path, "scenario.toml")
        if os.path.isfile(candidate):
            path = candidate
    if not os.path.isfile(path):
        raise FileNotFoundError(f"no scenario '{name_or_path}' (evals/scenarios/<name>/scenario.toml)")
    data = read_toml(path)
    data["_dir"] = os.path.dirname(os.path.abspath(path))
    data.setdefault("name", os.path.basename(data["_dir"]))
    prompt_file = os.path.join(data["_dir"], data.get("prompt", "prompt.md"))
    data["_prompt"] = open(prompt_file, encoding="utf-8").read().strip()
    for g in data.get("graders", []):
        if g.get("type") not in GRADER_TYPES:
            raise ValueError(f"{data['name']}: grader '{g.get('name')}' has unknown type {g.get('type')!r}; one of {GRADER_TYPES}")
    if not data.get("graders"):
        raise ValueError(f"{data['name']}: a scenario needs at least one grader")
    return data


def list_scenarios(tag=None):
    folder = os.path.join(ROOT, "evals", "scenarios")
    out = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        path = os.path.join(folder, name, "scenario.toml")
        if os.path.isfile(path):
            s = load_scenario(path)
            if tag is None or tag in s.get("tags", []):
                out.append(s)
    return out


def make_workspace(scenario, base_dir):
    ws = tempfile.mkdtemp(prefix=f"bench-{scenario['name']}-", dir=base_dir)
    fixture = scenario.get("fixture")
    if fixture:
        src = os.path.normpath(os.path.join(scenario["_dir"], fixture))
        shutil.copytree(src, ws, dirs_exist_ok=True, symlinks=True)
    scaffold = scenario.get("scaffold")
    if scaffold:
        subprocess.run(["bash", os.path.join(scenario["_dir"], scaffold)], cwd=ws, check=True,
                       capture_output=True, text=True, timeout=300)
    return ws


# --- graders ----------------------------------------------------------------

def grade(scenario, workspace, result_text, claude_bin, judge_model, session_id=None, config_dir=None):
    out = []
    calls: list[tuple[str, str]] | None = None   # read once, only when a grader needs it
    for g in scenario.get("graders", []):
        kind = g["type"]
        passed, note = False, ""
        try:
            if kind == "regex":
                flags = re.I if "i" in g.get("flags", "") else 0
                passed = re.search(g["pattern"], result_text or "", flags | re.S) is not None
                note = "matched" if passed else "no match"
            elif kind == "file_exists":
                passed = os.path.exists(os.path.join(workspace, g["path"])) == g.get("exists", True)
                note = g["path"]
            elif kind == "command":
                proc = subprocess.run(["bash", "-c", g["command"]], cwd=workspace, capture_output=True,
                                      text=True, timeout=g.get("timeout_s", 300))
                passed = proc.returncode == 0
                note = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or [""]
                note = f"exit {proc.returncode}: {note[0][:120]}"
            elif kind == "llm":
                if calls is None:
                    calls = tool_calls(session_id, config_dir)
                passed, note = llm_grade(g, result_text, workspace, claude_bin, judge_model, calls)
            elif kind == "agent_used":
                passed, note = agent_used(g, session_id)
            elif kind == "tool_called":
                if calls is None:
                    calls = tool_calls(session_id, config_dir)
                passed, note = tool_called(g, session_id, calls)
        except Exception as exc:  # a grader that crashes is a failed grader, with the reason
            passed, note = False, f"grader error: {exc}"
        out.append({"name": g["name"], "type": kind, "passed": passed, "note": note, "weight": g.get("weight", 1)})
    return out


def agent_used(g, session_id):
    """Did the session start an agent whose type matches `agent_type` (a regex)? Read from the
    relay ledger (the observe plugin must be enabled in the profile under test)."""
    import relay_ledger
    if not session_id:
        return False, "no session id in the result"
    pattern = re.compile(g["agent_type"])
    started = [e.get("agent_type") or "general-purpose" for e in relay_ledger.read()
               if e.get("event") == "agent_start" and e.get("session_id") == session_id]
    hits = [a for a in started if pattern.search(a)]
    want = g.get("count", 1)
    if g.get("exists", True):
        return len(hits) >= want, f"started: {', '.join(started) or 'none'}"
    return not hits, f"started: {', '.join(started) or 'none'}"


_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH", re.I)


def redact(text: str) -> str:
    """Replace every secret-looking environment value (by variable name, 8+ characters) in `text`,
    so nothing a grader reads can carry one."""
    for name, value in os.environ.items():
        if len(value) >= 8 and _SECRET_NAME.search(name):
            text = text.replace(value, "[redacted]")
    return text


def _call_summary(name: str, tool_input: object) -> str:
    """The part of a tool call a grader can match: a Bash command, a file path, else the input as JSON."""
    if isinstance(tool_input, dict):
        for key in ("command", "file_path", "path", "pattern"):
            if isinstance(tool_input.get(key), str):
                return tool_input[key]
    return json.dumps(tool_input, sort_keys=True)


def tool_calls(session_id: str | None, config_dir: str | None = None) -> list[tuple[str, str]]:
    """Every tool call of the session and of its subagents, as (tool name, command or path), secrets
    redacted, in file order. Read from the transcripts Claude Code leaves under `<config>/projects`."""
    if not session_id:
        return []
    from relay_config import claude_dir
    root = os.path.join(config_dir or claude_dir(), "projects")
    files = sorted(glob.glob(os.path.join(root, "*", session_id + ".jsonl"))
                   + glob.glob(os.path.join(root, "*", session_id, "subagents", "*.jsonl")))
    out: list[tuple[str, str]] = []
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    message = json.loads(line).get("message")
                except ValueError:
                    continue                      # a torn last line of a transcript still being written
                content = message.get("content") if isinstance(message, dict) else None
                for block in content if isinstance(content, list) else []:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and isinstance(block.get("name"), str):
                        out.append((block["name"], redact(_call_summary(block["name"], block.get("input")))))
    return out


def tool_called(g, session_id: str | None, calls: list[tuple[str, str]]) -> tuple[bool, str]:
    """Did the session (or a subagent) call a tool matching `tool` (a regex on the name, default
    Bash) whose command or path matches `input` (a regex, default any)? `count` calls at least
    (default 1); `exists = false` inverts."""
    if not session_id:
        return False, "no session id in the result"
    name_re, input_re = re.compile(g.get("tool", "^Bash$")), re.compile(g.get("input", ""), re.S)
    hits = [c for c in calls if name_re.search(c[0]) and input_re.search(c[1])]
    note = f"{len(hits)} of {len(calls)} calls matched" + (f": {hits[0][0]} {hits[0][1][:100]}" if hits else "")
    if g.get("exists", True):
        return len(hits) >= g.get("count", 1), note
    return not hits, note


def llm_grade(g, result_text, workspace, claude_bin, judge_model, calls=None):
    """A PASS/FAIL rubric judged by a cheap model in a fresh headless session."""
    rubric = g["rubric"]
    seen = "".join(f"- {n}: {c[:200]}\n" for n, c in (calls or [])[:200])
    prompt = (
        "You are a strict grader. Read the rubric and the candidate reply, then answer with "
        "exactly one line: PASS or FAIL, then a colon and one sentence why.\n\n"
        f"Rubric:\n{rubric}\n\nCandidate reply:\n{result_text[:20000]}\n"
        + (f"\nTool calls the candidate's session made:\n{seen}" if seen else "")
    )
    proc = subprocess.run([claude_bin, "-p", prompt, "--model", judge_model, "--output-format", "json",
                           "--max-turns", "1", "--tools", ""],
                          cwd=workspace, capture_output=True, text=True, timeout=180)
    verdict = ""
    try:
        verdict = json.loads(proc.stdout).get("result", "")
    except ValueError:
        verdict = proc.stdout
    return verdict.strip().upper().startswith("PASS"), verdict.strip()[:160]


def score(graders):
    weight = sum(g["weight"] for g in graders) or 1
    return sum(g["weight"] for g in graders if g["passed"]) / weight


# --- running ----------------------------------------------------------------

def plugin_for_run(profile, folder, out_dir):
    """The folder `--plugin-dir` gets for one plugin. A plugin that carries agents (delegate) is copied
    with each agent's model and effort set to the profile's for its tier: the session starts the plugin's
    own `delegate:worker`, and `--agents` only adds an unprefixed `worker` it never picks, so without the
    copy a change to models.build would not reach the worker that runs."""
    source = os.path.join(folder, "agents")
    if not os.path.isdir(source):
        return folder
    dest = os.path.join(out_dir, f"plugin-{profile['profile']['name']}-{os.path.basename(folder)}")
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(folder, dest, symlinks=True)
    models, efforts = profile.get("models", {}), profile.get("effort", {})
    for file in sorted(os.listdir(os.path.join(dest, "agents"))):
        if not file.endswith(".md"):
            continue
        path = os.path.join(dest, "agents", file)
        text = open(path, encoding="utf-8").read()
        front, _ = split_frontmatter(text)
        tier = front.get("relay-tier") or ""
        for key, table in (("model", models), ("effort", efforts)):
            if table.get(tier):
                text = re.sub(rf"^{key}:.*$", f"{key}: {table[tier]}", text, count=1, flags=re.M)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    return dest


def claude_command(profile, scenario, prompt, agents_json_path, rules_path, out_dir=None):
    session = profile.get("session", {})
    cmd = [os.environ.get("RELAY_CLAUDE_BIN", "claude"), "-p", prompt, "--output-format", "json",
           "--max-turns", str(scenario.get("max_turns", 30))]
    if session.get("model"):
        cmd += ["--model", session["model"]]
    mode = scenario.get("permission_mode") or session.get("permission_mode") or "acceptEdits"
    cmd += ["--permission-mode", mode]
    tools = scenario.get("allowed_tools")
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]
    if agents_json_path:
        cmd += ["--agents", open(agents_json_path, encoding="utf-8").read()]
    if rules_path and os.path.getsize(rules_path) > 0:
        cmd += ["--append-system-prompt", open(rules_path, encoding="utf-8").read()]
    for plugin in profile.get("plugins", {}).get("enabled", []):
        folder = plugin_dir(profile, plugin)
        if folder:
            cmd += ["--plugin-dir", plugin_for_run(profile, folder, out_dir) if out_dir else folder]
    if scenario.get("max_cost_usd"):
        cmd += ["--max-budget-usd", str(scenario["max_cost_usd"])]
    for extra in profile.get("session", {}).get("extra_args", []):
        cmd.append(extra)
    return cmd


def isolated_config_dir(base_dir):
    """A throwaway CLAUDE_CONFIG_DIR: credentials copied, nothing else (no user CLAUDE.md,
    no installed plugins, no memory), so the two profiles differ only in what they declare.
    On a machine that keeps credentials in the system keychain the copy is empty and
    sign-in still works; if a run fails with an auth error, bench without --isolate."""
    from relay_config import claude_dir
    folder = tempfile.mkdtemp(prefix="claude-config-", dir=base_dir)
    for name in (".credentials.json",):
        src = os.path.join(claude_dir(), name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(folder, name))
    with open(os.path.join(folder, "settings.json"), "w", encoding="utf-8") as handle:
        json.dump({"enabledPlugins": {}}, handle)
    return folder


def run_one(profile, scenario, run_index, out_dir, judge_model, keep=False, config_dir=None):
    ws = make_workspace(scenario, out_dir)
    agents = agent_definitions(profile)
    agents_path = os.path.join(out_dir, f"agents-{profile['profile']['name']}.json")
    with open(agents_path, "w", encoding="utf-8") as handle:
        json.dump(agents, handle)
    rules_path = os.path.join(out_dir, f"rules-{profile['profile']['name']}.md")
    with open(rules_path, "w", encoding="utf-8") as handle:
        handle.write(rules_text(profile))
    env = dict(os.environ)
    env.update({k: str(v) for k, v in profile.get("env", {}).items()})
    env["RELAY_BENCH"] = "1"
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = config_dir
    cmd = claude_command(profile, scenario, scenario["_prompt"], agents_path, rules_path, out_dir)
    started = dt.datetime.now(dt.timezone.utc)
    row = {"profile": profile["profile"]["name"], "scenario": scenario["name"], "run": run_index,
           "started": started.isoformat(), "workspace": ws if keep else None}
    try:
        proc = subprocess.run(cmd, cwd=ws, env=env, capture_output=True, text=True,
                              timeout=scenario.get("timeout_s", 900))
        row["exit"] = proc.returncode
        result = parse_result(proc.stdout)
        row["error"] = None if result else (proc.stderr.strip()[-500:] or "no result document")
    except subprocess.TimeoutExpired:
        proc, result = None, {}
        row["exit"], row["error"] = -1, "timeout"
    wall = (dt.datetime.now(dt.timezone.utc) - started).total_seconds()
    row["wall_s"] = round(wall, 1)
    row["cost_usd"] = result.get("total_cost_usd")
    row["duration_s"] = round((result.get("duration_ms") or wall * 1000) / 1000, 1)
    row["api_s"] = round((result.get("duration_api_ms") or 0) / 1000, 1)
    row["turns"] = result.get("num_turns")
    row["usage"] = result.get("usage")
    row["model_usage"] = result.get("modelUsage")
    row["session_id"] = result.get("session_id")
    text = result.get("result") or ""
    row["reply_chars"] = len(text)
    row["graders"] = grade(scenario, ws, text, os.environ.get("RELAY_CLAUDE_BIN", "claude"), judge_model, session_id=row["session_id"], config_dir=config_dir)
    row["score"] = score(row["graders"])
    with open(os.path.join(out_dir, f"{profile['profile']['name']}-{scenario['name']}-{run_index}.log"), "w", encoding="utf-8") as handle:
        handle.write("$ " + " ".join(shell_quote(c) for c in cmd[:6]) + " ...\n\n")
        if proc is not None:
            handle.write(proc.stdout[-20000:])
            handle.write("\n--- stderr ---\n" + proc.stderr[-5000:])
    if not keep:
        shutil.rmtree(ws, ignore_errors=True)
        shutil.rmtree(ws + ".main", ignore_errors=True)   # the primary checkout a scaffold may leave beside the workspace
    return row


def shell_quote(s):
    return s if re.fullmatch(r"[\w./:=@-]+", s) else "'" + s.replace("'", "'\\''") + "'"


def parse_result(stdout):
    """The result document of `claude -p --output-format json` (the last JSON object on stdout)."""
    stdout = (stdout or "").strip()
    if not stdout:
        return {}
    try:
        doc = json.loads(stdout)
        if isinstance(doc, list):
            doc = next((d for d in reversed(doc) if isinstance(d, dict) and d.get("type") == "result"), {})
        return doc if isinstance(doc, dict) else {}
    except ValueError:
        pass
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                doc = json.loads(line)
                if doc.get("type") == "result" or "total_cost_usd" in doc:
                    return doc
            except ValueError:
                continue
    return {}


class PaidCapReached(RuntimeError):
    """The day's paid-run cap would be passed by this run."""


def run_bench(profiles, scenarios, runs=None, judge_model="haiku", keep=False, out_root=None, max_cost_usd=None, isolate=False):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    sessions = len(profiles) * sum(runs or s.get("runs", 1) for s in scenarios)
    refusal = relay_paidcap.check(stamp[:10], relay_paidcap.bench_estimate(sessions, out_root), "bench", bench=out_root,
                                    roots=relay_paidcap.suite_roots(ROOT))
    if refusal:
        raise PaidCapReached(refusal)
    out_dir = os.path.join(out_root or bench_dir(), stamp)
    os.makedirs(out_dir, exist_ok=True)
    if out_root and os.path.realpath(out_root) != os.path.realpath(bench_dir()):
        relay_paidcap.link_out(out_dir, stamp)   # the day's spend (bin/paid-cost today, the cap) counts a run kept outside ~/.relay/bench
    for profile in profiles:
        if profile.get("_derived"):
            profile["_path"] = os.path.join(out_dir, f"{profile['profile']['name']}.toml")
            with open(profile["_path"], "w", encoding="utf-8") as handle:
                handle.write(f"# Derived by `relay bench --set`: {profile['profile']['description']}\n# Adopt with `relay improve adopt {profile['_path']}`.\n\n")
                handle.write(to_toml(profile))
    config_dir = isolated_config_dir(out_dir) if isolate else None
    rows = []
    spent = 0.0
    stopped = None
    for scenario in scenarios:
        n = runs or scenario.get("runs", 1)
        for i in range(n):
            for profile in profiles:          # interleave profiles so time-of-day affects both alike
                row = run_one(profile, scenario, i, out_dir, judge_model, keep=keep, config_dir=config_dir)
                rows.append(row)
                spent += row.get("cost_usd") or 0.0
                if max_cost_usd is not None and spent > max_cost_usd:
                    stopped = f"cost ceiling ${max_cost_usd:.2f} reached after ${spent:.2f}"
                    break
            if stopped:
                break
        if stopped:
            break
    doc = {
        "started": stamp, "profiles": [p["profile"] | {"path": p["_path"]} for p in profiles],
        "scenarios": [s["name"] for s in scenarios], "rows": rows, "partial": bool(stopped), "stopped": stopped,
        "claude_bin": os.environ.get("RELAY_CLAUDE_BIN", "claude"), "isolated": bool(isolate),
    }
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=2)
    text = render(doc)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as handle:
        handle.write(text)
    return out_dir, doc, text


# --- rendering --------------------------------------------------------------

def aggregate(doc):
    """{(profile, scenario): {score, cost, duration, turns, n, errors, reply_chars, by_tier}}"""
    agg = {}
    for row in doc["rows"]:
        key = (row["profile"], row["scenario"])
        a = agg.setdefault(key, {"score": [], "cost": [], "duration": [], "turns": [], "errors": 0, "reply_chars": [], "by_tier": {}})
        a["score"].append(row.get("score") or 0.0)
        if row.get("cost_usd") is not None:
            a["cost"].append(row["cost_usd"])
        a["duration"].append(row.get("duration_s") or 0.0)
        if row.get("turns") is not None:
            a["turns"].append(row["turns"])
        a["reply_chars"].append(row.get("reply_chars") or 0)
        if row.get("error"):
            a["errors"] += 1
        for model, mu in (row.get("model_usage") or {}).items():
            tier = _tier(model)
            a["by_tier"][tier] = a["by_tier"].get(tier, 0.0) + float(mu.get("costUSD") or 0.0)
    for a in agg.values():
        a["n"] = len(a["score"])
        for k in ("score", "cost", "duration", "turns", "reply_chars"):
            a[k + "_mean"] = sum(a[k]) / len(a[k]) if a[k] else None
        a["score_min"] = min(a["score"]) if a["score"] else None
    return agg


def _tier(model):
    name = (model or "").lower()
    for t in ("opus", "sonnet", "haiku"):
        if t in name:
            return t
    return "other"


def _fmt(v, kind):
    if v is None:
        return "-"
    if kind == "money":
        return f"${v:.2f}"
    if kind == "score":
        return f"{v:.2f}"
    if kind == "s":
        return f"{v:.0f}s"
    if kind == "int":
        return f"{v:.1f}"
    return str(v)


def render(doc):
    agg = aggregate(doc)
    names = [p["name"] for p in doc["profiles"]]
    lines = [f"# Bench {doc['started']}", ""]
    lines.append("Profiles: " + ", ".join(f"{p['name']} ({p.get('description', '')})" for p in doc["profiles"]))
    lines.append("Scenarios: " + ", ".join(doc["scenarios"]))
    if doc.get("partial"):
        lines.append(f"PARTIAL: {doc['stopped']}")
    lines.append("")
    measures = [("quality (mean score)", "score_mean", "score"), ("quality (worst run)", "score_min", "score"),
                ("cost $ (Claude's own figure)", "cost_mean", "money"), ("time", "duration_mean", "s"),
                ("turns", "turns_mean", "int"), ("reply length", "reply_chars_mean", "int")]
    for scenario in doc["scenarios"]:
        lines.append(f"## {scenario}")
        headers = ["measure"] + names + (["delta (B-A)"] if len(names) == 2 else [])
        rows = []
        for label, key, kind in measures:
            vals = [agg.get((n, scenario), {}).get(key) for n in names]
            row = [label] + [_fmt(v, kind) for v in vals]
            if len(names) == 2 and None not in vals:
                d = vals[1] - vals[0]
                pct = f" ({d / vals[0] * 100:+.0f}%)" if vals[0] else ""
                row.append(("+" if d >= 0 else "") + _fmt(d, kind).lstrip("+") + pct)
            rows.append(row)
        tiers = sorted({t for n in names for t in agg.get((n, scenario), {}).get("by_tier", {})})
        for t in tiers:
            vals = [agg.get((n, scenario), {}).get("by_tier", {}).get(t) for n in names]
            n_runs = [agg.get((n, scenario), {}).get("n") or 1 for n in names]
            vals = [v / k if v is not None else None for v, k in zip(vals, n_runs)]
            row = [f"  of which {t} $"] + [_fmt(v, "money") for v in vals]
            if len(names) == 2 and None not in vals:
                row.append(f"{vals[1]-vals[0]:+.2f}")
            rows.append(row)
        errs = [agg.get((n, scenario), {}).get("errors", 0) for n in names]
        rows.append(["runs with errors"] + [str(e) for e in errs] + ([""] if len(names) == 2 else []))
        lines.append(_table(rows, headers))
        lines.append("")
        # grader detail
        for n in names:
            runs = [r for r in doc["rows"] if r["profile"] == n and r["scenario"] == scenario]
            failed = {}
            for r in runs:
                for g in r.get("graders", []):
                    if not g["passed"]:
                        failed.setdefault(g["name"], []).append(f"run {r['run']}: {g['note']}")
            if failed:
                lines.append(f"{n}: failed graders")
                for g, notes in failed.items():
                    lines.append(f"  - {g}: " + "; ".join(notes)[:300])
        lines.append("")
    lines.append(verdict(doc, agg))
    return "\n".join(lines)


def _adopt_arg(entry):
    """The argument `relay improve adopt` can load: the bare name for a profile under profiles/, else its path."""
    path = entry.get("path")
    if not path:
        return entry["name"]
    folder = os.path.realpath(os.path.dirname(path))
    profiles = os.path.realpath(os.path.join(ROOT, "profiles"))
    if folder in (profiles, os.path.join(profiles, "candidates")):
        return entry["name"]
    return path


def verdict(doc, agg):
    """One paragraph: which profile wins, by the rule 'no scenario worse in quality; then cheaper; then faster'."""
    names = [p["name"] for p in doc["profiles"]]
    if len(names) != 2:
        return "Verdict: compare two profiles to get one."
    a, b = names
    worse, cheaper, faster = [], 0.0, 0.0
    for s in doc["scenarios"]:
        qa, qb = agg.get((a, s), {}), agg.get((b, s), {})
        if (qb.get("score_min") or 0) < (qa.get("score_min") or 0) - 1e-9:
            worse.append(s)
        if qa.get("cost_mean") is not None and qb.get("cost_mean") is not None:
            cheaper += qa["cost_mean"] - qb["cost_mean"]
        faster += (qa.get("duration_mean") or 0) - (qb.get("duration_mean") or 0)
    if worse:
        return f"Verdict: keep {a}. {b} is worse in quality on: {', '.join(worse)}. (A cheaper run that fails is not cheaper.)"
    if cheaper > 0.005:
        return f"Verdict: {b} wins: same or better quality on every scenario, ${cheaper:.2f} cheaper per scenario set, {faster:+.0f}s faster. Adopt with `relay improve adopt {_adopt_arg(doc['profiles'][1])}`."
    if cheaper < -0.005:
        return f"Verdict: keep {a}. {b} is not worse in quality but costs ${-cheaper:.2f} more per scenario set."
    return f"Verdict: a tie on quality and cost; {b} is {faster:+.0f}s faster. Decide on speed, or add a scenario that separates them."


def _table(rows, headers):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(cell)))
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)), "  ".join("-" * w for w in widths)]
    for row in rows:
        out.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row) if i < len(widths)))
    return "\n".join(out)


def list_results(limit=10):
    folder = bench_dir()
    if not os.path.isdir(folder):
        return []
    names = sorted(os.listdir(folder), reverse=True)[:limit]
    out = []
    for n in names:
        path = os.path.join(folder, n, "results.json")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                out.append((n, json.load(handle)))
    return out
