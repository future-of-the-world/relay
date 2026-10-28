#!/usr/bin/env python3
"""Splits a Bash command into its simple commands for hooks/guard-main.sh.

    kit_guard.py <cwd> [target-flag ...]      the command on stdin

The guard must judge each part of `git -C wt log && git merge x` by the
directory THAT part runs in, so this walks the command the way a shell does,
only as far as needed: quotes, `;` `&&` `||` `|` `&` and newlines, subshells
`( )` and `$( )` (a `cd` inside does not leak out), heredoc bodies (skipped),
and redirects. For each simple command it prints one line per fact, fields
separated by \\x1f:

    C <dir> <text>     a command and the directory it acts on: the tracked
                       `cd`, overridden by `git -C <dir>` or a target flag's
                       value. <text> keeps the original spelling with ; & | ( )
                       inside quotes masked, so a pattern cannot match a quoted
                       sentence.
    W <path>           an absolute path the command writes: a redirect target,
                       tee, sed -i, cp/mv/rm/touch/mkdir/ln/install/truncate,
                       curl -o, wget -O, dd of=.
    G <dir> <what>     a git command that writes the repository the directory
                       belongs to (commit, reset, branch -f, update-ref, ...),
                       found from the parsed words, so `git -c k=v commit`,
                       `time git reset`, `bash -c "git commit"` and
                       `xargs git reset` all count.
    D <dir>            a `cd` / `pushd` to a known directory that stays in force for the rest of the session's
                       command (not inside a subshell): Claude Code moves the session's folder there. The guard
                       refuses it from the main session when the directory is a linked worktree.
    B <reason>         a command blocked anywhere: an anonymous stash, a stash
                       pop, an environment dump.
    Y <dir>            the same for a queue item file `.relay/queue/<slug>.json` (a redirect, cp, mv, rm, sed -i ... or inline
                       code naming it with a write word); git's own verbs on it stay free so a conflict can be resolved.
                       Refused in a repository with `.relay/` on its default branch: only `relay queue` writes an item.
    X <dir>            a command that writes `.relay/checks/` (a redirect, cp, mv,
                       rm, ... under it; git add/rm/mv/restore/update-index or
                       `checkout --` naming it; inline code naming it with a write
                       word), and the nearest existing directory it acts in. The
                       guard refuses it only when that directory's repository has
                       a `.relay/` folder on its default branch (design section 9).

The directory is "?" when the command's place is unknown (`cd -` with no known
previous directory, `popd` of an empty stack); the guard counts it as the main
checkout. `cd -`, `pushd` and `popd` are tracked otherwise. Arithmetic
(`$(( ))`, `(( ))`) is not a command. Not seen: a write made by a program's own
code (`python3 -c "open(p, 'w')"`, `node -e`), a path or directory held in a
shell variable of unknown value, and a tar/zip written into main (only extraction is judged).

Paths in shell variables are followed when the value is known: a plain `NAME=value` (or `export NAME=value`)
earlier in the same command, set once and nowhere else in it (no `+=`, `unset`, `read`, `for`, a second
assignment), not after `&&` or `||`, in a pipe or in the background; or HOME, TMPDIR, USER from the environment
this runs in. `M=<main>; touch $M/x` is judged as `touch <main>/x`. A word holding a variable whose value is not
known (set in another call, `$(...)`, `${X:-d}`, `$1`) is read literally when unquoted (a path under the
current directory, refused in main, as before variables were followed) and skipped when it sits inside double
quotes. `$PWD` is the directory tracked for that part.
This catches slips, not a determined bypass.
"""
import os
import re
import sys

SEP = "\x1f"
OPS = ";&|\n"
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


class Word:
    __slots__ = ("text", "dynamic", "has_var", "quoted_var", "unknown")

    def __init__(self, text, dynamic, has_var=False, quoted_var=False):
        self.unknown = False  # an unquoted variable of unknown value, left as written
        self.quoted_var = quoted_var  # a `$` sits inside double quotes: when unresolved, the word is skipped
        self.text = text
        self.dynamic = dynamic  # holds a command substitution, arithmetic or a backtick: never resolved
        self.has_var = has_var  # holds an unquoted or double-quoted `$NAME`: resolved when its value is known


