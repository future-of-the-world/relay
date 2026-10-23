#!/usr/bin/env bash
# PreToolUse hook: keep the main checkout clean.
#
# Blocks, with exit 2 so the reason goes back to the agent:
# - Edit/Write/MultiEdit/NotebookEdit on a path inside the main checkout but
#   outside its worktrees folder (project.worktrees, default .worktrees);
# - Bash that, in the main checkout, runs a mutating git command (commit,
#   reset, branch -f, update-ref, ...; except `git merge --ff-only wt/<name>`,
#   the user-requested merge), also behind `git -c k=v`, `time`, `nohup`,
#   `bash -c "..."`, `eval` and `xargs`, a command the
#   project lists under [[guard.block]] in .claude/kit.toml (the stack's
#   commands that write tracked files: dependency changes, formatters), or
#   writes a file that is not git-ignored through the shell (a redirect or
#   heredoc, tee, sed -i, perl -i, cp, mv, rm, touch, mkdir, ln, install,
#   truncate, find -delete, xargs rm, rsync, patch, tar -x, unzip, curl -o,
#   wget -O, dd of=). Not seen: a program's own code (python3 -c, node -e)
#   and a path held in a shell variable;
# - an anonymous `git stash` (bare, -u, push without -m) and any `git stash
#   pop`, anywhere (the stash is shared);
# - shell tracing (set -x, bash -x), verbose curl on an authenticated request,
#   and environment dumps (env, printenv, export -p), because all print secrets;
# - anywhere (main checkout or any worktree) in a repository whose default branch has `.relay/`: a write to
#   `.relay/checks/` (Write/Edit, a Bash write row, git add/rm/mv/restore/update-index/checkout -- naming it, inline
#   code naming it with a write word); reads are allowed. Those files are written only by relay's own hook and
#   `relay gate`. Tests: plugins/core/tests/check-mark.test.sh;
# - everything, with the reason, when the guard cannot read its own bindings:
#   .claude/kit.toml present but unreadable, or jq / python3 missing. A broken
#   guard never silently allows.
#
# Bindings (.claude/kit.toml of the main checkout; every key optional):
#   project.worktrees, project.default_branch, gate.wt   the worktree advice
#   guard.target_flags     flags whose value is the directory a command acts on
#   guard.secret_patterns  more ERE patterns that mark a curl as authenticated
#   [[guard.block]]        pattern (ERE; {start} = where a command can start),
#                          unless (ERE; a match of pattern that also matches
#                          this is let through), reason
#
# A Bash command is split into its simple commands (lib/kit_guard.py: ; && ||
# | & newlines, subshells, quotes, heredocs). Each part is judged by the
# directory it runs in: the tracked `cd`, overridden by its `git -C` or a
# target flag's value, starting from the session cwd. So in the main checkout
# `git -C .worktrees/a log && git merge x` still blocks the merge. Paths held
# in shell variables are followed when the value is known: a plain `NAME=value` (or `export NAME=value`) earlier in
# the same command, set once and nowhere else in it (no `+=`, `unset`, `read`, `for`, a second assignment), not after
# `&&` or `||`, in a pipe or in the background; or HOME, TMPDIR, USER from the hook's own environment. The resolved
# path is judged like a literal one (`M=<main>; touch $M/x` is refused from a worktree). A variable whose value is not
# known (set in another call, `$(...)`, `${X:-d}`, `$1`) makes its word skipped, quoted or not: a write to it is not
# refused, even when it lands in main. Tests: tests/guard-diff.test.sh.
# This catches slips, not a determined bypass.
#
# Tests: plugins/core/tests/guard-main.test.sh
set -uo pipefail

kit="$(cd "$(dirname "$0")" && pwd -P)/../bin/kit"
lib="$(cd "$(dirname "$0")" && pwd -P)/../lib"

# A guard that cannot work blocks, with one line saying what to fix.
die() { echo "guard-main: $1" >&2; exit 2; }
command -v jq >/dev/null 2>&1 || die "jq is not installed, so the guard cannot read the tool call. Install it (brew install jq)."
input="$(cat)"
tool="$(jq -r '.tool_name // empty' <<<"$input")"
cwd="$(jq -r '.cwd // empty' <<<"$input")"
[ -n "$cwd" ] || cwd="$PWD"

