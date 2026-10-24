"""relay setup / migrate / doctor: a project onto relay, new or existing, and a check-up.

Nothing here deletes a file. Migration lists what the old setup had and what
replaces it; `--apply` moves the replaced files to .claude/relay-migration/
(so a revert is a `mv` back), never `rm`.
"""

import datetime as dt
import json
import os
import shutil
import stat
import subprocess
import tomllib

import relay_config
from relay_config import ROOT, bindings_path, claude_dir, load_bindings, read_toml, main_checkout

STACKS = [
    ("bun.lock", "typescript", "bun"), ("bun.lockb", "typescript", "bun"), ("pnpm-lock.yaml", "typescript", "pnpm"),
    ("package-lock.json", "typescript", "npm"), ("yarn.lock", "typescript", "yarn"), ("mix.exs", "elixir", "mix"),
    ("Cargo.toml", "rust", "cargo"), ("go.mod", "go", "go"), ("pyproject.toml", "python", "python"),
]
OLD_ROLES = ("worker", "fixer", "author", "reviewer", "spec-reviewer", "spec-conformance", "code-reviewer", "ui-reviewer")
OLD_STAGES = ("plan", "spec-review", "parallel-apply", "apply-review", "archive")


def detect(root):
    d = {"root": root, "name": os.path.basename(os.path.realpath(root)), "git": os.path.isdir(os.path.join(root, ".git")) or os.path.isfile(os.path.join(root, ".git"))}
    d["stack"], d["tool"] = "unknown", ""
    for marker, stack, tool in STACKS:
        if os.path.exists(os.path.join(root, marker)):
            d["stack"], d["tool"] = stack, tool
            break
    d["default_branch"] = default_branch(root)
    d["openspec"] = os.path.isdir(os.path.join(root, "openspec"))
    d["has_bindings"] = os.path.isfile(bindings_path(root))
    d["bindings"] = load_bindings(root)
    d["scripts"] = {s: os.path.isfile(os.path.join(root, "bin", s)) for s in ("check", "ci", "wt")}
    d["claude_md"] = os.path.isfile(os.path.join(root, "CLAUDE.md"))
    d["handover"] = os.path.isfile(os.path.join(root, "docs", "handover.md"))
    d["settings"] = read_json(os.path.join(root, ".claude", "settings.json"))
    agents_dir = os.path.join(root, ".claude", "agents")
    d["agents"] = sorted(f[:-3] for f in os.listdir(agents_dir)) if os.path.isdir(agents_dir) else []
    skills_dir = os.path.join(root, ".claude", "skills")
    d["skills"] = sorted(os.listdir(skills_dir)) if os.path.isdir(skills_dir) else []
    d["additions"] = sorted(os.listdir(os.path.join(root, ".claude", "kit"))) if os.path.isdir(os.path.join(root, ".claude", "kit")) else []
    d["issue_skills"] = [s for s in d["skills"] if "issue" in s]
    d["ui"] = any(os.path.exists(os.path.join(root, p)) for p in ("index.html", "src/ui", "src/App.tsx", "src-tauri", "lib/*_web"))
    if d["openspec"]:
        d["flow"] = "openspec"
    elif d["issue_skills"] or d["bindings"].get("issues") or os.path.isdir(os.path.join(root, ".issues")):
        d["flow"] = "issues"
    else:
        d["flow"] = "none"
    return d