class Frame:
    def __init__(self, start):
        self.words = []
        self.redirs = []
        self.buf = []
        self.has_word = False
        self.dynamic = False
        self.has_var = False
        self.quoted_var = False
        self.start = start
        self.pending = None  # "redir" (a write target follows) or "skip" (an input follows)
        self.masked = []  # (offset, length) of quoted spans, for masking

    def end_word(self):
        if not self.has_word:
            return
        w = Word("".join(self.buf), self.dynamic, self.has_var, self.quoted_var)
        if self.pending == "redir":
            self.redirs.append(w)
        elif self.pending == "skip":
            pass
        else:
            self.words.append(w)
        self.pending = None
        self.buf, self.has_word, self.dynamic, self.has_var, self.quoted_var = [], False, False, False, False


def mask_text(raw):
    """raw with ; & | ( ) and newlines inside quotes replaced by _, and whitespace controls by spaces."""
    out, q, i = [], None, 0
    while i < len(raw):
        c = raw[i]
        if q:
            if c == q:
                q = None
                out.append(c)
            elif q == '"' and c == "\\" and i + 1 < len(raw):
                out.append("__")
                i += 1
            else:
                out.append("_" if c in ";&|()\n\t" else c)
        elif c == "\\" and i + 1 < len(raw):
            out.append(c)
            i += 1
            out.append(" " if raw[i] in "\n\t" else raw[i])
        elif c in "'\"":
            q = c
            out.append(c)
        else:
            out.append(" " if c in "\n\t" else c)
        i += 1
    return "".join(out)


KEYWORDS = re.compile(r"^\s*(if|then|else|elif|do|while|until|!|\{)(\s+|$)")


def seg_text(raw):
    """The masked text of a command with leading shell keywords (`then git commit`) removed."""
    t = mask_text(raw)
    while KEYWORDS.match(t):
        t = KEYWORDS.sub("", t, count=1)
    return t.strip()


def arith_end(cmd, i):
    """Index just past the `))` that closes the `((` starting at i."""
    depth, j, n = 0, i, len(cmd)
    while j < n:
        if cmd[j] == "(":
            depth += 1
        elif cmd[j] == ")":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return n