# Main checkout = parent of the git common dir, which every worktree shares.
# A session folder that was deleted (its worktree removed) falls back to cwd; with neither there, refuse.
anchor="${CLAUDE_PROJECT_DIR:-$cwd}"
if [ ! -d "$anchor" ] && [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then anchor="$cwd"; fi
[ -d "$anchor" ] || die "the session's folder ${CLAUDE_PROJECT_DIR:-$cwd} no longer exists, so the guard cannot tell the main checkout; start the session again from the main checkout or a worktree"
common="$(git -C "$anchor" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || exit 0
main="$(cd "$common/.." && pwd -P)"

# The project's bindings, read once from the main checkout. A file that is
# there but unreadable (a typo) must not silently drop the project's rules.
bind='{}'
if [ -f "$main/.claude/kit.toml" ]; then
  bind="$(cd "$main" && "$kit" dump 2>&1)" || die "$main/.claude/kit.toml is unreadable: $(head -n 1 <<<"$bind")"
fi
command -v python3 >/dev/null 2>&1 || die "python3 is not installed, so the guard cannot read Bash commands. Install Python 3."
wtdir="$(jq -r '.project.worktrees // ".worktrees"' <<<"$bind")"
wtdir="${wtdir%/}"

block() {
  local branch wt
  branch="$(jq -r '.project.default_branch // empty' <<<"$bind")"
  wt="$(jq -r '.gate.wt // empty' <<<"$bind")"
  echo "guard-main: $1" >&2
  if [ -n "$wt" ]; then
    echo "Work in a worktree instead: $wt new <name> ${branch:-<base>}, then use $wtdir/<name> (the project's Git and worktrees rule)." >&2
  else
    echo "Work in a worktree instead: git worktree add $wtdir/<name> -b <branch>, then use $wtdir/<name> (the project's Git and worktrees rule)." >&2
  fi
  exit 2
}

# Resolve a path (possibly relative, possibly not yet existing) to an absolute
# physical path, via its nearest existing ancestor.
resolve() {
  local p="$1" base="$2" tail=""
  case "$p" in "~"*) p="$HOME${p#\~}" ;; /*) ;; *) p="$base/$p" ;; esac
  while [ ! -d "$p" ]; do
    tail="/$(basename "$p")$tail"
    p="$(dirname "$p")"
  done
  echo "$(cd "$p" && pwd -P)$tail"
}

# .relay/checks is written only by relay (the check hook, relay gate): in a repository whose default branch has
# .relay/, whichever folder the command runs from. Outside such a repository a write is allowed (design section 9).
# One git call, made only when a path or command names .relay/checks.
checks_refuse() { # <existing directory the write acts in>
  python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import relay_git; sys.exit(0 if relay_git.has_relay(sys.argv[2]) else 1)' "$lib" "$1" 2>/dev/null || return 0
  echo "guard-main: files in .relay/checks are written only by relay (the check hook, relay gate); run the checker or relay gate instead" >&2
  exit 2
}

in_main() {
  case "$1" in
    "$main/$wtdir" | "$main/$wtdir/"*) return 1 ;;
    "$main" | "$main/"*) return 0 ;;
    "?") return 0 ;; # a directory the guard cannot follow (cd -, popd): counts as main
    *) return 1 ;;
  esac
}

case "$tool" in
  Edit | Write | MultiEdit | NotebookEdit)
    file="$(jq -r '.tool_input.file_path // .tool_input.notebook_path // empty' <<<"$input")"
    [ -n "$file" ] || exit 0
    target="$(resolve "$file" "$cwd")"
    case "$target" in */.relay/checks | */.relay/checks/*)
      dir="$target"; while [ ! -d "$dir" ]; do dir="$(dirname "$dir")"; done
      checks_refuse "$dir" ;;
    esac
    in_main "$target" && block "$tool on $target writes to the main checkout."
    exit 0
    ;;
  Bash) ;;
  *) exit 0 ;;
esac

cmd="$(jq -r '.tool_input.command // empty' <<<"$input")"
[ -n "$cmd" ] || exit 0

# Where a command can start, and the env assignments that may precede it.
start='(^|[;&|(])[[:space:]]*([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*'

# Shell tracing and verbose curl print env values and auth headers.
if grep -Eq "${start}(set[[:space:]]+-[a-wyz]*x|set[[:space:]]+-o[[:space:]]+xtrace|(ba|z)?sh[[:space:]]+-[a-z]*x)" <<<"$cmd"; then
  echo "guard-main: shell tracing prints env values and request headers, which can leak secrets." >&2
  echo "Debug with targeted echo of non-secret values instead (the Secrets rule)." >&2
  exit 2
fi
secret='[Aa]uthorization|[Tt]oken|_KEY|_SECRET|X-API'
extra="$(jq -r '(.guard.secret_patterns // []) | join("|")' <<<"$bind")"
[ -z "$extra" ] || secret="$secret|$extra"
if grep -Eq 'curl[^;&|]*[[:space:]](-v|-[a-zA-Z]*v[a-zA-Z]*|--verbose|--trace[a-z-]*)([[:space:]]|$)' <<<"$cmd" &&
  grep -Eq "$secret" <<<"$cmd"; then
  echo "guard-main: verbose curl on an authenticated request prints the credential headers." >&2
  echo "Drop -v/--trace and print only the response body or status (the Secrets rule)." >&2
  exit 2
fi

# The rest is judged per simple command, each by the directory it runs in.
rules="$(jq -c '.guard.block[]?' <<<"$bind")"
flags=()
while IFS= read -r f; do [ -n "$f" ] && flags+=("$f"); done < <(jq -r '.guard.target_flags[]?' <<<"$bind")

SEP=$'\037'

# Does a project rule match this command text? Prints the reason when it does.
rule_hit() {
  local text="$1" rule pat unless hits
  while IFS= read -r rule; do
    [ -n "$rule" ] || continue
    pat="$(jq -r '.pattern // empty' <<<"$rule")"
    [ -n "$pat" ] || continue
    # {start} (once) becomes $start; spliced, not substituted, so the & in $start
    # stays literal in every bash.
    case "$pat" in *"{start}"*) pat="${pat%%\{start\}*}${start}${pat#*\{start\}}" ;; esac
    unless="$(jq -r '.unless // empty' <<<"$rule")"
    hits="$(grep -Eo -- "$pat" <<<"$text")" || continue
    if [ -n "$unless" ]; then
      hits="$(grep -Ev -- "$unless" <<<"$hits")" || continue
    fi
    [ -n "$hits" ] || continue
    jq -r '.reason // "this command writes tracked files"' <<<"$rule"
    return 0
  done <<<"$rules"
  return 1
}

rows="$(printf '%s' "$cmd" | python3 -I "$lib/kit_guard.py" "$cwd" "${flags[@]+"${flags[@]}"}")" || die "lib/kit_guard.py failed on this command, so the guard cannot judge it."

while IFS=$SEP read -r kind a b; do
  case "$kind" in
    B) echo "guard-main: $a" >&2; exit 2 ;;
    X) checks_refuse "$a" ;;
    W)
      # a git-ignored target stays allowed (.ci/ logs); a not-yet-existing ignored
      # directory is probed through a child path
      if in_main "$a" && ! git -C "$main" check-ignore -q -- "$a" 2>/dev/null &&
        ! git -C "$main" check-ignore -q -- "$a/.probe" 2>/dev/null; then
        block "a shell command writes $a in the main checkout (redirect, tee, sed -i, cp, mv, rm, ...)."
      fi
      ;;
    C)
      in_main "$a" || continue
      if why="$(rule_hit "$b")"; then block "$why ($a)."; fi
      ;;
    G)
      # the one git write allowed in main, the user-requested `merge --ff-only wt/<name>`,
      # is not reported by kit_guard.py
      in_main "$a" && block "mutating git command in the main checkout: $b ($a)."
      ;;
  esac
done <<<"$rows"

exit 0
