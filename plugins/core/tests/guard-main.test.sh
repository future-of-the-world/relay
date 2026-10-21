#!/usr/bin/env bash
# Allow/block cases for hooks/guard-main.sh over a temporary repository, once
# per binding profile (Kartoteka's real kit.toml, and the profiles/ examples).
#   plugins/core/tests/guard-main.test.sh
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd -P)"
hook="$here/../hooks/guard-main.sh"
kartoteka="$here/../../../migration/kartoteka/kit.toml"
unset CLAUDE_PROJECT_DIR

tmp="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT
M="$tmp/repo"
mkdir -p "$M" && cd "$M" && git init -q -b master . \
  && git -c user.name=t -c user.email=t@t commit -q --allow-empty -m init \
  && git worktree add -q .worktrees/any-change -b wt/any-change \
  && git worktree add -q .worktree/any-change -b wt/any-change2 || { echo "guard-main.test: cannot build the repo" >&2; exit 1; }
printf '.ci/\n' >"$M/.gitignore"; printf 'a\n' >"$M/README.md"
mkdir -p "$M/deps/jason" && ln -s "$M/deps" "$M/.worktree/any-change/deps"
fails=0

t() {
  local expect="$1" desc="$2" tool="$3" cwd="$4" key="$5" val="$6" got
  jq -n --arg tool "$tool" --arg cwd "$cwd" --arg key "$key" --arg val "$val" \
    '{tool_name: $tool, cwd: $cwd, tool_input: {($key): $val}}' | "$hook" >/dev/null 2>&1
  [ $? -eq 2 ] && got=block || got=allow
  if [ "$got" = "$expect" ]; then echo "ok    $got  [$profile] $desc"; else echo "FAIL  $got  [$profile] $desc"; fails=$((fails + 1)); fi
}

use() { # <profile name> <kit.toml or ->  <worktrees dir>
  profile="$1"
  mkdir -p "$M/.claude"
  if [ "$2" = - ]; then rm -f "$M/.claude/kit.toml"; else cp "$2" "$M/.claude/kit.toml"; fi
  W="$M/$3/any-change"
  : >"$W/f.txt"
}

# Test strings for the tracing cases, built so this file never contains them literally.
X="-x"; EUX="-euxo"