def parse(cmd):
    """Yield ("open"|"close", None) and ("cmd", (words, redirs, raw)) in shell order."""
    n, i = len(cmd), 0
    stack = [Frame(0)]
    heredocs = []  # (delimiter, strip_tabs) read at the next newline

    def flush(f, end):
        f.end_word()
        if f.words or f.redirs:
            before = re.search(r"[;&|\n]*\Z", cmd[:f.start]).group(0)
            after = re.match(r"[ \t]*([;&|\n]*)", cmd[end:]).group(1)
            return ("cmd", (f.words, f.redirs, cmd[f.start:end], (before, after)))
        return None

    while i < n:
        f = stack[-1]
        c = cmd[i]
        if c == "'":
            j = cmd.find("'", i + 1)
            j = n if j < 0 else j
            f.buf.append(cmd[i + 1:j])
            f.has_word = True
            i = j + 1
        elif c == '"':
            j, parts = i + 1, []
            while j < n and cmd[j] != '"':
                escaped = False
                if cmd[j] == "\\" and j + 1 < n:
                    j += 1
                    escaped = True
                if cmd[j] == "`" or (cmd[j] == "$" and not escaped and cmd.startswith("(", j + 1)):
                    f.dynamic = True
                elif cmd[j] == "$" and not escaped:
                    f.has_var = True
                    f.quoted_var = True
                parts.append(cmd[j])
                j += 1
            f.buf.append("".join(parts))
            f.has_word = True
            i = j + 1
        elif c == "\\" and i + 1 < n:
            if cmd[i + 1] != "\n":
                f.buf.append(cmd[i + 1])
                f.has_word = True
            i += 2
        elif c == "`":
            # command substitution in backticks: its commands run in a subshell
            j = cmd.find("`", i + 1)
            j = n if j < 0 else j
            f.dynamic = True
            f.buf.append("$SUB")
            f.has_word = True
            yield ("open", None)
            for ev in parse(cmd[i + 1:j]):
                yield ev
            yield ("close", None)
            i = j + 1
        elif cmd.startswith("$((", i):
            # arithmetic expansion: no command inside, and `>` is a comparison
            f.dynamic = True
            f.buf.append("$ARITH")
            f.has_word = True
            i = arith_end(cmd, i + 1)
        elif c == "(" and not f.has_word and cmd.startswith("((", i):
            # (( )) arithmetic command or C-style for header
            f.dynamic = True
            f.buf.append("$ARITH")
            f.has_word = True
            i = arith_end(cmd, i)
        elif (c == "$" and cmd.startswith("$(", i)) or (c in "<>" and cmd.startswith("(", i + 1)):
            # $( ) and process substitution: its commands run in a subshell
            f.dynamic = True
            f.buf.append("$SUB")
            f.has_word = True
            stack.append(Frame(i + 2))
            yield ("open", None)
            i += 2
        elif c == "(" and not f.has_word:
            r = flush(f, i)
            if r:
                yield r
            f.words, f.redirs, f.pending = [], [], None
            stack.append(Frame(i + 1))
            yield ("open", None)
            i += 1
        elif c == ")" and len(stack) > 1:
            r = flush(f, i)
            if r:
                yield r
            stack.pop()
            yield ("close", None)
            if not stack[-1].has_word:
                stack[-1].start = i + 1
            i += 1
        elif c == "&" and cmd.startswith("&>", i):
            f.end_word()
            f.pending = "redir"
            i += 3 if cmd.startswith("&>>", i) else 2
        elif c in OPS:
            r = flush(f, i)
            if r:
                yield r
            j = i + 1
            while j < n and cmd[j] in "&|;":
                j += 1
            if c == "\n" and heredocs:
                j = i + 1
                for delim, strip in heredocs:
                    while j < n:
                        k = cmd.find("\n", j)
                        k = n if k < 0 else k
                        line = cmd[j:k]
                        j = min(k + 1, n)
                        if (line.lstrip("\t") if strip else line) == delim:
                            break
                heredocs = []
            f.words, f.redirs, f.pending = [], [], None
            f.start = j
            i = j
        elif c in " \t":
            f.end_word()
            i += 1
        elif c == "#" and not f.has_word:
            j = cmd.find("\n", i)
            i = n if j < 0 else j
        elif c in "<>":
            # redirects. `N>`: the digits are the fd, not a word.
            if f.has_word and "".join(f.buf).isdigit() and not f.dynamic:
                f.buf, f.has_word = [], False
            else:
                f.end_word()
            if cmd.startswith("<<<", i):
                f.pending = "skip"
                i += 3
            elif cmd.startswith("<<", i):
                j = i + 2
                strip = j < n and cmd[j] == "-"
                j += 1 if strip else 0
                while j < n and cmd[j] in " \t":
                    j += 1
                k = j
                dq = None
                delim = []
                while k < n and (dq or cmd[k] not in " \t\n;&|<>()"):
                    if cmd[k] in "'\"" and not dq:
                        dq = cmd[k]
                    elif cmd[k] == dq:
                        dq = None
                    else:
                        delim.append(cmd[k])
                    k += 1
                heredocs.append(("".join(delim), strip))
                i = k
            elif c == "<":
                f.pending = "skip"
                i += 1
            else:
                j = i + 1
                if j < n and cmd[j] == ">":
                    j += 1
                if j < n and cmd[j] == "|":
                    j += 1
                if j < n and cmd[j] == "&":
                    # >&2, >&-: a descriptor copy, not a file
                    j += 1
                    while j < n and cmd[j] not in " \t\n;&|<>()":
                        j += 1
                    i = j
                    continue
                f.pending = "redir"
                i = j
        else:
            if c == "$":
                f.has_var = True
            f.buf.append(c)
            f.has_word = True
            i += 1
    while len(stack) > 1:
        r = flush(stack[-1], n)
        if r:
            yield r
        stack.pop()
        yield ("close", None)
    r = flush(stack[0], n)
    if r:
        yield r


UNKNOWN = "?"


def resolve(path, base):
    p = os.path.expanduser(path)
    if not os.path.isabs(p):
        if base == UNKNOWN:
            return UNKNOWN
        p = os.path.join(base, p)
    return os.path.realpath(p)


