"""relay setup / migrate / doctor: a project onto relay, new or existing, and a check-up.

Nothing here deletes a file. Migration lists what the old setup had and what
replaces it; `--apply` moves the replaced files to .claude/relay-migration/
(so a revert is a `mv` back), never `rm`.
"""

import datetime as dt
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tomllib

import relay_config
import relay_license
from relay_config import ROOT, bindings_path, claude_dir, load_bindings, read_toml

STACKS = [
    ("bun.lock", "typescript", "bun"), ("bun.lockb", "typescript", "bun"), ("pnpm-lock.yaml", "typescript", "pnpm"),
    ("package-lock.json", "typescript", "npm"), ("yarn.lock", "typescript", "yarn"), ("mix.exs", "elixir", "mix"),
    ("Cargo.toml", "rust", "cargo"), ("go.mod", "go", "go"), ("pyproject.toml", "python", "python"),
]
OLD_ROLES = ("worker", "fixer", "author", "reviewer", "spec-reviewer", "spec-conformance", "code-reviewer", "ui-reviewer")
OLD_STAGES = ("plan", "spec-review", "parallel-apply", "apply-review", "archive")


OLD_NAMES_FILE = os.path.join(ROOT, "lib", "relay_old_names.toml")


def load_old_names(path=None):
    """The records of lib/relay_old_names.toml, checked; a file that does not fit raises ValueError naming the part."""
    with open(path or OLD_NAMES_FILE, "rb") as handle:
        data = tomllib.load(handle)
    keys = data.get("plugin_key")
    if not isinstance(keys, dict) or not keys or not all(isinstance(k, str) and isinstance(v, str) and "@" in k and "@" in v for k, v in keys.items()):
        raise ValueError("relay_old_names.toml: [plugin_key] must map 'old@market' to 'new@market'")
    flow = data.get("kit_flow")
    if not isinstance(flow, dict) or sorted(flow) != ["old_kind", "old_plugin", "specs_method"] or not all(isinstance(v, str) and v for v in flow.values()):
        raise ValueError("relay_old_names.toml: [kit_flow] needs old_kind, old_plugin, specs_method (strings)")
    names = data.get("stored_rule", {}).get("names")
    if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
        raise ValueError("relay_old_names.toml: [stored_rule] names must be a list of rule names")
    adds = data.get("addition")
    if not isinstance(adds, list) or not all(isinstance(a, dict) and sorted(a) == ["new", "old"] and all(isinstance(v, str) and v.endswith(".md") for v in a.values()) for a in adds):
        raise ValueError("relay_old_names.toml: each [[addition]] needs old and new (.md file names)")
    prefix = data.get("agent_prefix", {}).get("old")
    if not isinstance(prefix, str) or not prefix.endswith(":"):
        raise ValueError("relay_old_names.toml: [agent_prefix] old must end with ':'")
    return data


def detect(root):
    # a linked worktree is the same project as its main checkout: name it after that folder
    d = {"root": root, "name": os.path.basename(main_checkout(root) or os.path.realpath(root)), "git": os.path.isdir(os.path.join(root, ".git")) or os.path.isfile(os.path.join(root, ".git"))}
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
    cfg_specs = d["bindings"].get("specs", {}).get("method") if isinstance(d["bindings"].get("specs"), dict) else None
    d["specs_bound"] = cfg_specs if isinstance(cfg_specs, str) else None   # None: kit.toml has no [specs] setting
    if d["issue_skills"] or d["bindings"].get("issues") or os.path.isdir(os.path.join(root, ".issues")):
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


def _git_out(cwd, *args):
    """Stdout of a git command run in `cwd`, stripped; None when git fails or is missing."""
    try:
        run = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return run.stdout.strip() if run.returncode == 0 else None