common() {
  t block "edit main file"             Edit  "$M" file_path "$M/src/main.tsx"
  t block "write main, relative path"  Write "$M" file_path "openspec/changes/new/proposal.md"
  t allow "edit worktree file"         Edit  "$M" file_path "$W/src/main.tsx"
  t allow "write outside the repo"     Write "$M" file_path "$HOME/.claude/projects/x/memory/a.md"
  t allow "Read tool"                  Read  "$M" file_path "$M/CLAUDE.md"
  t block "cd main && commit"          Bash "$W" command "cd $M && git commit -m x"
  t block "git switch in main"         Bash "$M" command "git switch wt/foo"
  t block "git -C main merge"          Bash "$W" command "git -C $M merge wt/foo"
  t block "no-ff merge in main"        Bash "$M" command "git merge --no-ff wt/foo"
  t block "ff-only of non-wt branch"   Bash "$M" command "git merge --ff-only origin/master"
  t allow "ff-only wt/ merge in main"  Bash "$M" command "git merge --ff-only wt/add-library && git log --oneline -1 && bin/wt rm add-library"
  t allow "ff-only with its output cut" Bash "$M" command "git merge --ff-only wt/add-library 2>&1 | tail -3"
  t block "ff-only, redirect, commit"  Bash "$M" command "git merge --ff-only wt/foo 2>&1 && git commit --amend"
  t block "ff-only then commit"        Bash "$M" command "git merge --ff-only wt/foo && git commit --amend"
  t allow "merge in worktree"          Bash "$M" command "git -C $W merge --no-ff wt/foo"
  t allow "status/log in main"         Bash "$M" command "git status && git log --oneline -5"
  t allow "bin/wt new in main"         Bash "$M" command "bin/wt new foo master"
  t block "bare git stash"             Bash "$W" command "git stash"
  t block "git stash pop"              Bash "$W" command "git stash pop"
  t allow "git stash list"             Bash "$W" command "git stash list"
  t block "shell tracing via set"      Bash "$W" command "set $X; ./probe.sh"
  t block "set with x among flags"     Bash "$W" command "set $EUX pipefail; curl -s https://example.com"
  t block "bash tracing a script"      Bash "$W" command "bash $X scripts/release.sh"
  t block "curl -v with auth header"   Bash "$W" command "curl -v -H \"Authorization: token \$FORGEJO_TOKEN\" https://git.example.dev/api/v1/user"
  t allow "curl -v public endpoint"    Bash "$W" command "curl -v https://registry.npmjs.org/preact"
  t allow "chmod +x"                   Bash "$W" command "chmod +x bin/ci"
  t allow "curl -s with auth header"   Bash "$W" command "curl -s -H \"Authorization: token \$FORGEJO_TOKEN\" https://git.example.dev/api/v1/user"
  # writes through the shell
  t block "heredoc into a main file"   Bash "$M" command "cat > docs/handover.md <<'EOF'
new text; more
EOF"
  t block "sed -i on a main file"      Bash "$M" command "sed -i '' 's/a/b/' README.md"
  t block "redirect into main src"     Bash "$M" command "echo hi > src/x.ts"
  t block "append into main file"      Bash "$M" command "echo hi >> README.md"
  t block "rm -rf in main"             Bash "$M" command "rm -rf src"
  t block "tee into main"              Bash "$M" command "echo hi | tee notes.md"
  t block "cp into main"               Bash "$M" command "cp /etc/hosts hosts.txt"
  t block "mv in main"                 Bash "$M" command "mv README.md README.old"
  t block "mkdir in main"              Bash "$M" command "mkdir -p src/new"
  t block "redirect by absolute path from a worktree" Bash "$W" command "echo hi > $M/src/x.ts"
  t block "cd main, then redirect"     Bash "$W" command "cd $M && echo hi > x.txt"
  t allow "redirect to /dev/null"      Bash "$M" command "ls > /dev/null 2>&1"
  t allow "stderr to stdout"           Bash "$M" command "ls 2>&1 | head -3"
  t allow "git-ignored log in main"    Bash "$M" command "mkdir -p .ci && echo ok > .ci/ci.log"
  t allow "redirect in a worktree"     Bash "$W" command "echo hi > src/x.ts && rm -f src/x.ts"
  t allow "redirect into a worktree from main" Bash "$M" command "cp README.md $W/README.copy"
  t allow "quoted > is no redirect"    Bash "$M" command "echo 'a > b' && grep -n \"x > y\" README.md"
  t allow "cat a main file"            Bash "$M" command "cat README.md | head -2"
  # compound commands: every part is judged by its own directory
  t block "worktree log, then merge in main" Bash "$M" command "git -C $W log -1 && git merge wt/foo"
  t block "subshell commit, then reset"      Bash "$M" command "(cd $W && git commit -m x); git reset --hard HEAD~1"
  t block "worktree status, then checkout"   Bash "$M" command "git -C $W status; git checkout -b oops"
  t block "cd worktree, back, then commit"   Bash "$M" command "cd $W && git status && cd $M && git commit -m x"
  t block "pipe then commit"                 Bash "$M" command "git -C $W log | head -1 && git commit -m x"
  t block "command substitution, then commit" Bash "$M" command "echo \$(git -C $W rev-parse HEAD) && git commit -m x"
  t block "if/then commit"                   Bash "$M" command "if true; then git commit -m x; fi"
  t allow "all parts in the worktree"        Bash "$M" command "git -C $W log -1 && git -C $W commit -m x && (cd $W && git merge wt/foo)"
  t allow "read-only parts around a worktree commit" Bash "$M" command "git status && git -C $W commit -m x; git log -1"
  t allow "subshell cd does not leak into main checks" Bash "$W" command "(cd $M && git status); git commit -m x"
  # the stash is shared
  t block "git stash -u"               Bash "$W" command "git stash -u"
  t block "git stash push, no message" Bash "$W" command "git stash push src/a.ts"
  t block "git stash pop with a ref"   Bash "$W" command "git stash pop stash@{0}"
  t block "git -C stash"               Bash "$W" command "git -C $W stash"
  t allow "git stash push -m"          Bash "$W" command "git stash push -m wip"
  t allow "git stash show"             Bash "$W" command "git stash show -p"
  # secrets in the environment
  t block "printenv"                   Bash "$W" command "printenv"
  t block "bare env"                   Bash "$W" command "env | sort"
  t block "export -p"                  Bash "$W" command "export -p"
  t allow "env running a command"      Bash "$W" command "env FOO=1 ls"
  t allow "echo of one variable name"  Bash "$W" command "echo \"home is \$HOME\""
  # git writes spelled around the plain `git <sub>` (review 2, n1)
  t block "git -c before the subcommand"   Bash "$M" command "git -c user.name=x commit -m y"
  t block "git --no-pager -c ... reset"    Bash "$M" command "git --no-pager -c core.x=y reset --hard HEAD~1"
  t block "time git reset"                 Bash "$M" command "time git reset --hard HEAD~1"
  t block "nohup git checkout -b"          Bash "$M" command "nohup git checkout -b x"
  t block "git branch -f"                  Bash "$M" command "git branch -f master HEAD~1"
  t block "git branch -D"                  Bash "$M" command "git branch -D wt/foo"
  t block "git update-ref"                 Bash "$M" command "git update-ref refs/heads/master HEAD~1"
  t block "git tag -d"                     Bash "$M" command "git tag -d v1"
  t block "bash -c with a commit"          Bash "$M" command "bash -c \"git commit -m x\""
  t block "sh -c with a reset"             Bash "$M" command "sh -c 'cd . && git reset --hard HEAD~1'"
  t block "xargs into git reset"           Bash "$M" command "git log --format=%H | xargs -I{} git reset --hard {}"
  t block "cd -, back to main, commit"     Bash "$M" command "cd $W; cd -; git commit -m x"
  t block "cd - with no known previous"    Bash "$W" command "cd -; git commit -m x"
  t block "popd with an empty stack"       Bash "$W" command "popd; git commit -m x"
  t block "pushd, popd, back in main"      Bash "$M" command "pushd $W; popd; git commit -m x"
  t allow "cd - lands in the worktree"     Bash "$M" command "cd $W && cd $M && cd - && git commit -m x"
  t allow "pushd to a worktree"            Bash "$M" command "pushd $W && git commit -m x"
  t allow "git branch lists"               Bash "$M" command "git branch --list 'wt/*'"
  t allow "git tag lists"                  Bash "$M" command "git tag -l"
  t allow "git -c in a worktree"           Bash "$M" command "git -C $W -c user.name=x commit -m y"
  t allow "bash -c, harmless"              Bash "$M" command "bash -c 'git status'"
  t allow "xargs into a harmless git"      Bash "$M" command "git log --format=%H | xargs -n1 git show --stat"
  # shell writes the first version missed (review 2, n2)
  t block "find -delete"                   Bash "$M" command "find src -delete"
  t block "perl -pi"                       Bash "$M" command "perl -pi -e 's/a/b/' README.md"
  t block "xargs rm"                       Bash "$M" command "ls | xargs rm"
  t block "xargs -I rm"                    Bash "$M" command "ls | xargs -I{} rm {}"
  t block "rsync into main"                Bash "$M" command "rsync -a $W/ src/"
  t block "patch from stdin"               Bash "$M" command "patch -p1 < x.diff"
  t block "unzip -o"                       Bash "$M" command "unzip -o x.zip"
  t block "tar -xf"                        Bash "$M" command "tar -xf x.tar"
  t block "tar xzf, old style"             Bash "$M" command "tar xzf x.tgz"
  t allow "find without -delete"           Bash "$M" command "find src -name '*.ts' -print"
  t allow "perl without -i"                Bash "$M" command "perl -ne 'print if /a/' README.md"
  t allow "perl -pi on a worktree file"    Bash "$M" command "perl -pi -e 's/a/b/' $W/f.txt"
  t allow "xargs rm in a worktree"         Bash "$W" command "ls | xargs rm -f"
  t allow "rsync into a worktree"          Bash "$M" command "rsync -a src/ $W/src/"
  t allow "rsync from a remote"            Bash "$W" command "rsync -a host:/data/ out/"
  t allow "unzip -l lists"                 Bash "$M" command "unzip -l x.zip"
  t allow "tar -tf lists"                  Bash "$M" command "tar -tf x.tar"
  t allow "tar -xf into a worktree"        Bash "$M" command "tar -xf x.tar -C $W"
  t allow "unzip into a worktree"          Bash "$M" command "unzip -o x.zip -d $W"
  t allow "patch in a worktree"            Bash "$M" command "patch -p1 -d $W < x.diff"
  # false blocks to remove (review 2, n3)
  t allow "arithmetic expansion"           Bash "$M" command "echo \$(( 3 > 2 ))"
  t allow "(( )) test in a wait loop"      Bash "$M" command "n=4; if (( n > 3 )); then echo big; fi"
  t allow "(( )) for loop"                 Bash "$M" command "for ((i=0;i<3;i++)); do echo \$i; done"
  t allow "touch -t value"                 Bash "$M" command "touch -t 202601010000 $W/f.txt"
  t allow "install -m value"               Bash "$M" command "install -m 755 README.md $W/x.sh"
  t allow "mkdir -m value"                 Bash "$M" command "mkdir -m 755 $W/newdir"
  t allow "ln -s from a main file"         Bash "$M" command "ln -s $M/README.md $W/link"
  t allow "git add --help"                 Bash "$M" command "git add --help"
  t block "touch -t, target in main"       Bash "$M" command "touch -t 202601010000 README.md"
  t block "install into main"              Bash "$M" command "install -m 755 $W/f.txt tool.sh"
  t block "ln -s into main"                Bash "$M" command "ln -s $W/f.txt link"
}