WRAPPERS = {"command", "time", "nohup", "exec", "builtin", "nice", "sudo", "if", "then", "else", "elif", "do", "while", "until", "!", "{"}
WRITE_ALL = {"rm", "rmdir", "unlink", "touch", "mkdir", "truncate", "shred", "tee", "mv"}
STASH_MSG = re.compile(r"^(-[A-Za-z]*m|--message(=.*)?)$")
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
# options that take the next word as their value, so it is not a path
OPT_VALUE = {
    "touch": {"-t", "-r", "-d", "--date", "--reference"},
    "mkdir": {"-m", "--mode"},
    "truncate": {"-s", "-r", "--size", "--reference"},
    "install": {"-m", "-o", "-g", "-S", "--mode", "--owner", "--group", "--suffix"},
    "rsync": {"-e", "--rsh", "--exclude", "--include", "--filter", "-f", "--exclude-from", "--include-from",
              "--files-from", "--log-file", "--backup-dir", "--suffix", "--chmod", "--chown", "--rsync-path"},
}
XARGS_VALUE = {"-I", "-n", "-P", "-L", "-d", "-s", "-E", "-a", "-J", "--max-args", "--max-procs", "--delimiter", "--arg-file"}
GIT_WRITE = {"commit", "merge", "switch", "checkout", "reset", "rebase", "restore", "cherry-pick", "revert", "pull",
             "am", "apply", "add", "rm", "mv", "clean", "update-ref", "read-tree", "checkout-index", "filter-branch"}
CHECKS = re.compile(r"(?:^|/)\.relay/checks(?:/|$)")
CHECKS_NAMED = re.compile(r"(?:^|[^A-Za-z0-9_.])\.relay/checks(?:/|$|[^A-Za-z0-9_.])")
QUEUE_FILE = re.compile(r"(?:^|/)\.relay/queue/[^/]+\.json$")
QUEUE_NAMED = re.compile(r"(?:^|[^A-Za-z0-9_.])\.relay/queue/")
GIT_CHECKS_WRITE = {"add", "rm", "mv", "restore", "update-index"}
INLINE_CODE = {"python", "python3", "node", "perl", "ruby"}
# a write in inline code: open( with a w, a or x mode, or one of these words, or a redirect
# (a `>` inside the code is a comparison, never a redirect: a real redirect is a shell word and is checked as a target;
# printing with sys.stdout.write or sys.stderr.write is not a file write; a word is a write only as a call, so text
# like ".relay/checks writes" in a printed string is not)
INLINE_WRITE = re.compile(r"open\([^)]*['\"][wax][+bt]*['\"]|(?<!sys\.stdout\.)(?<!sys\.stderr\.)\b(?:write\w*|unlink|remove|rename|rmtree|copy\w*|move)\s*\(")
GIT_GLOBAL_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix"}


def strip_prefix(words):
    """Drop env assignments and wrappers; return the command words from the real command on."""
    i = 0
    while i < len(words):
        t = words[i].text
        if ENV_ASSIGN.match(t):
            i += 1
        elif t in WRAPPERS:
            i += 1
        elif t == "env":
            i += 1
            while i < len(words) and (words[i].text.startswith("-") or ENV_ASSIGN.match(words[i].text)):
                i += 1
            if i >= len(words):
                return [Word("env", False)]  # an environment dump
        else:
            break
    return words[i:]


def existing_dir(path):
    """The nearest existing directory at or above `path`."""
    p = path
    while p and not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p


def git_parts(words, cwd):
    """(dir, subcommand, rest) of a git command: -C options applied to cwd."""
    d, i = cwd, 1
    while i < len(words):
        t = words[i].text
        if t == "-C" and i + 1 < len(words):
            if not words[i + 1].dynamic and not words[i + 1].unknown:
                d = resolve(words[i + 1].text, d)
            i += 2
        elif t in GIT_GLOBAL_VALUE and i + 1 < len(words):
            i += 2
        elif t.startswith("-"):
            i += 1
        else:
            return d, t, words[i + 1:]
    return d, "", []


def stash_block(rest):
    texts = [w.text for w in rest]
    action = next((t for t in texts if not t.startswith("-")), None)
    named = any(STASH_MSG.match(t) for t in texts)
    if action == "pop":
        return "'git stash pop' uses the stash shared by all worktrees; make a WIP commit on the worktree branch instead."
    if action is None or action == "push":
        if not named:
            return "an anonymous 'git stash' uses the stash shared by all worktrees; make a WIP commit on the worktree branch instead."
    if action == "save" and len([t for t in texts if not t.startswith("-")]) < 2:
        return "an anonymous 'git stash save' uses the stash shared by all worktrees; make a WIP commit on the worktree branch instead."
    return None