def main_checkout(root):
    """The main checkout's folder when `root` is a linked git worktree of it; None for anything else (a main checkout, a submodule,
    a --separate-git-dir checkout, a bare repository, a folder outside git). A linked worktree's git dir is <common>/worktrees/<name>,
    so it differs from the common dir; the main checkout is the common dir's parent when that is a `.git` folder."""
    gitdir = _git_out(root, "rev-parse", "--path-format=absolute", "--git-dir")
    common = _git_out(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not gitdir or not common or os.path.realpath(gitdir) == os.path.realpath(common):
        return None
    if os.path.basename(os.path.realpath(common)) != ".git":
        return None
    if _git_out(root, "rev-parse", "--is-bare-repository") == "true":
        return None
    return os.path.dirname(os.path.realpath(common))


def marketplace_root():
    """The folder the relay marketplace is registered at: relay's main checkout, never a linked worktree of it (a worktree is
    removed after its merge, and every session would then load relay from nowhere)."""
    return main_checkout(ROOT) or ROOT


def backup(path):
    """Keep a copy of `path` before it is rewritten; return where it went, None when no copy was needed.
    A file in a git repository gets no `.bak` beside it (it would sit untracked among the project's files): when git holds the
    file unchanged, no copy is needed; otherwise the copy goes under the repository's git folder, relay-backup/. A file outside
    git (the user's own settings) keeps the `.bak` beside it."""
    if not os.path.isfile(path):
        return None
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = os.path.dirname(os.path.abspath(path))
    top = _git_out(folder, "rev-parse", "--show-toplevel")
    if top is not None:
        if _git_out(folder, "ls-files", "--error-unmatch", "--", path) is not None and _git_out(folder, "diff", "--quiet", "HEAD", "--", path) is not None:
            return None   # tracked and equal to HEAD: git already holds this exact file
        gitdir = _git_out(folder, "rev-parse", "--path-format=absolute", "--git-dir")
        if gitdir:
            rel = os.path.relpath(os.path.realpath(path), os.path.realpath(top)).replace(os.sep, "__")
            dest = os.path.join(gitdir, "relay-backup", f"{rel}.{stamp}.bak")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(path, dest)
            return dest
    shutil.copy2(path, f"{path}.{stamp}.bak")
    return f"{path}.{stamp}.bak"


# --- bindings ---------------------------------------------------------------

def bindings_text(d, flow, product, specs="none"):
    """A kit.toml for a new project; sections relay needs, with the detected values."""
    name, stack = d["name"], d["stack"]
    skills = {"typescript": '["ts-dev"]', "rust": '["rust-dev"]', "elixir": '["elixir-dev"]', "go": '["go-dev"]'}.get(stack, "[]")
    lines = [
        f"# {name}: bindings for the relay plugins (written by `relay setup`, {dt.date.today()}).",
        "# Every key is documented in plugins/core/README.md (gate, product, packet, guard)",
        "# and docs/flows.md ([flow], [issues]); [delegate] and [observe] in docs/delegation.md.", "",
        "[project]", f'name = "{name}"', f'default_branch = "{d["default_branch"]}"', 'worktrees = ".worktrees"',
        f"stack_skills = {skills}", "",
        "[gate]", 'wt = "bin/wt"', 'check = "bin/check"', 'ci = "bin/ci"', 'ci_log = ".ci/ci.log"', 'final = "local"', "",
        "[flow]", f'kind = "{flow}"', "",
        "[specs]", f'method = "{specs}"   # "none", or a spec method plugin such as "openspec" (docs/flows.md)', "",
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


def set_specs(root, method):
    """Write [specs] method in kit.toml: replace the line when the section is there, else add the section."""
    path = bindings_path(root)
    text = open(path, encoding="utf-8").read()
    lines = text.split("\n")
    out, section, seen_section, written = [], None, False, False
    for line in lines:
        m = re.match(r"\s*\[([^\]]+)\]", line)
        if m:
            if section == "specs" and not written:
                out.append(f'method = "{method}"')
                written = True
            section = m.group(1).strip()
            seen_section = seen_section or section == "specs"
        elif section == "specs" and re.match(r"\s*method\s*=", line):
            line, written = f'method = "{method}"', True
        out.append(line)
    if section == "specs" and not written:
        while out and out[-1] == "":
            out.pop()
        out += [f'method = "{method}"', ""]
        written = True
    new = "\n".join(out)
    if not seen_section:
        new = text.rstrip("\n") + f'\n\n[specs]\nmethod = "{method}"\n'
    if new != text:
        backup(path)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(new)
        return True
    return False


def set_license(root, license_id, holder, todo):
    """`setup --license`: relay license add (LICENSE, LICENSES/, REUSE.toml, kit.toml [license]); the lines for the done list.
    A different existing file is kept and goes to the to-do list. The gate runs the check; bin/check is not touched."""
    try:
        return relay_license.add(root, license_id, holder)
    except relay_license.Refused as exc:
        todo.append(str(exc))
        return []


def merge_bindings(root, flow, specs="none", force_specs=False):
    """Add the relay sections a kit.toml lacks, without touching what is there. `force_specs` rewrites an existing [specs] method."""
    path = bindings_path(root)
    text = open(path, encoding="utf-8").read()
    cfg = tomllib.loads(text)
    added = []
    blocks = {
        "flow": f'\n[flow]\nkind = "{flow}"\n',
        "specs": f'\n[specs]\nmethod = "{specs}"\n',
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
    if force_specs and "specs" not in added and set_specs(root, specs):
        added.append("specs method")
    return added


def migrate_kit_toml(root, names=None):
    """The old [flow] forms in kit.toml (relay_old_names.toml [kit_flow]) onto the current ones; the lines it did, [] when none."""
    names = names or load_old_names()["kit_flow"]
    path = bindings_path(root)
    if not os.path.isfile(path):
        return []
    text = open(path, encoding="utf-8").read()
    out, section, did, kind_was_old = [], None, [], False
    for line in text.split("\n"):
        m = re.match(r"\s*\[([^\]]+)\]", line)
        if m:
            section = m.group(1).strip()
        elif section == "flow" and re.match(r'\s*kind\s*=\s*"' + re.escape(names["old_kind"]) + r'"', line):
            out.append(re.sub(r'"[^"]*"', '"none"', line, count=1))
            did.append(f'[flow] kind = "{names["old_kind"]}" -> "none"')
            kind_was_old = True
            continue
        elif section == "flow" and re.match(r'\s*plugin\s*=\s*"' + re.escape(names["old_plugin"]) + r'"', line):
            did.append(f'[flow] plugin = "{names["old_plugin"]}" removed')
            continue
        out.append(line)
    if not did:
        return []
    new = "\n".join(out)
    if kind_was_old and "specs" not in tomllib.loads(text):
        new = new.rstrip("\n") + f'\n\n[specs]\nmethod = "{names["specs_method"]}"\n'
        did.append(f'[specs] method = "{names["specs_method"]}" added (the project had the spec steps on)')
    backup(path)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(new)
    return did


# --- settings ---------------------------------------------------------------

def relay_plugins_for(flow, specs, product):
    plugins = ["core", "observe", "delegate", "front"]
    if specs and specs != "none" and os.path.isdir(os.path.join(ROOT, "plugins", specs)):
        plugins.append(specs)
    if flow == "issues":
        plugins.append("issues")
    if product:
        plugins.append("product")
    return plugins


def names_moved_hook(command, moved):
    """True when `command` runs one of the project hook files `moved` (paths like ".claude/hooks/issue-stage.sh") as migrate wrote
    it: `"$CLAUDE_PROJECT_DIR"/<path>`, `./<path>` or `<path>`, with or without arguments. A home-folder or other path is not."""
    words = command.replace('"', "").replace("'", "").split()
    if not words:
        return False
    first = words[0]
    for prefix in ("$CLAUDE_PROJECT_DIR/", "${CLAUDE_PROJECT_DIR}/", "./"):
        if first.startswith(prefix):
            first = first[len(prefix):]
            break
    return first in moved


def merge_settings(root, plugins, remove=(), moved_hooks=()):
    """Enable `plugins`; drop the principles marketplace, the old plugin keys and the `remove` keys. `moved_hooks`: project hook paths
    migrate moved aside in this run; only the commands that run them are dropped."""
    path = os.path.join(root, ".claude", "settings.json")
    data = read_json(path)
    before = json.dumps(data, sort_keys=True)
    enabled = data.setdefault("enabledPlugins", {})
    gone = set(load_old_names()["plugin_key"]) | set(remove)
    for key in list(enabled):
        if key.endswith("@principles") or key in gone:
            enabled.pop(key)   # the principles marketplace is replaced by relay; old and turned-off plugin keys go
    for p in plugins:
        enabled[f"{p}@relay"] = True
    markets = data.setdefault("extraKnownMarketplaces", {})
    markets["relay"] = {"source": {"source": "directory", "path": marketplace_root()}}
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
                continue
            entries = group.get("hooks", [])
            stay = [h for h in entries if not names_moved_hook(h.get("command", ""), moved_hooks)]
            for h in entries:
                if h not in stay:
                    removed.append(f"{event}: {h.get('command', '')}")
            if stay or not entries:
                kept.append(group if len(stay) == len(entries) else {**group, "hooks": stay})
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


def global_problem():
    """Why the user's settings do not hold relay's marketplace at relay's main checkout, None when they do."""
    user = read_json(os.path.join(claude_dir(), "settings.json"))
    entry = user.get("extraKnownMarketplaces", {}).get("relay")
    if not entry:
        return "the relay marketplace is not in ~/.claude/settings.json"
    path = entry.get("source", {}).get("path") if isinstance(entry, dict) and isinstance(entry.get("source"), dict) else None
    if not isinstance(path, str) or not os.path.isdir(path):
        return f"the relay marketplace path {path!r} in ~/.claude/settings.json does not exist"
    if os.path.realpath(path) != os.path.realpath(marketplace_root()):
        return f"the relay marketplace path {path} in ~/.claude/settings.json is not relay's main checkout {marketplace_root()}"
    return None


def merge_user_settings(plugins):
    """~/.claude/settings.json: the relay marketplace and the user-scope plugins (observe, delegate, front, core)."""
    path = os.path.join(claude_dir(), "settings.json")
    data = read_json(path)
    before = json.dumps(data, sort_keys=True)
    data.setdefault("extraKnownMarketplaces", {})["relay"] = {"source": {"source": "directory", "path": marketplace_root()}}
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


SESSION_KEYS = {"model": "model", "effort": "effortLevel"}   # profile [session] key -> user settings key
OWNED_ENV = {"CLAUDE_CODE_RETRY_WATCHDOG": "1"}   # env keys relay adds to the user settings: a session waits through a network drop
PERSISTABLE_EFFORTS = ("low", "medium", "high", "xhigh")   # Claude Code drops any other persisted effortLevel; max is session-only


def session_settings(profile):
    """The top-level user settings keys the profile's [session] sets: model and effortLevel (only a persistable effort)."""
    session = profile.get("session", {})
    out = {SESSION_KEYS[k]: session[k] for k in SESSION_KEYS if session.get(k)}
    if out.get("effortLevel") not in PERSISTABLE_EFFORTS:
        out.pop("effortLevel", None)
    return out


def unpersistable_effort(profile):
    """The profile's [session] effort when Claude Code cannot keep it in settings.json (e.g. max), else None."""
    effort = profile.get("session", {}).get("effort")
    return effort if effort and effort not in PERSISTABLE_EFFORTS else None


def effort_model_key(data, model):
    """The modelSettings key Claude Code reads the effort of the profile's model from (it wins over top-level effortLevel).
    A full id is its own key; an alias ("opus") is the one existing key naming that family; None when no entry exists yet.
    Raises ValueError when several keys match."""
    if not model:
        return None
    if model.startswith("claude-"):
        return model
    found = [k for k in data.get("modelSettings", {}) if model in k.split("-")]
    if len(found) > 1:
        raise ValueError(f"modelSettings has several entries for {model!r}: {', '.join(sorted(found))}")
    return found[0] if found else None


def missing_env(data: dict) -> dict[str, str]:
    """The OWNED_ENV keys absent from the settings env. A key present with any value is the owner's and is left alone."""
    env = data.get("env")
    env = env if isinstance(env, dict) else {}
    return {k: v for k, v in OWNED_ENV.items() if k not in env}


def read_json_strict(path):
    """(data, error): a missing file is ({}, None); invalid JSON or a non-object is ({}, reason)."""
    if not os.path.exists(path):
        return {}, None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        return {}, f"{os.path.basename(path)} is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return {}, f"{os.path.basename(path)} is not a JSON object"
    return data, None


def merge_session_settings(profile: dict, dry: bool = False) -> tuple[str, str]:
    """Write the profile's [session] model and effort into ~/.claude/settings.json, other keys untouched: the top-level
    keys and modelSettings.<model>.effortLevel (the entry Claude Code reads first). Returns (path, state): unchanged,
    would set/set <keys>, not written (max), or refused/would refuse when the file is not valid JSON. dry: write nothing."""
    path = os.path.join(claude_dir(), "settings.json")
    data, error = read_json_strict(path)
    if error:
        return path, ("would refuse: " if dry else "refused: ") + error
    wanted = session_settings(profile)
    changes = {k: v for k, v in wanted.items() if data.get(k) != v}
    names = [f"{k} {data.get(k)!r} -> {v!r}" for k, v in sorted(changes.items())]
    effort = wanted.get("effortLevel")
    per_model = None
    if effort:
        try:
            key = effort_model_key(data, profile["session"].get("model"))
        except ValueError as exc:
            return path, ("would refuse: " if dry else "refused: ") + str(exc)
        if key:
            old = data.get("modelSettings", {}).get(key, {}).get("effortLevel")
            if old != effort:
                per_model = (key, effort)
                names.append(f"modelSettings.{key}.effortLevel {old!r} -> {effort!r}")
    notes = []
    add_env = missing_env(data)
    if "env" in data and not isinstance(data["env"], dict):
        add_env = {}
        notes.append("env is not an object: watchdog not written")
    names += [f"env.{k} -> {v!r}" for k, v in sorted(add_env.items())]
    bad = unpersistable_effort(profile)
    if bad:
        notes.append(f"not written: effort {bad} is session-only")
    if not names:
        return path, "; ".join(["unchanged"] + notes) if not notes else "; ".join(notes)
    if not dry:
        data.update(changes)
        if add_env:
            data.setdefault("env", {}).update(add_env)
        if per_model:
            data.setdefault("modelSettings", {}).setdefault(per_model[0], {})["effortLevel"] = per_model[1]
        backup(path)
        write_json(path, data)
    return path, ("would set " if dry else "set ") + ", ".join(names) + "".join("; " + n for n in notes)


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


def strip_stored_spec_rules(name):
    """Remove spec-rule entries from the stored `load` of [name] in projects.toml (spec rules come from kit.toml [specs]); True when changed."""
    path = relay_config.projects_file()
    if not os.path.isfile(path):
        return False
    stored = load_old_names()["stored_rule"]["names"]
    lines = open(path, encoding="utf-8").read().split("\n")
    section, changed = None, False
    for i, line in enumerate(lines):
        m = re.match(r"\s*\[([^\]]+)\]", line)
        if m:
            section = m.group(1).strip()
        elif section == name and re.match(r"\s*load\s*=\s*\[", line):
            head, _, rest = line.partition("=")
            body, _, comment = rest.partition("]")
            try:
                current = json.loads(body.strip() + "]")
            except ValueError:
                return False
            kept = [r for r in current if r not in stored]
            if kept != current:
                lines[i] = f"{head}= {json.dumps(kept)}{comment}"
                changed = True
    if changed:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
    return changed


def register_project(name, root, flow, product, specs="none"):
    """Add the project to projects.toml so `relay sync` writes its CLAUDE.local.md."""
    path = relay_config.projects_file()
    text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    data = tomllib.loads(text) if text else {}
    if name in data:
        return False
    load = []
    if flow == "issues" or specs != "none":
        load += ["quality-gate"]   # spec rules are not stored here: relay sync derives them from kit.toml [specs]
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


def run_plugin_uninstall(root, key):
    """Real uninstall runner: (ok, detail), the same binary as the install runner."""
    cmd = [os.environ.get("RELAY_CLAUDE_BIN") or "claude", "plugin", "uninstall", key, "--scope", "project"]
    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return proc.returncode == 0, (proc.stderr or proc.stdout).strip()


def project_installed(root, key):
    """Is plugin `key` installed at project scope for the project at `root`?"""
    reg = read_json(os.path.join(relay_config.claude_dir(), "plugins", "installed_plugins.json"))
    entries = reg.get("plugins", {}).get(key, [])
    root = os.path.realpath(root)
    return any(e.get("scope") == "project" and e.get("projectPath") and os.path.realpath(e["projectPath"]) == root
               for e in (entries if isinstance(entries, list) else []) if isinstance(e, dict))


def setup(root, flow=None, product=None, relay_dir=True, install_runner=None, specs=None, uninstall_runner=None,
          moved_hooks=(), license_id=None, holder=None):
    """Set one project up. `relay_dir=False` leaves `.relay/` out: `migrate` (even as a plan) must not turn the work queue and the
    merge checks on in a project the owner has not chosen (docs/setup.md: old projects are not given a .relay/ folder)."""
    import relay_rules
    root = os.path.realpath(root)
    names = load_old_names()
    methods = relay_rules.spec_methods()
    if flow == "openspec":
        raise ValueError("spec steps are their own setting now: use --specs openspec")
    if specs is not None and specs != "none" and specs not in methods:
        raise ValueError(f"no spec method named '{specs}' (spec methods: {', '.join(sorted(methods)) or 'none'})")
    if license_id is not None:
        if not holder:
            raise ValueError("--license needs --holder <name>")
        relay_license.license_text(license_id, holder, 2000)   # refuses an unknown id or a missing holder before anything is written
    d = detect(root)
    done, todo = [], []
    if d["has_bindings"]:
        for line in migrate_kit_toml(root, names["kit_flow"]):
            done.append(f"kit.toml: {line}")
        d = detect(root)
    flow = flow or d["flow"]
    product = d["ui"] if product is None else product
    explicit = specs is not None
    auto_on = False
    if specs is None:
        specs = d["specs_bound"]
        if specs is None:
            specs = "openspec" if d["openspec"] and "openspec" in methods else "none"
            auto_on = specs != "none"
    if not d["git"]:
        todo.append("the folder is not a git repository: `git init` first; relay's worktree rules need it")
    if d["has_bindings"]:
        added = merge_bindings(root, flow, specs, force_specs=explicit)
        done.append(f"kept .claude/kit.toml; added sections: {', '.join(added) or 'none needed'}")
    else:
        os.makedirs(os.path.join(root, ".claude"), exist_ok=True)
        with open(bindings_path(root), "w", encoding="utf-8") as handle:
            handle.write(bindings_text(d, flow, product, specs))
        done.append("wrote .claude/kit.toml (check the [gate] commands and, for issues, the [issues] commands)")
    if auto_on:
        done.append(f"spec steps are ON for this project because it has an openspec/ folder; turn them off with `relay setup {root} --specs none`")
    plugins = relay_plugins_for(flow, specs, product)
    turned_off = [f"{m}@relay" for m in methods if m != specs]
    changed, removed = merge_settings(root, plugins, remove=turned_off, moved_hooks=moved_hooks)
    done.append(f".claude/settings.json: plugins {', '.join(p + '@relay' for p in plugins)} enabled" + (" (unchanged)" if not changed else ""))
    for r in removed:
        done.append(f"  removed a hook the plugins now provide: {r}")
    unrunner = uninstall_runner or run_plugin_uninstall
    for key in sorted(set(names["plugin_key"]) | set(turned_off)):
        if project_installed(root, key):
            ok, why = unrunner(root, key)
            if ok:
                done.append(f"uninstalled {key} at project scope")
            else:
                todo.append(f"{key} is still installed: run `claude plugin uninstall {key} --scope project` in {root}" + (f" (claude said: {why})" if why else ""))
    for script in ("check", "ci", "wt"):
        if not d["scripts"][script]:
            if copy_template(f"bin-{script}", os.path.join(root, "bin", script), mode_exec=True, replacements={"tool": d["tool"], "stack": d["stack"], "branch": d["default_branch"]}):
                done.append(f"wrote bin/{script} from the template")
                todo.append(f"bin/{script}: fill in the {d['stack']} commands where it says TODO (the contract is in plugins/core/README.md)")
    if license_id is not None:
        done += set_license(root, license_id, holder, todo)
    if copy_template("CLAUDE.md", os.path.join(root, "CLAUDE.md"), replacements={"name": d["name"], "stack": d["stack"]}):
        done.append("wrote CLAUDE.md (a skeleton: what the product is, the commands, the product surface)")
        todo.append("CLAUDE.md: write what the project is in two lines, and its product surface if a person sees it")
    if copy_template("handover.md", os.path.join(root, "docs", "handover.md"), replacements={"name": d["name"], "date": str(dt.date.today())}):
        done.append("wrote docs/handover.md")
    if register_project(d["name"], main_checkout(root) or root, flow, product, specs):
        done.append(f"registered {d['name']} in projects.toml (loads: {flow} flow rules)")
    if strip_stored_spec_rules(d["name"]):
        done.append(f"projects.toml [{d['name']}]: removed the stored spec rule from load (it comes from kit.toml [specs])")
    todo.append("in Claude Code, run `/plugin marketplace add " + marketplace_root() + "` once, then `/reload-plugins` (or restart) so the plugins load")
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
    problem = global_problem()
    if problem:   # a project setup never writes the user's files (owner's decision, 26 Oct): it says which command does
        todo.append(f"{problem}: run `relay setup --global` once on this machine")
    if relay_dir and relay_folder(root)[1]:
        done.append("wrote .relay/README.md (turns on the work queue and the merge checks once it is on the default branch)")
    return d, flow, product, done, todo


NO_TARGET = "no target: spec steps are off"


def effective_specs(d):
    """The spec method a project runs after its kit.toml is migrated: [specs] method, else on for an old [flow] kind or an openspec/ folder."""
    if d["specs_bound"] is not None:
        return d["specs_bound"]
    old = load_old_names()["kit_flow"]
    if d["bindings"].get("flow", {}).get("kind") == old["old_kind"] or d["openspec"]:
        return old["specs_method"]
    return "none"


def migration_plan(root):
    """What an existing project carries from the old setup, and what relay replaces it with."""
    d = detect(root)
    name = d["name"]
    specs_on = effective_specs(d) != "none"
    items = []
    for agent in d["agents"]:
        role = agent[len(name) + 1:] if agent.startswith(name + "-") else None
        if role in OLD_ROLES:
            if role == "ui-reviewer":
                target = "product:ui-reviewer"
            elif role in ("spec-reviewer", "spec-conformance"):
                target = f"openspec:{role}" if specs_on else NO_TARGET
            elif role == "author":
                target = "openspec:author" if specs_on else "delegate:thinker"
            else:
                target = {"worker": "delegate:worker", "fixer": "delegate:fixer", "reviewer": "delegate:critic", "code-reviewer": "delegate:critic"}[role]
            note = f"its project-only rules go to .claude/kit/{role}.md (injected into {target})" if target != NO_TARGET else "kept in .claude/relay-migration; nothing runs it while spec steps are off"
            items.append(("agent", f".claude/agents/{agent}.md", target, note))
    for skill in d["skills"]:
        stage = skill[len(name) + 1:] if skill.startswith(name + "-") else None
        if stage in OLD_STAGES:
            if stage == "parallel-apply":
                items.append(("skill", f".claude/skills/{skill}", "the change cycle's step 2", "its project-only rules go to .claude/kit/worker.md"))
            elif stage == "apply-review":
                items.append(("skill", f".claude/skills/{skill}", "the change cycle's step 4", "its project-only rules go to .claude/kit/critic.md"))
            elif specs_on:
                items.append(("skill", f".claude/skills/{skill}", f"openspec:{stage}", f"its project-only rules go to .claude/kit/{stage}.md"))
            else:
                items.append(("skill", f".claude/skills/{skill}", NO_TARGET, "kept in .claude/relay-migration; nothing runs it while spec steps are off"))
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
    hooks_moved = tuple(path for path, _ in moved if path.startswith(".claude/hooks/"))
    d2, flow, product, done, todo = setup(root, relay_dir=False, moved_hooks=hooks_moved, **kw)
    return d, items, moved, flow, product, done, todo


# --- dependencies: deps.toml is read here and by install.sh ------------------

DEPS_FILE = os.path.join(ROOT, "deps.toml")
DEP_STRINGS = ("name", "command", "min", "version_arg", "brew", "apt", "uv_tool", "uv_python", "darwin_run", "installer_url",
               "installer_sha256", "official_url", "official_shell", "manual", "why")
DEP_ROUTES = ("brew", "apt", "uv_tool", "uv_python", "darwin_run", "installer_url", "official_url", "manual")   # at least one way to install it
RELEASE_KEY = re.compile(r"release_(url|sha256)_(darwin|linux)_(arm64|x86_64|aarch64)")


def platform_key(system=None, machine=None):
    """'darwin_arm64', 'linux_x86_64': the suffix of the release_* fields for this machine."""
    system = system or sys.platform
    return ("darwin" if system == "darwin" else "linux") + "_" + (machine or platform.machine())


def load_deps(path=None):
    """The entries of deps.toml, checked; a file that does not fit raises ValueError naming the entry."""
    with open(path or DEPS_FILE, "rb") as handle:
        data = tomllib.load(handle)
    entries = data.get("dep")
    if not isinstance(entries, list) or not entries:
        raise ValueError("deps.toml: no [[dep]] entries")
    seen = set()
    for n, dep in enumerate(entries, 1):
        label = f"deps.toml entry {n} ({dep.get('name', '?')})"
        for key in dep:
            if key not in DEP_STRINGS and key != "exact" and not RELEASE_KEY.fullmatch(key):
                raise ValueError(f"{label}: unknown field '{key}'")
        for key in ("name", "command", "version_arg"):
            if not isinstance(dep.get(key), str) or not dep[key]:
                raise ValueError(f"{label}: '{key}' must be a non-empty string")
        for key in dep:
            if key != "exact" and not isinstance(dep[key], str):
                raise ValueError(f"{label}: '{key}' must be a string")
        if "min" in dep and not re.fullmatch(r"\d+(\.\d+)*", dep["min"]):
            raise ValueError(f"{label}: 'min' must be dotted numbers")
        if "exact" in dep and (dep["exact"] is not True or "min" not in dep):
            raise ValueError(f"{label}: 'exact' is true and needs 'min'")
        if ("installer_url" in dep) != ("installer_sha256" in dep):
            raise ValueError(f"{label}: 'installer_url' and 'installer_sha256' go together")
        for key in dep:
            m = RELEASE_KEY.fullmatch(key)
            if m and m.group(1) == "url" and "release_sha256_" + key[len("release_url_"):] not in dep:
                raise ValueError(f"{label}: '{key}' needs its release_sha256 checksum")
            if m and m.group(1) == "sha256" and "release_url_" + key[len("release_sha256_"):] not in dep:
                raise ValueError(f"{label}: '{key}' needs its release_url")
        if not any(r in dep for r in DEP_ROUTES) and not any(RELEASE_KEY.fullmatch(k) for k in dep):
            raise ValueError(f"{label}: no way to install it ({', '.join(DEP_ROUTES)}, release_url_*)")
        if dep["name"] in seen:
            raise ValueError(f"{label}: name listed twice")
        seen.add(dep["name"])
    return entries


def version_tuple(text):
    return tuple(int(x) for x in text.split("."))


def dep_version(dep):
    """The version the tool prints, as a tuple; None when it prints none or cannot run."""
    exe = shutil.which(dep["command"])
    if exe is None:
        return None
    try:
        done = subprocess.run([exe, dep["version_arg"]], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = re.search(r"\d+(?:\.\d+)+", done.stdout + done.stderr)
    return version_tuple(found.group(0)) if found else None


def install_hint(dep, system=None, machine=None):
    """The route install.sh takes, in its order: the official one first, Homebrew/apt only as the fallback."""
    system = system or sys.platform
    if "uv_tool" in dep:
        return "uv tool install " + dep["uv_tool"]
    if "uv_python" in dep:
        return "uv python install " + dep["uv_python"]
    if "darwin_run" in dep and system == "darwin":
        return dep["darwin_run"]
    key = platform_key(system, machine)
    if "release_url_" + key in dep:
        return f"sh {os.path.join(ROOT, 'install.sh')} (downloads {dep['release_url_' + key]}, checks its sha256)"
    if "installer_url" in dep:
        return f"sh {os.path.join(ROOT, 'install.sh')} (downloads {dep['installer_url']}, checks its sha256)"
    if "official_url" in dep:
        return f"curl -fsSL {dep['official_url']} | {dep.get('official_shell', 'sh')}"
    if "apt" in dep and system.startswith("linux"):
        return "sudo apt-get install -y " + dep["apt"]
    if "brew" in dep and system == "darwin":
        return "brew install " + dep["brew"]
    if "manual" in dep:
        return dep["manual"]
    return "sh " + os.path.join(ROOT, "install.sh")


def dep_checks(deps=None):
    """One (name, good, detail) per entry of deps.toml: on PATH, and the version at least the minimum (exactly it for a pin)."""
    try:
        deps = deps if deps is not None else load_deps()
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        return [("deps.toml readable", False, str(exc))]
    checks = []
    for dep in deps:
        exact = dep.get("exact") is True
        if "min" not in dep:
            name = f"{dep['name']} on PATH"
        else:
            name = f"{dep['name']} {dep['min']}" + (" (pinned)" if exact else "+")
        found = dep_version(dep)
        if shutil.which(dep["command"]) is None:
            good, why = False, "not found"
        elif found is None:   # on PATH but it prints no version: a stub (macOS git without the developer tools) or broken
            good, why = False, "version not readable" if "min" in dep else "found but not working (prints no version)"
        elif "min" not in dep:
            good, why = True, ""
        else:
            want = version_tuple(dep["min"])
            good = found == want if exact else found >= want
            why = "found " + ".".join(map(str, found))
        detail = ""
        if not good:
            detail = f"{why}; {install_hint(dep)}" + (f"; {dep['why']}" if dep.get("why") else "")
        checks.append((name, good, detail))
    return checks


# --- doctor -----------------------------------------------------------------

def doctor(root: str | None = None, profile: dict | None = None) -> list[tuple[str, bool, str]]:
    checks = []

    def ok(name, good, detail=""):
        checks.append((name, bool(good), detail))

    checks.extend(dep_checks())
    user = read_json(os.path.join(claude_dir(), "settings.json"))
    ok("relay marketplace in ~/.claude/settings.json", "relay" in user.get("extraKnownMarketplaces", {}), "relay setup --global")
    problem = global_problem()
    ok("relay marketplace in ~/.claude/settings.json is relay's main checkout", problem is None, f"{problem} -> relay setup --global")
    for p in ("observe", "delegate", "front", "core"):
        ok(f"{p}@relay enabled for the user", user.get("enabledPlugins", {}).get(f"{p}@relay"), "relay setup --global")
    global_md = os.path.join(claude_dir(), "CLAUDE.md")
    text = open(global_md, encoding="utf-8").read() if os.path.isfile(global_md) else ""
    for key, want in sorted(session_settings(profile or {}).items()):
        ok(f"{key} in ~/.claude/settings.json is the profile's [session] {want}", user.get(key) == want,
           f"is {user.get(key)!r} -> relay sync")
    for key in sorted(OWNED_ENV):
        ok(f"{key} in the env of ~/.claude/settings.json", key not in missing_env(user),
           "env is not an object: fix it by hand" if "env" in user and not isinstance(user["env"], dict)
           else "missing -> relay sync")
    bad = unpersistable_effort((profile or {}))
    if bad:
        ok(f"effortLevel in ~/.claude/settings.json can hold the profile's [session] effort {bad}", False,
           f"{bad} is session-only: Claude Code does not keep it; pick low, medium, high or xhigh")
    want_effort = session_settings(profile or {}).get("effortLevel")
    if want_effort:
        try:
            mkey = effort_model_key(user, (profile or {})["session"].get("model"))
        except ValueError as exc:
            ok("modelSettings has one entry for the profile's model", False, str(exc))
        else:
            if mkey:
                have = user.get("modelSettings", {}).get(mkey, {}).get("effortLevel")
                ok(f"modelSettings.{mkey}.effortLevel is the profile's [session] {want_effort}", have == want_effort,
                   f"is {have!r} -> relay sync")
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
        old = load_old_names()
        old_flow = old["kit_flow"]
        enabled = d["settings"].get("enabledPlugins", {})
        stale_keys = [k for k in old["plugin_key"] if enabled.get(k)]
        ok("no old binding", flow != old_flow["old_kind"] and cfg.get("flow", {}).get("plugin") != old_flow["old_plugin"] and not stale_keys,
           "old binding: " + ", ".join(([f'[flow] kind = "{flow}"'] if flow == old_flow["old_kind"] else []) + ([f'[flow] plugin = "{old_flow["old_plugin"]}"'] if cfg.get("flow", {}).get("plugin") == old_flow["old_plugin"] else []) + stale_keys) + f" -> relay setup {root}")
        ok(f"flow bound ({flow})", True, "")
        if flow not in ("none", old_flow["old_kind"]):
            manifest = flow_manifest(flow)
            ok(f"flow plugin for '{flow}' found", manifest is not None, "plugins/<plugin>/flow.json")
            if manifest:
                missing = [k for k in manifest.get("bindings_required", []) if get_dotted(cfg, k) is None]
                ok("flow bindings present", not missing, "missing: " + ", ".join(missing) if missing else "")
                not_on = [p for p in manifest.get("requires_plugins", []) if not enabled.get(f"{p}@relay")]
                ok("flow plugins enabled in .claude/settings.json", not not_on, "enable: " + ", ".join(not_on) if not_on else "")
        import relay_rules
        methods = relay_rules.spec_methods()
        method = d["specs_bound"] or "none"
        if method == "none":
            ok("spec steps off", True, "")
        else:
            ok(f"spec method '{method}' known", method in methods, f"[specs] method = {method}: no spec method of that name (`relay flows` lists them)")
        for m in sorted(methods):
            on, wanted = bool(enabled.get(f"{m}@relay")), method == m
            if on != wanted:
                ok(f"spec steps and {m}@relay agree", False,
                   f"spec steps are {'`' + m + '`' if wanted else 'not `' + m + '`'} but {m}@relay is {'not enabled' if wanted else 'enabled'}: relay setup {root} --specs {m if wanted else 'none'}")
        stored = [r for r in (relay_rules.targets().get(d["name"], {}).get("load", [])) if r in old["stored_rule"]["names"] or r in methods]
        ok("no stored spec rule in projects.toml", not stored,
           f"projects.toml [{d['name']}] load names {', '.join(stored)}: spec rules come from kit.toml [specs]; run relay setup {root}")
        gone = [a["old"] for a in old["addition"] if os.path.isfile(os.path.join(root, ".claude", "kit", a["old"]))]
        ok("no addition for a removed stage", not gone,
           "addition for a removed stage: " + ", ".join(f"{a['old']} (move its rules to .claude/kit/{a['new']})" for a in old["addition"] if a["old"] in gone))
        ok("no file names the old plugin", not names_old_plugin(root, old["agent_prefix"]["old"]), "names the old plugin: " + "; ".join(names_old_plugin(root, old["agent_prefix"]["old"])[:5]))
        enabled = d["settings"].get("enabledPlugins", {})
        for key in sorted(k for k, v in enabled.items() if v):
            ok(f"{key} installed", installed_for(root, key), f"claude plugin install {key} --scope project")
        for s in ("check", "ci", "wt"):
            path = os.path.join(root, cfg.get("gate", {}).get(s, f"bin/{s}"))
            ok(f"gate.{s} exists and is executable", os.path.isfile(path) and os.access(path, os.X_OK), path)
        ok("docs/handover.md exists", d["handover"], "the front desk keeps state there")
        old_agents = [a for a in d["agents"] if a.startswith(d["name"] + "-")]
        ok("no old prefixed agents left", not old_agents, ", ".join(old_agents) + " -> relay migrate --apply" if old_agents else "")
    for line in unshipped_installs():
        ok("installed plugin still shipped", False, line)
    return checks


def names_old_plugin(root, prefix):
    """file:line of project files (.claude/, CLAUDE.md, CLAUDE.local.md) that name an agent or skill of the old plugin."""
    found = []
    pattern = re.compile(r"(?<![\w-])" + re.escape(prefix))
    paths = [os.path.join(root, "CLAUDE.md"), os.path.join(root, "CLAUDE.local.md")]
    for folder, _, files in os.walk(os.path.join(root, ".claude")):
        if "relay-migration" in folder:
            continue
        paths += [os.path.join(folder, f) for f in files if f.endswith((".md", ".toml", ".json"))]
    for path in sorted(paths):
        try:
            for n, line in enumerate(open(path, encoding="utf-8"), 1):
                if pattern.search(line):
                    found.append(f"{os.path.relpath(path, root)}:{n}")
        except (OSError, UnicodeDecodeError):
            continue
    return found


def unshipped_installs():
    """One line per project-scope install of a relay plugin the marketplace no longer ships (a rename or a removal)."""
    shipped = set(os.listdir(os.path.join(ROOT, "plugins")))
    reg = read_json(os.path.join(claude_dir(), "plugins", "installed_plugins.json")).get("plugins", {})
    lines = []
    for key, entries in sorted(reg.items()):
        plugin, _, market = key.partition("@")
        if market != "relay" or plugin in shipped:
            continue
        for e in entries if isinstance(entries, list) else []:
            if isinstance(e, dict) and e.get("scope") == "project" and e.get("projectPath"):
                lines.append(f"{key} installed for {e['projectPath']}: run relay setup {e['projectPath']}")
    return lines


def get_dotted(cfg, key):
    value = cfg
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def flow_manifest(kind):
    """The flow.json of the plugin named `kind`, else of the plugin whose manifest says that kind."""
    path = os.path.join(ROOT, "plugins", kind, "flow.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    for folder in sorted(os.listdir(os.path.join(ROOT, "plugins"))):
        path = os.path.join(ROOT, "plugins", folder, "flow.json")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                m = json.load(handle)
            if m.get("kind") == kind:
                return m
    return None


def list_flows():
    """Every manifest with its plugin folder, work flows first then spec methods (by slot)."""
    out = []
    for folder in sorted(os.listdir(os.path.join(ROOT, "plugins"))):
        path = os.path.join(ROOT, "plugins", folder, "flow.json")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                m = json.load(handle)
            out.append(dict(m, plugin=folder))
    return sorted(out, key=lambda m: (m.get("slot") != "work", m["plugin"]))


# --- install and whole-machine migration --------------------------------------

def install(run_claude=True):
    """The machine part of installing relay: global CLAUDE.md, user settings, plugins.
    It registers no project; `relay setup <dir>` adds one."""
    import relay_rules
    import relay_config
    done, todo = [], []
    profile = relay_config.active_profile()
    results = relay_rules.sync(profile, only={"global", "agents", "settings"}, adopt="global", wait=False)   # install renders the head the owner chose; a fresh machine has no green record
    for name, path, state in results:
        done.append(f"{name}: {state} ({path})")
    path, changed, removed = merge_user_settings(["core", "observe", "delegate", "front"])
    done.append(f"{path}: relay marketplace + user-scope plugins" + ("" if changed else " (already)"))
    for r in removed:
        done.append(f"  removed a user hook the front plugin now provides: {r}")
    if run_claude and shutil.which("claude"):
        cmds = [["claude", "plugin", "marketplace", "add", marketplace_root()]] + [["claude", "plugin", "install", f"{p}@relay", "--scope", "user"] for p in ("core", "observe", "delegate", "front")]
        for cmd in cmds:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                done.append(("ok   " if proc.returncode == 0 else "FAIL ") + " ".join(cmd[1:]) + ("" if proc.returncode == 0 else ": " + (proc.stderr or proc.stdout).strip().splitlines()[-1:][0] if (proc.stderr or proc.stdout).strip() else ""))
            except Exception as exc:
                done.append(f"FAIL {' '.join(cmd[1:])}: {exc}")
    else:
        todo.append(f"in Claude Code: /plugin marketplace add {marketplace_root()}, then install core, observe, delegate, front at user scope; restart")
    link = "/usr/local/bin/relay"
    if not shutil.which("relay"):
        todo.append(f"put relay on your PATH: ln -s {os.path.join(marketplace_root(), 'bin', 'relay')} {link} (or add {os.path.join(marketplace_root(), 'bin')} to PATH)")
    return done, todo


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