# --- Kartoteka: bun rules, worktrees in .worktrees ---------------------------
use kartoteka "$kartoteka" .worktrees
common
t allow "cd relative worktree"       Bash "$M" command "cd .worktrees/any-change && bin/ci"
t allow "grep for 'cargo test'"      Bash "$M" command "grep -rn 'cargo test' docs"
t block "bun add in main"            Bash "$M" command "bun add @tauri-apps/api"
t block "bun remove in main"         Bash "$M" command "bun remove preact"
t block "bun install in main"        Bash "$M" command "bun install"
t block "bun i in main"              Bash "$M" command "git status && bun i"
t allow "frozen install in main"     Bash "$M" command "bun install --frozen-lockfile"
t block "bun run format in main"     Bash "$M" command "bun run format"
t allow "format:check in main"       Bash "$M" command "bun run format:check"
t block "prettier --write in main"   Bash "$M" command "bunx prettier --write src"
t block "eslint --fix in main"       Bash "$M" command "bun run lint --fix"
t block "snapshot update in main"    Bash "$M" command "bun run test -u"
t allow "bun run check in main"      Bash "$M" command "bun run check"
t allow "bun run dev in main"        Bash "$M" command "bun run dev"
t allow "bin/ci --check in main"     Bash "$M" command "bin/ci --check"
t allow "bun add in worktree cwd"    Bash "$W" command "bun add @tauri-apps/api"
t allow "cd worktree && bun add"     Bash "$M" command "cd $W && bun add @tauri-apps/api"
t allow "bun --cwd worktree"         Bash "$M" command "bun --cwd $W run format"
t block "bun --cwd main from wt"     Bash "$W" command "bun add --cwd $M zod"
t allow "bun info is not install"    Bash "$M" command "bun info preact"
t allow "commit message says cargo"  Bash "$W" command "git commit -m 'run cargo fmt'"
t allow "cargo is no rule here"      Bash "$M" command "cargo test"