def _widens_ff_only(texts):
    """True when --ff-only has --no-ff, --ff or --squash beside it: git takes the last one and may make a merge commit."""
    return any(t in ("--no-ff", "--ff", "--squash", "--no-ff-only") for t in texts)


def allowed_merge_branch(rest):
    """The wt/ branch of `git merge --ff-only wt/<name>` (the arguments after `merge`), else None."""
    texts = [w.text for w in rest]
    if "--help" in texts or "-h" in texts:
        return None
    pos = [t for t in texts if not t.startswith("-")]
    if _widens_ff_only(texts):
        return None
    if "--ff-only" in texts and len(pos) == 1 and re.match(r"^wt/[^\s;&|)]+$", pos[0]):
        return pos[0]
    return None


def sync_merge(rest, directory):
    """True for `git merge --ff-only origin/<default>` (exactly that ref) run in `directory` while the default branch
    is checked out there: a main checkout catching up with its remote (projects that merge by pull request). Only `origin`."""
    texts = [w.text for w in rest]
    pos = [t for t in texts if not t.startswith("-")]
    if "--help" in texts or "-h" in texts or "--ff-only" not in texts or _widens_ff_only(texts) or len(pos) != 1 or directory == UNKNOWN:
        return False
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # the guard runs with python3 -I: no script folder on the path
    import relay_git
    default = relay_git.default_branch(directory)
    if not default or relay_git.current_branch(directory) != default:
        return False
    return pos[0] == "origin/" + default


def git_write(sub, rest, directory=UNKNOWN):
    """What a git subcommand writes, or None when it only reads (or writes nothing in the working tree)."""
    texts = [w.text for w in rest]
    if "--help" in texts or "-h" in texts:
        return None
    flags = [t for t in texts if t.startswith("-")]
    if sub == "merge":
        # the one write allowed in main: the user-requested fast-forward to a finished wt/ branch, or the sync to origin/<default>
        if allowed_merge_branch(rest) or sync_merge(rest, directory):
            return None
        return "git merge"
    if sub in GIT_WRITE:
        return "git " + sub
    if sub == "branch":
        letters = re.compile(r"^-[A-Za-z]*[fDdMmCcu]")
        if any(letters.match(t) and not t.startswith("--") for t in flags) or any(
            t.split("=")[0] in ("--force", "--delete", "--move", "--copy", "--set-upstream-to", "--unset-upstream", "--edit-description")
            for t in flags
        ):
            return "git branch (moves or deletes a branch)"
    if sub == "tag" and any(t in ("-d", "--delete", "-f", "--force") for t in flags):
        return "git tag (moves or deletes a tag)"
    if sub == "symbolic-ref" and len([t for t in texts if not t.startswith("-")]) >= 2:
        return "git symbolic-ref"
    return None


class State:
    """The directory a shell is in, the one before it (`cd -`), and its pushd stack."""

    def __init__(self, cur, env=None):
        self.cur, self.prev, self.stack = cur, UNKNOWN, []
        self.env = dict(env or {})  # variables assigned earlier in this command, with their literal values

    def copy(self):
        c = State(self.cur, self.env)
        c.prev, c.stack = self.prev, list(self.stack)
        return c


ENV_KNOWN = ("HOME", "TMPDIR", "USER")
# commands whose words name a variable they set or remove
ASSIGNERS = ("unset", "read", "for", "select", "declare", "local", "typeset", "export", "readonly", "printf",
             "mapfile", "readarray", "getopts", "let")
VAR_REF = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")


def expand(word, lookup):
    """The word with its `$NAME` / `${NAME}` replaced by their known values. A variable with no known value
    (or a form like `${X:-d}`, `$1`, `$?`) in an unquoted word is left as written, so the word is read
    literally (a path under the current directory, as before variables were followed); a word with such a
    variable inside double quotes comes back dynamic, so it is skipped."""
    if not word.has_var:
        return word
    failed = []

    def sub(m):
        v = lookup(m.group(1) or m.group(2))
        if v is None:
            failed.append(1)
            return m.group(0)
        return v

    text = VAR_REF.sub(sub, word.text)
    if failed or "$" in VAR_REF.sub("", word.text):
        if word.quoted_var:
            return Word(word.text, True)
        w = Word(text, word.dynamic)
        w.unknown = True
        return w
    return Word(text, word.dynamic)