def default_branch(root):
    for cmd in (["git", "-C", root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], ["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            out = ""
        if out and out != "HEAD":
            return out.split("/")[-1]
    return "master"


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def backup(path):
    if os.path.isfile(path):
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, f"{path}.{stamp}.bak")
        return f"{path}.{stamp}.bak"
    return None


# --- bindings ---------------------------------------------------------------

def bindings_text(d, flow, product):
    """A kit.toml for a new project; sections relay needs, with the detected values."""
    name, stack, tool = d["name"], d["stack"], d["tool"]
    skills = {"typescript": '["ts-dev"]', "rust": '["rust-dev"]', "elixir": '["elixir-dev"]', "go": '["go-dev"]'}.get(stack, "[]")
    lines = [
        f"# {name}: bindings for the relay plugins (written by `relay setup`, {dt.date.today()}).",
        "# Every key is documented in plugins/core/README.md (gate, product, packet, guard)",
        "# and docs/flows.md ([flow], [issues]); [delegate] and [observe] in docs/delegation.md.", "",
        "[project]", f'name = "{name}"', f'default_branch = "{d["default_branch"]}"', 'worktrees = ".worktrees"',
        f"stack_skills = {skills}", "",
        "[gate]", 'wt = "bin/wt"', 'check = "bin/check"', 'ci = "bin/ci"', 'ci_log = ".ci/ci.log"', 'final = "local"', "",
        "[flow]", f'kind = "{flow}"', "",
        "[delegate]", "typed_only = true", "fork_limit = 100000", "max_parallel = 4", 'build_tier_opus = "escalate"', "",
        "[observe]", "enabled = true", "log_prompts = false", "",
    ]
    if flow == "issues":
        lines += ["[issues]", "# Commands with {n}, {title}, {body_file}, {branch}, {pr}. Forgejo (tea) shown; GitHub: gh issue create/view, gh pr create/checks/merge;",
                  "# GitLab: glab; Yandex Tracker: the glonass_* tools through a runner. Issues live in .issues/<slug>/description.md on branch <slug>.",
                  'create = "tea issue create --title \"{title}\" --description \"$(cat {body_file})\""',
                  'view = "tea issue view {n} --comments"', 'list = "tea issue list --state open"',
                  'pr_create = "tea pr create --head {branch} --title \"{title}\" --description \"$(cat {body_file})\""',
                  'pr_status = "tea pr view {pr}"', 'pr_merge = "tea pr merge {pr} --style squash --delete-branch"',
                  'commit_ref = "Closes: #{n}"', 'attribution = "default"   # "none" where no Claude credit may appear (Glonass)', ""]
    if product:
        lines += ["[product]", 'medium = "the app on a phone and on a computer"', f'run_skill = "{name}-run"', "look_review = false", ""]
    lines += ["[coordination]", 'mode = "leadless"', ""]
    return "\n".join(lines)


def merge_bindings(root, flow):
    """Add the relay sections a kit.toml lacks, without touching what is there."""
    path = bindings_path(root)
    text = open(path, encoding="utf-8").read()
    cfg = tomllib.loads(text)
    added = []
    blocks = {
        "flow": f'\n[flow]\nkind = "{flow}"\n',
        "delegate": '\n[delegate]\ntyped_only = true\nfork_limit = 100000\nmax_parallel = 4\nbuild_tier_opus = "escalate"\n',
        "observe": "\n[observe]\nenabled = true\nlog_prompts = false\n",
    }
    for key, block in blocks.items():
        if key not in cfg:
            text = text.rstrip("\n") + "\n" + block
            added.append(key)
    if added:
        backup(path)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    return added


# --- settings ---------------------------------------------------------------

def relay_plugins_for(flow, product):
    plugins = ["core", "observe", "delegate", "front"]
    if flow == "openspec":
        plugins.append("sdd")
    if flow == "issues":
        plugins.append("issues")
    if product:
        plugins.append("product")
    return plugins


def merge_settings(root, plugins):
    path = os.path.join(root, ".claude", "settings.json")
    data = read_json(path)
    before = json.dumps(data, sort_keys=True)
    enabled = data.setdefault("enabledPlugins", {})
    for key in list(enabled):
        if key.endswith("@principles"):
            enabled.pop(key)   # the principles marketplace is replaced by relay
    for p in plugins:
        enabled[f"{p}@relay"] = True
    markets = data.setdefault("extraKnownMarketplaces", {})
    markets["relay"] = {"source": {"source": "directory", "path": ROOT}}
    markets.pop("principles", None)
    perms = data.setdefault("permissions", {})
    allow = perms.setdefault("allow", [])
    for rule in ("Bash(kit:*)", "Bash(bin/kit:*)", "Bash(relay:*)"):
        if rule not in allow:
            allow.append(rule)
    # Old user-level hooks now live in the front plugin.
    hooks = data.get("hooks", {})
    removed = []
    for event, groups in list(hooks.items()):
        kept = []
        for group in groups:
            cmds = " ".join(h.get("command", "") for h in group.get("hooks", []))
            if "context-budget.py" in cmds or "session-handover.py" in cmds or "opsx-stage.sh" in cmds or "guard-main.sh" in cmds:
                removed.append(f"{event}: {cmds}")
            else:
                kept.append(group)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event)
    if not hooks:
        data.pop("hooks", None)
    if json.dumps(data, sort_keys=True) != before:
        backup(path)
        write_json(path, data)
        return True, removed
    return False, removed