# --- Rust and Tauri (Clean, Mind) ---------------------------------------------
use tauri "$here/profiles/tauri.toml" .worktrees
common
t block "cargo in main src-tauri"    Bash "$M" command "cd src-tauri && cargo clippy"
t block "env-prefixed cargo in main" Bash "$M" command "RUST_BACKTRACE=1 cargo test"
t block "manifest-path into main"    Bash "$W" command "cargo build --manifest-path $M/src-tauri/Cargo.toml"
t allow "cargo in worktree cwd"      Bash "$W" command "cd src-tauri && cargo clippy"
t allow "cd worktree && cargo"       Bash "$M" command "cd $W/src-tauri && cargo clippy"
t allow "tauri info in main"         Bash "$M" command "bun run tauri info"
t allow "tauri dev in main"          Bash "$M" command "bun run tauri dev"
t block "tauri add in main"          Bash "$M" command "bun run tauri add haptics"
t block "tauri ios init in main"     Bash "$M" command "bun run tauri ios init"
t block "tauri icon in main"         Bash "$M" command "bunx tauri icon src-tauri/app-icon.svg"
t allow "tauri add in worktree"      Bash "$W" command "bun run tauri add haptics"
t allow "commit message says cargo"  Bash "$W" command "git commit -m 'run cargo fmt'"