def positional(name, args):
    """The path words of a command: no flags, no flag values."""
    skip = OPT_VALUE.get(name, set())
    out, k = [], 0
    while k < len(args):
        t = args[k].text
        if t in skip:
            k += 2
            continue
        if not t.startswith("-"):
            out.append(args[k])
        k += 1
    return out


def option_value(args, short, long_):
    for k, w in enumerate(args):
        if w.text in short and k + 1 < len(args):
            return args[k + 1]
        if w.text.startswith(long_ + "="):
            return Word(w.text[len(long_) + 1:], False)
    return None


def shell_writes(name, args, paths, cur, via_xargs):
    """Words naming what a command writes, for the commands whose targets are not simply every path."""
    here = Word(".", False)
    if name == "cp":
        tdir = option_value(args, ("-t",), "--target-directory")
        return [tdir] if tdir else paths[-1:] if len(paths) >= 2 else []
    if name == "install":
        if any(w.text == "-d" for w in args):
            return paths
        tdir = option_value(args, ("-t",), "--target-directory")
        return [tdir] if tdir else paths[-1:] if len(paths) >= 2 else []
    if name == "ln":
        tdir = option_value(args, ("-t",), "--target-directory")
        if tdir:
            return [tdir]
        if len(paths) >= 2:
            return paths[-1:]
        return [Word(os.path.basename(paths[0].text), False)] if paths else []
    if name == "sed" and any(re.match(r"^-[A-Za-z]*i|^--in-place", w.text) for w in args):
        return [w for w in paths if os.path.isfile(resolve(w.text, cur))]
    if name == "perl" and any(re.match(r"^-[plnasw0-9]*i", w.text) and not w.text.startswith("--") for w in args):
        return [w for w in paths if os.path.isfile(resolve(w.text, cur))]
    if name in ("curl", "wget"):
        outs = {"-o", "--output"} | ({"-O"} if name == "wget" else set())
        return [args[k + 1] for k, w in enumerate(args[:-1]) if w.text in outs]
    if name == "dd":
        return [Word(w.text[3:], False) for w in args if w.text.startswith("of=")]
    if name == "find":
        texts = [w.text for w in args]
        danger = "-delete" in texts or any(
            t in ("-exec", "-execdir") and k + 1 < len(texts) and os.path.basename(texts[k + 1]) in ("rm", "rmdir", "mv", "shred", "unlink", "truncate")
            for k, t in enumerate(texts)
        )
        if not danger:
            return []
        roots = []
        for w in args:
            if w.text.startswith("-") or w.text in ("(", "!", ","):
                break
            roots.append(w)
        return roots or [here]
    if name == "rsync":
        if any(w.text in ("-n", "--dry-run") for w in args):
            return []
        dest = paths[-1] if len(paths) >= 2 else None
        if dest is None or re.match(r"^[^/]*:", dest.text):
            return []
        return [dest]
    if name == "patch":
        if any(w.text == "--dry-run" for w in args):
            return []
        return [option_value(args, ("-d",), "--directory") or here]
    if name == "unzip":
        if any(w.text.startswith("-") and not w.text.startswith("--") and re.search(r"[ltpvZz]", w.text) for w in args):
            return []
        return [option_value(args, ("-d",), "--directory") or here]
    if name == "tar":
        texts = [w.text for w in args]
        old_style = bool(texts) and re.match(r"^[A-Za-z]+$", texts[0]) and "x" in texts[0]
        clusters = any(re.match(r"^-[A-Za-z]*x", t) and not t.startswith("--") for t in texts)
        if old_style or clusters or "--extract" in texts or "--get" in texts:
            return [option_value(args, ("-C",), "--directory") or here]
        return []
    if name in WRITE_ALL:
        if via_xargs and not paths:
            return [here]  # `ls | xargs rm`: the names come from stdin, relative to the directory
        return paths
    return []