def merge_user_settings(plugins):
    """~/.claude/settings.json: the relay marketplace and the user-scope plugins (observe, delegate, front, core)."""
    path = os.path.join(claude_dir(), "settings.json")
    data = read_json(path)
    before = json.dumps(data, sort_keys=True)
    data.setdefault("extraKnownMarketplaces", {})["relay"] = {"source": {"source": "directory", "path": ROOT}}
    enabled = data.setdefault("enabledPlugins", {})
    for p in plugins:
        enabled[f"{p}@relay"] = True
    hooks = data.get("hooks", {})
    removed = []
    for event, groups in list(hooks.items()):
        kept = []
        for group in groups:
            cmds = " ".join(h.get("command", "") for h in group.get("hooks", []))
            if "context-budget.py" in cmds or "session-handover.py" in cmds:
                removed.append(f"{event}: {cmds}")
            else:
                kept.append(group)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event)
    if not hooks:
        data.pop("hooks", None)
    changed = json.dumps(data, sort_keys=True) != before
    if changed:
        backup(path)
        write_json(path, data)
    return path, changed, removed


# --- files ------------------------------------------------------------------

def copy_template(name, dest, mode_exec=False, replacements=None):
    if os.path.exists(dest):
        return False
    src = os.path.join(ROOT, "templates", name)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    text = open(src, encoding="utf-8").read()
    for key, value in (replacements or {}).items():
        text = text.replace("{{" + key + "}}", value)
    with open(dest, "w", encoding="utf-8") as handle:
        handle.write(text)
    if mode_exec:
        os.chmod(dest, os.stat(dest).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return True


def register_project(name, root, flow, product):
    """Add the project to projects.toml so `relay sync` writes its CLAUDE.local.md."""
    path = relay_config.projects_file()
    text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    data = tomllib.loads(text) if text else {}
    if name in data:
        return False
    load = []
    if flow == "openspec":
        load += ["openspec", "quality-gate"]
    elif flow == "issues":
        load += ["quality-gate"]
    if product:
        load.append("product-work")
    block = (f'\n[{name}]\nfile = "{os.path.join(root, "CLAUDE.local.md")}"\ntitle = "Rules this project loads"\n'
             f'load = {json.dumps(load)}\nread = []\n')
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(block)
    return True


# --- the procedures ---------------------------------------------------------

RELAY_README = """# .relay/

This folder turns on relay's hard rules in this repository (relay's design: docs/plans/review-gate.md).
It exists on the default branch, so every worktree sees it. It is created only by `relay setup`
(or `relay setup --relay-folder`), and committed.

- `queue/` the work queue: one JSON file per item, `fix` (something wrong, with its failing case) or
  `feature`, ordered by important points. `relay queue` lists it; `relay queue -h` shows the commands.
- `checks/` the gate logs, reviews, checks and check marks of task branches. A merge into the
  default branch is refused until the branch's last commit has its gate, its review and its check.

Not here: `~/.relay` is per machine (ledger, bench results) and is never committed.
"""


def relay_folder(root):
    """Write `.relay/README.md` when it is absent and nothing else; (path, created). The only step run for relay itself."""
    root = os.path.realpath(root)
    if not os.path.isdir(root):
        raise ValueError(f"no such folder: {root}")
    path = os.path.join(root, ".relay", "README.md")
    if os.path.exists(path):
        return path, False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(RELAY_README)
    return path, True


USER_SCOPE_PLUGINS = ("core", "observe", "delegate", "front")


def installed_for(root, key):
    """Is plugin `key` (name@marketplace) installed for the user, or for the project at `root`? Reads Claude's own registry."""
    reg = read_json(os.path.join(relay_config.claude_dir(), "plugins", "installed_plugins.json"))
    entries = reg.get("plugins", {}).get(key, [])
    root = os.path.realpath(root)
    for e in entries if isinstance(entries, list) else []:
        if e.get("scope") == "user":
            return True
        if e.get("projectPath") and os.path.realpath(e["projectPath"]) == root:
            return True
    return False


def run_plugin_install(root, key):
    """Real install runner: (ok, detail). The binary is RELAY_CLAUDE_BIN or `claude`."""
    cmd = [os.environ.get("RELAY_CLAUDE_BIN") or "claude", "plugin", "install", key, "--scope", "project"]
    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return proc.returncode == 0, (proc.stderr or proc.stdout).strip()


def setup(root, flow=None, product=None, apply_global=True, relay_dir=True, install_runner=None):
    """Set one project up. `relay_dir=False` leaves `.relay/` out: `migrate` (even as a plan) must not turn the work queue and the
    merge checks on in a project the owner has not chosen (docs/setup.md: old projects are not given a .relay/ folder)."""
    root = os.path.realpath(root)
    d = detect(root)
    flow = flow or d["flow"]
    product = d["ui"] if product is None else product
    done, todo = [], []
    if not d["git"]:
        todo.append("the folder is not a git repository: `git init` first; relay's worktree rules need it")
    if d["has_bindings"]:
        added = merge_bindings(root, flow)
        done.append(f"kept .claude/kit.toml; added sections: {', '.join(added) or 'none needed'}")
    else:
        os.makedirs(os.path.join(root, ".claude"), exist_ok=True)
        with open(bindings_path(root), "w", encoding="utf-8") as handle:
            handle.write(bindings_text(d, flow, product))
        done.append("wrote .claude/kit.toml (check the [gate] commands and, for issues, the [issues] commands)")
    plugins = relay_plugins_for(flow, product)
    changed, removed = merge_settings(root, plugins)
    done.append(f".claude/settings.json: plugins {', '.join(p + '@relay' for p in plugins)} enabled" + (" (unchanged)" if not changed else ""))
    for r in removed:
        done.append(f"  removed a hook the plugins now provide: {r}")
    for script in ("check", "ci", "wt"):
        if not d["scripts"][script]:
            if copy_template(f"bin-{script}", os.path.join(root, "bin", script), mode_exec=True, replacements={"tool": d["tool"], "stack": d["stack"], "branch": d["default_branch"]}):
                done.append(f"wrote bin/{script} from the template")
                todo.append(f"bin/{script}: fill in the {d['stack']} commands where it says TODO (the contract is in plugins/core/README.md)")
    if copy_template("CLAUDE.md", os.path.join(root, "CLAUDE.md"), replacements={"name": d["name"], "stack": d["stack"]}):
        done.append("wrote CLAUDE.md (a skeleton: what the product is, the commands, the product surface)")
        todo.append("CLAUDE.md: write what the project is in two lines, and its product surface if a person sees it")
    if copy_template("handover.md", os.path.join(root, "docs", "handover.md"), replacements={"name": d["name"], "date": str(dt.date.today())}):
        done.append("wrote docs/handover.md")
    if register_project(d["name"], root, flow, product):
        done.append(f"registered {d['name']} in projects.toml (loads: {flow} flow rules)")
    todo.append("in Claude Code, run `/plugin marketplace add " + ROOT + "` once, then `/reload-plugins` (or restart) so the plugins load")
    runner = install_runner or run_plugin_install
    for p in plugins:
        if p in USER_SCOPE_PLUGINS:
            continue
        key = f"{p}@relay"
        cmd = f"claude plugin install {key} --scope project"
        if installed_for(root, key):
            done.append(f"{key} already installed")
        else:
            ok, why = runner(root, key)
            if ok:
                done.append(f"installed {key} at project scope")
            else:
                todo.append(f"{key} is enabled but not installed, so its skills are missing: after the marketplace step above, run `{cmd}` in {root}" + (f" (claude said: {why})" if why else ""))
    if apply_global:
        path, changed, removed = merge_user_settings(["core", "observe", "delegate", "front"])
        done.append(f"{path}: relay marketplace registered, user-scope plugins enabled" + ("" if changed else " (already)"))
        for r in removed:
            done.append(f"  removed a user hook the front plugin now provides: {r}")
    if relay_dir and relay_folder(root)[1]:
        done.append("wrote .relay/README.md (turns on the work queue and the merge checks once it is on the default branch)")
    return d, flow, product, done, todo


def migration_plan(root):
    """What an existing project carries from the old setup, and what relay replaces it with."""
    d = detect(root)
    name = d["name"]
    items = []
    for agent in d["agents"]:
        role = agent[len(name) + 1:] if agent.startswith(name + "-") else None
        if role in OLD_ROLES:
            target = {"ui-reviewer": "product:ui-reviewer"}.get(role, f"sdd:{role}" if d["flow"] == "openspec" else {"worker": "delegate:worker", "fixer": "delegate:fixer", "reviewer": "delegate:critic", "code-reviewer": "delegate:critic", "author": "delegate:thinker"}.get(role, "delegate:worker"))
            items.append(("agent", f".claude/agents/{agent}.md", target, f"its project-only rules go to .claude/kit/{role}.md (injected into {target})"))
    for skill in d["skills"]:
        stage = skill[len(name) + 1:] if skill.startswith(name + "-") else None
        if stage in OLD_STAGES:
            items.append(("skill", f".claude/skills/{skill}", f"sdd:{stage}", f"its project-only rules go to .claude/kit/{stage}.md"))
        if skill in ("issue-reader", "issue-creator", "issue-implementer"):
            target = {"issue-reader": "issues:read", "issue-creator": "issues:create", "issue-implementer": "issues:implement (+ issues:merge)"}[skill]
            items.append(("skill", f".claude/skills/{skill}", target, f"its project-only rules (Hard Rules, preflight script path, Forgejo specifics) go to .claude/kit/{skill.split('-')[1].replace('reader','read').replace('creator','create').replace('implementer','implement')}.md"))
    for hook in ("guard-main.sh", "opsx-stage.sh", "issue-stage.sh"):
        path = os.path.join(root, ".claude", "hooks", hook)
        if os.path.isfile(path):
            items.append(("hook", f".claude/hooks/{hook}", "core plugin", "remove its entry from .claude/settings.json (relay setup does)"))
    for script in ("packet", "spec-check"):
        if os.path.isfile(os.path.join(root, "bin", script)):
            items.append(("script", f"bin/{script}", f"kit {script}", "scripts outside Claude call bin/kit (the shim)"))
    return d, items


def migrate(root, apply=False, **kw):
    root = os.path.realpath(root)
    d, items = migration_plan(root)
    moved = []
    if apply and items:
        store = os.path.join(root, ".claude", "relay-migration")
        os.makedirs(store, exist_ok=True)
        for kind, path, _, _ in items:
            src = os.path.join(root, path)
            dst = os.path.join(store, path.lstrip(".").replace("/", "__"))
            if os.path.exists(src):
                shutil.move(src, dst)
                moved.append((path, dst))
        if not os.path.isfile(os.path.join(root, "bin", "kit")):
            shutil.copy2(os.path.join(ROOT, "plugins", "core", "templates", "kit-shim"), os.path.join(root, "bin", "kit"))
            os.chmod(os.path.join(root, "bin", "kit"), 0o755)
            moved.append(("bin/kit", "written from the shim template"))
    d2, flow, product, done, todo = setup(root, relay_dir=False, **kw)
    return d, items, moved, flow, product, done, todo


# --- doctor -----------------------------------------------------------------

def doctor(root=None, profile=None):
    checks = []

    def ok(name, good, detail=""):
        checks.append((name, bool(good), detail))

    ok("python3 3.11+", True, "")
    ok("jq on PATH", shutil.which("jq") is not None, "brew install jq" if not shutil.which("jq") else "")
    ok("claude on PATH", shutil.which("claude") is not None, "benches and evals need it" if not shutil.which("claude") else "")
    user = read_json(os.path.join(claude_dir(), "settings.json"))
    ok("relay marketplace in ~/.claude/settings.json", "relay" in user.get("extraKnownMarketplaces", {}), "relay setup --global")
    for p in ("observe", "delegate", "front", "core"):
        ok(f"{p}@relay enabled for the user", user.get("enabledPlugins", {}).get(f"{p}@relay"), "relay setup --global")
    global_md = os.path.join(claude_dir(), "CLAUDE.md")
    text = open(global_md, encoding="utf-8").read() if os.path.isfile(global_md) else ""
    ok("~/.claude/CLAUDE.md written by relay", "Generated by relay" in text, "relay sync --adopt global")
    try:
        import relay_rules
        stale = relay_rules.check(profile or {})
        ok("rules in sync", not stale, "; ".join(f"{n}" for n, _ in stale) + (" -> relay sync" if stale else ""))
    except Exception as exc:
        ok("rules in sync", False, str(exc))
    prices = read_toml(os.path.join(ROOT, "prices.toml"))
    try:
        age = (dt.date.today() - dt.date.fromisoformat(prices.get("measured", "2000-01-01"))).days
        ok("prices.toml measured within 90 days", age <= 90, f"{age} days old: re-measure (docs/observability.md)")
    except ValueError:
        ok("prices.toml has a 'measured' date", False, "")
    from relay_config import ledger_dir
    import glob
    files = sorted(glob.glob(os.path.join(ledger_dir(), "*.jsonl")))
    ok("ledger has entries", bool(files), "none yet: the observe plugin writes it once a session runs" if not files else os.path.basename(files[-1]))
    if root:
        root = os.path.realpath(root)
        d = detect(root)
        ok("project has .claude/kit.toml", d["has_bindings"], "relay setup " + root)
        cfg = d["bindings"]
        flow = cfg.get("flow", {}).get("kind", "none")
        ok(f"flow bound ({flow})", True, "")
        if flow != "none":
            manifest = flow_manifest(flow)
            ok(f"flow plugin for '{flow}' found", manifest is not None, "plugins/<plugin>/flow.json")
            if manifest:
                missing = [k for k in manifest.get("bindings_required", []) if get_dotted(cfg, k) is None]
                ok("flow bindings present", not missing, "missing: " + ", ".join(missing) if missing else "")
                enabled = d["settings"].get("enabledPlugins", {})
                not_on = [p for p in manifest.get("requires_plugins", []) if not enabled.get(f"{p}@relay")]
                ok("flow plugins enabled in .claude/settings.json", not not_on, "enable: " + ", ".join(not_on) if not_on else "")
        enabled = d["settings"].get("enabledPlugins", {})
        for key in sorted(k for k, v in enabled.items() if v):
            ok(f"{key} installed", installed_for(root, key), f"claude plugin install {key} --scope project")
        for s in ("check", "ci", "wt"):
            path = os.path.join(root, cfg.get("gate", {}).get(s, f"bin/{s}"))
            ok(f"gate.{s} exists and is executable", os.path.isfile(path) and os.access(path, os.X_OK), path)
        ok("docs/handover.md exists", d["handover"], "the front desk keeps state there")
        old = [a for a in d["agents"] if a.startswith(d["name"] + "-")]
        ok("no old prefixed agents left", not old, ", ".join(old) + " -> relay migrate --apply" if old else "")
    return checks


def get_dotted(cfg, key):
    value = cfg
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def flow_manifest(kind):
    aliases = {"openspec": "sdd"}
    plugin = aliases.get(kind, kind)
    path = os.path.join(ROOT, "plugins", plugin, "flow.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    for folder in os.listdir(os.path.join(ROOT, "plugins")):
        path = os.path.join(ROOT, "plugins", folder, "flow.json")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                m = json.load(handle)
            if m.get("kind") == kind:
                return m
    return None


def list_flows():
    out = []
    for folder in sorted(os.listdir(os.path.join(ROOT, "plugins"))):
        path = os.path.join(ROOT, "plugins", folder, "flow.json")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                out.append(json.load(handle))
    return out


# --- install and whole-machine migration --------------------------------------

def install(principles=None, run_claude=True):
    """The machine part of installing relay: global CLAUDE.md, user settings, plugins,
    and the projects known to the principles library (its projects.toml and kit drafts)."""
    import relay_rules
    import relay_config
    done, todo = [], []
    profile = relay_config.active_profile()
    results = relay_rules.sync(profile, only={"global", "agents"}, adopt="global")
    for name, path, state in results:
        done.append(f"{name}: {state} ({path})")
    path, changed, removed = merge_user_settings(["core", "observe", "delegate", "front"])
    done.append(f"{path}: relay marketplace + user-scope plugins" + ("" if changed else " (already)"))
    for r in removed:
        done.append(f"  removed a user hook the front plugin now provides: {r}")
    principles = os.path.expanduser(principles or "~/principles")
    imported = import_principles_projects(principles)
    if imported:
        done.append(f"imported {len(imported)} projects from {principles}/projects.toml: " + ", ".join(imported))
    elif os.path.isdir(principles):
        done.append(f"{principles}: no projects to import (already registered)")
    if run_claude and shutil.which("claude"):
        cmds = [["claude", "plugin", "marketplace", "add", ROOT]] + [["claude", "plugin", "install", f"{p}@relay", "--scope", "user"] for p in ("core", "observe", "delegate", "front")]
        for cmd in cmds:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                done.append(("ok   " if proc.returncode == 0 else "FAIL ") + " ".join(cmd[1:]) + ("" if proc.returncode == 0 else ": " + (proc.stderr or proc.stdout).strip().splitlines()[-1:][0] if (proc.stderr or proc.stdout).strip() else ""))
            except Exception as exc:
                done.append(f"FAIL {' '.join(cmd[1:])}: {exc}")
    else:
        todo.append(f"in Claude Code: /plugin marketplace add {ROOT}, then install core, observe, delegate, front at user scope; restart")
    link = "/usr/local/bin/relay"
    if not shutil.which("relay"):
        todo.append(f"put relay on your PATH: ln -s {os.path.join(ROOT, 'bin', 'relay')} {link} (or add {os.path.join(ROOT, 'bin')} to PATH)")
    return done, todo


def import_principles_projects(principles):
    """Register the principles library's project targets in relay's projects.toml (same shape)."""
    src = os.path.join(principles, "projects.toml")
    if not os.path.isfile(src):
        return []
    data = read_toml(src)
    dst = relay_config.projects_file()
    current = read_toml(dst) if os.path.isfile(dst) else {}
    imported = []
    with open(dst, "a", encoding="utf-8") as handle:
        for name, spec in data.items():
            if name == "global" or name in current:
                continue
            load = [m for m in spec.get("load", []) if m not in ("agents", "context-budget")]
            handle.write(f'\n[{name}]\nfile = "{spec["file"]}"\ntitle = "{spec.get("title", "Rules this project loads")}"\nload = {json.dumps(load)}\nread = []\n')
            imported.append(name)
    return imported


def known_projects():
    """(name, root) for every project target in projects.toml whose folder exists."""
    import relay_config
    path = relay_config.projects_file()
    data = read_toml(path) if os.path.isfile(path) else {}
    out = []
    for name, spec in data.items():
        if name == "global":
            continue
        root = os.path.dirname(os.path.expanduser(spec["file"]))
        out.append((name, root, os.path.isdir(root)))
    return out


def copy_kit_drafts(principles, name, root):
    """The principles library's migration/<project>/kit/*.md drafts become .claude/kit/<role>.md where absent."""
    src = os.path.join(os.path.expanduser(principles), "migration", name, "kit")
    if not os.path.isdir(src):
        return []
    dst = os.path.join(root, ".claude", "kit")
    os.makedirs(dst, exist_ok=True)
    copied = []
    for f in sorted(os.listdir(src)):
        if f.endswith(".md") and not os.path.exists(os.path.join(dst, f)):
            shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
            copied.append(f)
    kit_toml = os.path.join(os.path.expanduser(principles), "migration", name, "kit.toml")
    if os.path.isfile(kit_toml) and not os.path.isfile(bindings_path(root)):
        os.makedirs(os.path.dirname(bindings_path(root)), exist_ok=True)
        shutil.copy2(kit_toml, bindings_path(root))
        copied.append("kit.toml")
    return copied