# --- Elixir (ALIX): worktrees in .worktree, key patterns, symlinked deps/ -------
use mix "$here/profiles/mix.toml" .worktree
common
t block "edit through deps symlink"  Edit "$M" file_path "$W/deps/jason/mix.exs"
t block "mix test in main"           Bash "$M" command "mix test"
t block "env-prefixed mix in main"   Bash "$M" command "ALIX_EXCHANGE_KEY=x mix test --only venue"
t allow "mix in worktree cwd"        Bash "$W" command "mix test"
t allow "cd worktree && mix"         Bash "$M" command "cd $W && mix ci"
t allow "cd relative worktree"       Bash "$M" command "cd .worktree/any-change && mix ci"
t allow "grep for 'mix test'"        Bash "$M" command "grep -rn 'mix test' docs"
t allow "commit message says mix"    Bash "$W" command "git commit -m 'run mix format'"
t block "curl -v with key header"    Bash "$W" command "curl -v -H \"X-BAPI-API-KEY: \$ALIX_EXCHANGE_KEY\" https://api-demo.bybit.com/v5/account"
t allow "curl -v public endpoint"    Bash "$W" command "curl -v https://api-demo.bybit.com/v5/market/time"
t allow "curl -s with key header"    Bash "$W" command "curl -s -H \"X-BAPI-API-KEY: \$ALIX_EXCHANGE_KEY\" https://api-demo.bybit.com/v5/account"
t allow "the other worktrees dir is main" Bash "$M" command "cd .worktrees/any-change && git status"
t block "edit in the unlisted .worktrees dir" Edit "$M" file_path "$M/.worktrees/any-change/x.ex"

# --- every bun-like tool blocked (Glyph) ---------------------------------------
use bun-all "$here/profiles/bun-all.toml" .worktree
common
t block "bun test in main"           Bash "$M" command "bun test"
t block "acton build in main"        Bash "$M" command "acton build"
t block "bunx in main"               Bash "$M" command "bunx vite build"
t block "env-prefixed bun in main"   Bash "$M" command "TONCENTER_KEY=x bun test"
t allow "bun in worktree cwd"        Bash "$W" command "bun test"
t allow "cd worktree && bun"         Bash "$M" command "cd $W && bun run check"
t allow "grep for 'bun test'"        Bash "$M" command "grep -rn 'bun test' docs"
t block "curl -v with key header"    Bash "$W" command "curl -v -H \"Authorization: \$TONCENTER_API_KEY\" https://testnet.toncenter.com/api/v2/getAddressInformation"

# --- no kit.toml: the generic rules only ---------------------------------------
use none - .worktrees
common
t allow "stack commands are no rule" Bash "$M" command "bun add zod"

# A kit.toml that cannot be read never silently drops the project's rules.
printf '[gate\n' >"$M/.claude/kit.toml"
profile=broken
for tool_cwd in "Bash $W command ls" "Edit $M file_path $W/a.txt"; do
  # shellcheck disable=SC2086
  set -- $tool_cwd
  out="$(jq -n --arg tool "$1" --arg cwd "$2" --arg key "$3" --arg val "$4" '{tool_name: $tool, cwd: $cwd, tool_input: {($key): $val}}' | "$hook" 2>&1 >/dev/null)"; rc=$?
  if [ "$rc" -eq 2 ] && grep -q "kit.toml is unreadable" <<<"$out"; then echo "ok    block  [broken] unreadable kit.toml, $1"; else echo "FAIL  rc=$rc [broken] unreadable kit.toml, $1: $out"; fails=$((fails + 1)); fi
done
rm -f "$M/.claude/kit.toml"

# Outside any repository nothing is guarded.
t allow "a directory outside any repo" Edit "$tmp" file_path "$tmp/x.txt"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