def analyze(cmd, cwd, flags, depth=0, merges=None, env=None, same_shell=True):
    out = []
    inherited = set(env or {})  # variables set by the command that runs this string
    states = [State(cwd, env)]

    events = list(parse(cmd))
    cmd_words = [w for kind, payload in events if kind not in ("open", "close") for w in [payload[0] + payload[1]]]

    def uses(name):
        """How many times a word of this command can change `name` (or, for a name held from an outer command,
        mention it): an assignment `NAME=` `NAME+=` `NAME[`, `${NAME:=`, the name given to unset, read, for,
        declare, export, ... , or any bare mention inside an eval or shell string. Text in quotes, heredoc bodies
        and the like is not a use."""
        n = 0
        bare = re.compile(r"(?<![A-Za-z0-9_$])(?<!\$\{)" + re.escape(name) + r"(?![A-Za-z0-9_])")
        for ws in cmd_words:
            for k, w in enumerate(ws):
                if re.match(re.escape(name) + r"(\+=|=|\[)", w.text) and not w.quoted_var:
                    n += 1
                elif re.search(r"\$\{" + re.escape(name) + r":?=", w.text):
                    n += 1
                cmd_name = os.path.basename(w.text)
                if cmd_name in ASSIGNERS:
                    n += sum(1 for x in ws[k + 1:] if x.text == name)
                elif cmd_name in SHELLS or cmd_name == "eval":
                    n += sum(len(bare.findall(x.text)) for x in ws[k + 1:])
        return n

    def trusted(name):
        """True when `name` is set once, by a plain `NAME=value` and nowhere else in this command (no `+=`,
        `unset`, `read`, `for`, `declare`, a function body, a second assignment): then the order of the parts
        decides its value. A name held from an outer command must not be changed in this one at all."""
        n = uses(name)
        return n == 0 if name in inherited else n <= 1

    def lookup(st, name):
        if name == "PWD" and name not in st.env and trusted(name) and st.cur != UNKNOWN:
            return st.cur
        if name in st.env:
            return st.env[name] if trusted(name) else None
        if name in ENV_KNOWN and trusted(name):
            return os.environ.get(name) or None
        return None

    def simple(words, redirs, raw, st, via_xargs=False, around=("", "")):
        cur = st.cur
        words = [expand(w, lambda n: lookup(st, n)) for w in words]
        redirs = [expand(w, lambda n: lookup(st, n)) for w in redirs]
        # `NAME=value` and `export NAME=value` (a literal value) set a variable for the parts that follow
        body = words[1:] if words and words[0].text == "export" else words
        if body and all(ENV_ASSIGN.match(w.text) for w in body):
            # an assignment that does not always run before the next part (after && or ||, in a pipe, in the
            # background) or whose value is not a plain literal leaves the variable unknown
            sure = around[0].strip("\n;") == "" and around[1] not in ("&", "|")
            for w in body:
                name, _, value = w.text.partition("=")
                st.env[name] = value if sure and not w.dynamic and not w.unknown and "$" not in value else None
        real = strip_prefix(words)
        name = os.path.basename(real[0].text) if real else ""
        d = cur
        if name in ("cd", "pushd", "popd") and not via_xargs:
            out.append(("C", cur, seg_text(raw)))
            arg = next((w for w in real[1:] if w.text == "-" or not w.text.startswith("-")), None)
            if name == "popd":
                st.prev, st.cur = cur, (st.stack.pop() if st.stack else UNKNOWN)
            elif arg is not None and arg.text == "-":
                st.prev, st.cur = cur, st.prev
            elif arg is not None and not arg.dynamic and not arg.unknown and arg.text != "":
                new = resolve(arg.text, cur)
                if name == "pushd":
                    st.stack.append(cur)
                st.prev, st.cur = cur, new
                # D: a cd in the session's own shell; a child shell (bash -c) or a pipe stage cannot move the session
                piped = around[1] == "|" or around[0].rstrip().endswith("|")
                if same_shell and not piped and len(states) == 1 and name in ("cd", "pushd"):
                    out.append(("D", new))
            return
        if name == "git":
            d, sub, rest = git_parts(real, cur)
            if sub == "stash":
                why = stash_block(rest)
                if why:
                    out.append(("B", why))
            if sub == "merge" and merges is not None:
                branch = allowed_merge_branch(rest)
                if branch:
                    merges.append((d, branch))
            what = git_write(sub, rest, d)
            texts = [w.text for w in rest]
            if d != UNKNOWN and any(CHECKS.search(t) or CHECKS_NAMED.search(t) for t in texts) and (
                sub in GIT_CHECKS_WRITE or (sub == "checkout" and "--" in texts)
            ):
                out.append(("X", existing_dir(d)))
            if what:
                out.append(("G", d, what))
        # a target flag's value is the directory (or a file in it) the command acts on
        for k, w in enumerate(words):
            for flag in flags:
                val = None
                if w.text == flag and k + 1 < len(words) and not words[k + 1].dynamic and not words[k + 1].unknown:
                    val = words[k + 1].text
                elif w.text.startswith(flag + "=") and not w.dynamic and not w.unknown:
                    val = w.text[len(flag) + 1:]
                if val:
                    d = resolve(val, cur)
                    if d != UNKNOWN and os.path.isfile(d):
                        d = os.path.dirname(d)
        out.append(("C", d, seg_text(raw)))

        if name == "printenv" or (name == "env" and len(real) == 1) or (
            name == "export" and [w.text for w in real[1:]] == ["-p"]
        ):
            out.append(("B", "environment dumps print secrets; read one non-secret variable by name instead (the Secrets rule)."))

        # a shell or eval running a string: judge the string as a command of its own
        if depth < 4:
            if name in SHELLS:
                k = next((k for k, w in enumerate(real) if k > 0 and re.match(r"^-[A-Za-z]*c[A-Za-z]*$", w.text)), None)
                if k is not None and k + 1 < len(real):
                    out.extend(analyze(real[k + 1].text, cur, flags, depth + 1, merges, st.env, False))
            elif name == "eval" and len(real) > 1:
                out.extend(analyze(" ".join(w.text for w in real[1:]), cur, flags, depth + 1, merges, st.env, same_shell))
            elif name == "xargs":
                k = 1
                while k < len(real) and real[k].text.startswith("-"):
                    t = real[k].text
                    k += 2 if t in XARGS_VALUE else 1
                if k < len(real):
                    simple(real[k:], [], raw, st, via_xargs=True)

        # inline code naming .relay/checks together with a write word
        if name in INLINE_CODE or re.match(r"^python3?\.\d+\Z", name):
            code = " ".join(w.text for w in real[1:])
            if cur != UNKNOWN and CHECKS_NAMED.search(code) and INLINE_WRITE.search(code):
                out.append(("X", existing_dir(cur)))
            if cur != UNKNOWN and QUEUE_NAMED.search(code) and INLINE_WRITE.search(code):
                out.append(("Y", existing_dir(cur)))

        # files written
        targets = [w for w in redirs if not w.dynamic and not w.text.startswith("/dev/")]
        args = [w for w in real[1:] if not w.dynamic]
        paths = positional(name, args)
        targets += shell_writes(name, args, paths, cur, via_xargs)
        for t in targets:
            if t.text and not t.dynamic:
                row = resolve(t.text, cur)
                if row != UNKNOWN:
                    if CHECKS.search(row):
                        out.append(("X", existing_dir(row)))
                    if QUEUE_FILE.search(row):
                        out.append(("Y", existing_dir(row)))
                    out.append(("W", row))

    for kind, payload in events:
        if kind == "open":
            states.append(states[-1].copy())
            continue
        if kind == "close":
            if len(states) > 1:
                states.pop()
            continue
        words, redirs, raw, around = payload
        simple(words, redirs, raw, states[-1], around=around)
    return out


def allowed_merges(cmd, cwd):
    """[(dir, branch)] for every simple command of `cmd` that is the allowed merge, `git merge --ff-only wt/<name>`:
    the directory it acts on (`cd`, `git -C` applied) and the branch, in order, without repeats."""
    found = []
    analyze(cmd, os.path.realpath(cwd), [], 0, found)
    return list(dict.fromkeys(found))


def main(argv):
    cwd = os.path.realpath(argv[1])
    flags = argv[2:]
    cmd = sys.stdin.read()
    seen = set()
    for row in analyze(cmd, cwd, flags):
        if row in seen:
            continue
        seen.add(row)
        print(SEP.join(row))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
