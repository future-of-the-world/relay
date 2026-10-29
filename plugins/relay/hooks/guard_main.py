#!/usr/bin/env python3
"""PreToolUse hook guard-main (the shell wrapper guard-main.sh execs this file).

PreToolUse hook: keep the main checkout clean.

Blocks, with exit 2 so the reason goes back to the agent:
- Edit/Write/MultiEdit/NotebookEdit on a path inside the main checkout but
  outside its worktrees folder (project.worktrees, default .worktrees);
- Bash that, in the main checkout, runs a mutating git command (commit,
  reset, branch -f, update-ref, ...; except `git merge --ff-only wt/<name>`,
  the user-requested merge, and `git merge --ff-only origin/<default>` in a
  main checkout on its default branch, the sync with the remote), also behind `git -c k=v`, `time`, `nohup`,
  `bash -c "..."`, `eval` and `xargs`, a command the
  project lists under [[guard.block]] in .claude/kit.toml (the stack's
  commands that write tracked files: dependency changes, formatters), or
  writes a file that is not git-ignored through the shell (a redirect or
  heredoc, tee, sed -i, perl -i, cp, mv, rm, touch, mkdir, ln, install,
  truncate, find -delete, xargs rm, rsync, patch, tar -x, unzip, curl -o,
  wget -O, dd of=). Not seen: a program's own code (python3 -c, node -e)
  and a path held in a shell variable of unknown value (see below);
- Bash of the main session (no agent_id) that cd's into a linked worktree: it moves the session's folder there;
  a subagent may. Tests: tests/test_front_cd.py;
- an anonymous `git stash` (bare, -u, push without -m) and any `git stash
  pop`, anywhere (the stash is shared);
- shell tracing (set -x, bash -x), verbose curl on an authenticated request,
  and environment dumps (env, printenv, export -p), because all print secrets;
- anywhere (main checkout or any worktree) in a repository whose default branch has `.relay/`: a write to
  `.relay/checks/` (Write/Edit, a Bash write row, git add/rm/mv/restore/update-index/checkout -- naming it, inline
  code naming it with a write word); reads are allowed. Those files are written only by relay's own hook and
  `relay gate`. Tests: tests/test_hook_check_mark.py;
- the same for a queue item file `.relay/queue/<slug>.json`: only `relay queue` writes it (the message names `relay queue edit`);
  git's own verbs (a merge conflict) stay free. Tests: tests/test_hook_check_mark.py (Q1-Q4)
- everything, with the reason, when the guard cannot read its own bindings:
  .claude/kit.toml present but unreadable, or jq / python3 missing. A broken
  guard never silently allows.

Bindings (.claude/kit.toml of the main checkout; every key optional):
  project.worktrees, project.default_branch, gate.wt   the worktree advice
  guard.target_flags     flags whose value is the directory a command acts on
  guard.secret_patterns  more ERE patterns that mark a curl as authenticated
  [[guard.block]]        pattern (ERE; {start} = where a command can start),
                         unless (ERE; a match of pattern that also matches
                         this is let through), reason

A Bash command is split into its simple commands (lib/kit_guard.py: ; && ||
| & newlines, subshells, quotes, heredocs). Each part is judged by the
directory it runs in: the tracked `cd`, overridden by its `git -C` or a
target flag's value, starting from the session cwd. So in the main checkout
`git -C .worktrees/a log && git merge x` still blocks the merge. Paths held
in shell variables are followed when the value is known: a plain `NAME=value` (or `export NAME=value`) earlier in
the same command, set once and nowhere else in it (no `+=`, `unset`, `read`, `for`, a second assignment), not after
`&&` or `||`, in a pipe or in the background; or HOME, TMPDIR, USER from the hook's own environment. The resolved
path is judged like a literal one (`M=<main>; touch $M/x` is refused from a worktree). A variable whose value is not
known (set in another call, `$(...)`, `${X:-d}`, `$1`) is read literally when unquoted (a path under the current
directory, refused in main) and skipped inside double quotes; `$PWD` is the directory tracked for that part. Tests: tests/test_hook_guard_diff.py.
This catches slips, not a determined bypass.

Tests: tests/test_hook_guard_main.py
"""
import json
import os
import re
import subprocess
import sys
from typing import Any, NoReturn, Optional

HERE = os.path.dirname(os.path.realpath(__file__))
KIT = os.path.join(HERE, "..", "bin", "kit")
LIB = os.path.join(HERE, "..", "lib")
sys.path.insert(0, LIB)

SEP = "\037"
# Where a command can start, and the env assignments that may precede it (POSIX ERE, matched by grep() below).
START = r"(^|[;&|(])[[:space:]]*([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*"
TRACING = START + r"(set[[:space:]]+-[a-wyz]*x|set[[:space:]]+-o[[:space:]]+xtrace|(ba|z)?sh[[:space:]]+-[a-z]*x)"
VERBOSE_CURL = r"curl[^;&|]*[[:space:]](-v|-[a-zA-Z]*v[a-zA-Z]*|--verbose|--trace[a-z-]*)([[:space:]]|$)"
SECRET = "[Aa]uthorization|[Tt]oken|_KEY|_SECRET|X-API"


def die(why: str) -> NoReturn:
    """A guard that cannot work blocks, with one line saying what to fix."""
    sys.stderr.write("guard-main: %s\n" % why)
    sys.exit(2)


_CLASSES = {"space": r"\s", "alpha": "a-zA-Z", "digit": "0-9", "alnum": "a-zA-Z0-9", "upper": "A-Z", "lower": "a-z",
            "blank": r" \t", "punct": r"!-/:-@\[-`{-~", "xdigit": "0-9A-Fa-f", "cntrl": r"\x00-\x1f\x7f",
            "graph": r"!-~", "print": r" -~"}


def _bracket(pattern: str, start: int) -> tuple[str, int]:
    """The ERE bracket expression opening at pattern[start] == "[" as a Python one, and the index after it.
    In ERE a backslash inside brackets is a plain character and [:name:] is a class."""
    i = start + 1
    out = "["
    if pattern[i:i + 1] == "^":
        out += "^"
        i += 1
    first = True
    while i < len(pattern):
        ch = pattern[i]
        if ch == "]" and not first:
            return out + "]", i + 1
        first = False
        if ch == "[" and pattern[i + 1:i + 2] == ":":
            end = pattern.find(":]", i + 2)
            name = pattern[i + 2:end] if end > 0 else ""
            if name not in _CLASSES:
                die("a guard pattern uses an unknown character class [:%s:] (pattern %r)" % (name, pattern))
            out += _CLASSES[name]
            i = end + 2
            continue
        out += "\\" + ch if ch in "\\[]^" else ch
        i += 1
    die("a guard pattern has an unclosed [ (pattern %r)" % pattern)


def _compile(pattern: str) -> "re.Pattern[str]":
    """A POSIX ERE as a Python regex: bracket expressions and \\< \\> are translated once, here. A pattern that does not
    compile stops the guard with the pattern named: a rule that never fires would silently allow."""
    out = ""
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "[":
            piece, i = _bracket(pattern, i)
            out += piece
        elif ch == "\\" and i + 1 < len(pattern):
            nxt = pattern[i + 1]
            out += {"<": r"\b(?=\w)", ">": r"\b(?<=\w)"}.get(nxt, ch + nxt)
            i += 2
        else:
            out += ch
            i += 1
    try:
        return re.compile(out)
    except re.error as err:
        die("a guard pattern does not compile (%s): %r" % (err, pattern))


_COMPILED: dict[str, "re.Pattern[str]"] = {}


def grep(flags: str, pattern: str, text: str) -> tuple[bool, str]:
    """What `grep <flags> -- pattern` gave over text, matched in Python line by line (the patterns are POSIX ERE).
    Flags: -Eq (any line matches), -Eo (the matching parts, one per line), -Ev (the lines that do not match).
    A pattern that does not compile stops the guard (see _compile). Alternation is leftmost-first, as in Python."""
    if pattern not in _COMPILED:
        _COMPILED[pattern] = _compile(pattern)
    regex = _COMPILED[pattern]
    lines = text.split("\n")
    if flags == "-Ev":
        kept = [line for line in lines if not regex.search(line)]
        return bool(kept), "".join(line + "\n" for line in kept)
    found = [m for m in (regex.search(line) for line in lines) if m]
    if flags == "-Eo":
        parts = [m.group(0) for line in lines for m in regex.finditer(line) if m.group(0)]
        return bool(found), "".join(part + "\n" for part in parts)
    return bool(found), ""


def resolve(path: str, base: str) -> str:
    """An absolute physical path for a possibly relative, possibly not yet existing path, via its nearest existing ancestor."""
    if path.startswith("~"):
        path = os.environ.get("HOME", "") + path[1:]
    elif not path.startswith("/"):
        path = base + "/" + path
    tail = ""
    while not os.path.isdir(path):
        path = path.rstrip("/") if len(path) > 1 else path
        tail = "/" + os.path.basename(path) + tail
        path = os.path.dirname(path)
    return os.path.realpath(path) + tail


def existing_dir(path: str) -> str:
    while not os.path.isdir(path):
        path = os.path.dirname(path)
    return path


def has_relay(directory: str) -> bool:
    """Does the default branch of the repository around directory have `.relay/`? A failure counts as no."""
    try:
        import relay_git
        return bool(relay_git.has_relay(directory))
    except Exception:
        return False


def text_of(value: Any) -> str:
    return value if isinstance(value, str) else ""


class Guard:
    def __init__(self, event: dict[str, Any]) -> None:
        self.event = event
        self.tool = text_of(event.get("tool_name"))
        self.cwd = text_of(event.get("cwd")) or os.getcwd()
        self.bind: dict[str, Any] = {}
        self.main = ""
        self.wtdir = ".worktrees"

    # ---- the project's bindings ----------------------------------------------------------------------------------
    def setup(self) -> bool:
        """The main checkout (the parent of the git common dir) and the bindings; False when this is no repository."""
        project = os.environ.get("CLAUDE_PROJECT_DIR", "")
        anchor = project or self.cwd
        if not os.path.isdir(anchor) and project:
            anchor = self.cwd
        if not os.path.isdir(anchor):
            die("the session's folder %s no longer exists, so the guard cannot tell the main checkout; "
                "start the session again from the main checkout or a worktree" % (project or self.cwd))
        done = subprocess.run(["git", "-C", anchor, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                              capture_output=True, text=True)
        if done.returncode != 0:
            return False
        self.main = os.path.realpath(os.path.join(done.stdout.strip(), ".."))
        # a file that is there but unreadable (a typo) must not silently drop the project's rules
        if os.path.isfile(os.path.join(self.main, ".claude", "kit.toml")):
            dump = subprocess.run([KIT, "dump"], cwd=self.main, capture_output=True, text=True, errors="replace")
            first = (dump.stdout + dump.stderr).splitlines()[:1]
            if dump.returncode != 0:
                die("%s/.claude/kit.toml is unreadable: %s" % (self.main, first[0] if first else ""))
            try:
                loaded = json.loads(dump.stdout)
            except ValueError:
                die("%s/.claude/kit.toml is unreadable: %s" % (self.main, first[0] if first else ""))
            self.bind = loaded if isinstance(loaded, dict) else {}
        wt = self.get("project", "worktrees")
        self.wtdir = wt if isinstance(wt, str) and wt else ".worktrees"
        if self.wtdir.endswith("/"):
            self.wtdir = self.wtdir[:-1]
        return True

    def get(self, *keys: str) -> Any:
        value: Any = self.bind
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        return value

    # ---- the answers ---------------------------------------------------------------------------------------------
    def block(self, why: str) -> NoReturn:
        branch = self.get("project", "default_branch") or ""
        wt = self.get("gate", "wt") or ""
        sys.stderr.write("guard-main: %s\n" % why)
        if wt:
            sys.stderr.write("Work in a worktree instead: %s new <name> %s, then use %s/<name> (the project's Git and worktrees rule).\n"
                             % (wt, branch or "<base>", self.wtdir))
        else:
            sys.stderr.write("Work in a worktree instead: git worktree add %s/<name> -b <branch>, then use %s/<name> (the project's Git and worktrees rule).\n"
                             % (self.wtdir, self.wtdir))
        sys.exit(2)

    def in_main(self, path: str) -> bool:
        wt = self.main + "/" + self.wtdir
        if path == wt or path.startswith(wt + "/"):
            return False
        if path == self.main or path.startswith(self.main + "/"):
            return True
        return path == "?"      # a directory the guard cannot follow (cd -, popd) counts as main

    def checks_refuse(self, directory: str) -> None:
        """.relay/checks is written only by relay, in a repository whose default branch has .relay/, whichever folder the command runs from."""
        if has_relay(directory):
            sys.stderr.write("guard-main: files in .relay/checks are written only by relay (the check hook, relay gate); "
                             "run the checker or relay gate instead\n")
            sys.exit(2)

    def queue_refuse(self, directory: str) -> None:
        """A queue item file is written only by `relay queue`; git's own verbs on it (a merge conflict) are not refused here."""
        if has_relay(directory):
            sys.stderr.write("guard-main: a queue item is changed only by relay queue (edit changes its text, note adds a note, take, done, "
                             "release, ip, drop): use relay queue edit <slug> --input <file.toml>\n")
            sys.exit(2)

    # ---- the tools -----------------------------------------------------------------------------------------------
    def edit(self) -> None:
        tool_input = self.event.get("tool_input")
        tool_input = tool_input if isinstance(tool_input, dict) else {}
        file = text_of(tool_input.get("file_path")) or text_of(tool_input.get("notebook_path"))
        if not file:
            return
        target = resolve(file, self.cwd)
        if target.endswith("/.relay/checks") or "/.relay/checks/" in target:
            self.checks_refuse(existing_dir(target))
        if re.fullmatch(r".*/\.relay/queue/.*\.json", target, re.DOTALL):
            self.queue_refuse(existing_dir(target))
        if self.in_main(target):
            self.block("%s on %s writes to the main checkout." % (self.tool, target))

    def rule_hit(self, text: str) -> Optional[str]:
        """The reason of the first project rule ([[guard.block]]) that matches this command text."""
        rules = self.get("guard", "block")
        for rule in rules if isinstance(rules, list) else []:
            pattern = text_of(rule.get("pattern")) if isinstance(rule, dict) else ""
            if not pattern:
                continue
            if "{start}" in pattern:
                before, _, after = pattern.partition("{start}")
                pattern = before + START + after
            unless = text_of(rule.get("unless"))
            ok, hits = grep("-Eo", pattern, text)
            if not ok:
                continue
            hits = hits.rstrip("\n")
            if unless:
                ok, hits = grep("-Ev", unless, hits)
                hits = hits.rstrip("\n")
                if not ok:
                    continue
            if not hits:
                continue
            return text_of(rule.get("reason")) or "this command writes tracked files"
        return None

    def bash(self) -> None:
        tool_input = self.event.get("tool_input")
        cmd = text_of(tool_input.get("command")) if isinstance(tool_input, dict) else ""
        if not cmd:
            return
        if grep("-Eq", TRACING, cmd)[0]:
            sys.stderr.write("guard-main: shell tracing prints env values and request headers, which can leak secrets.\n"
                             "Debug with targeted echo of non-secret values instead (the Secrets rule).\n")
            sys.exit(2)
        secret = SECRET
        patterns = self.get("guard", "secret_patterns")
        extra = "|".join(p for p in patterns if isinstance(p, str)) if isinstance(patterns, list) else ""
        if extra:
            secret += "|" + extra
        if grep("-Eq", VERBOSE_CURL, cmd)[0] and grep("-Eq", secret, cmd)[0]:
            sys.stderr.write("guard-main: verbose curl on an authenticated request prints the credential headers.\n"
                             "Drop -v/--trace and print only the response body or status (the Secrets rule).\n")
            sys.exit(2)
        # the rest is judged per simple command, each by the directory it runs in
        flags_value = self.get("guard", "target_flags")
        flags = [f for f in flags_value if isinstance(f, str) and f] if isinstance(flags_value, list) else []
        agent = text_of(self.event.get("agent_id"))
        done = subprocess.run([sys.executable, "-I", os.path.join(LIB, "kit_guard.py"), self.cwd] + flags,
                              input=cmd, capture_output=True, text=True, errors="replace")
        if done.returncode != 0:
            die("lib/kit_guard.py failed on this command, so the guard cannot judge it.")
        for row in done.stdout.split("\n"):
            parts = (row.split(SEP, 2) + ["", ""])[:3]
            self.row(parts[0], parts[1], parts[2], agent)

    def row(self, kind: str, a: str, b: str, agent: str) -> None:
        if kind == "B":
            sys.stderr.write("guard-main: %s\n" % a)
            sys.exit(2)
        elif kind == "X":
            self.checks_refuse(a)
        elif kind == "Y":
            self.queue_refuse(a)
        elif kind == "D":
            prefix = self.main + "/" + self.wtdir + "/"
            if a.startswith(prefix):
                # a session already working inside that worktree moves nowhere by cd'ing within it
                wtroot = prefix + a[len(prefix):].split("/", 1)[0]
                if self.cwd == wtroot or self.cwd.startswith(wtroot + "/"):
                    return
                if not agent:
                    sys.stderr.write("guard-main: cd into a worktree moves this session's working folder there and keeps it there; "
                                     "use git -C %s ... or absolute paths instead.\n" % a)
                    sys.exit(2)
        elif kind == "W":
            # a git-ignored target stays allowed (.ci/ logs); a not-yet-existing ignored directory is probed through a child path
            if self.in_main(a) and not self.ignored(a) and not self.ignored(a + "/.probe"):
                self.block("a shell command writes %s in the main checkout (redirect, tee, sed -i, cp, mv, rm, ...)." % a)
        elif kind == "C":
            if self.in_main(a):
                why = self.rule_hit(b)
                if why is not None:
                    self.block("%s (%s)." % (why, a))
        elif kind == "G":
            # the one git write allowed in main, the user-requested `merge --ff-only wt/<name>`, is not reported by kit_guard.py
            if self.in_main(a):
                self.block("mutating git command in the main checkout: %s (%s)." % (b, a))

    def ignored(self, path: str) -> bool:
        return subprocess.run(["git", "-C", self.main, "check-ignore", "-q", "--", path], capture_output=True).returncode == 0


def main() -> None:
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    try:
        loaded = json.loads(raw)
    except ValueError:
        loaded = {}
    guard = Guard(loaded if isinstance(loaded, dict) else {})
    if not guard.setup():
        return
    if guard.tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        guard.edit()
    elif guard.tool == "Bash":
        guard.bash()


if __name__ == "__main__":
    main()
