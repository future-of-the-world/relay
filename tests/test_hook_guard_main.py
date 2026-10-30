"""Port of plugins/relay/tests/guard-main.test.sh: allow/block cases for hooks/guard-main.sh over a temporary repository, once
per binding profile (a copy of Kartoteka's kit.toml, and the profiles/ examples). Each case is
(expect, description, tool, cwd, input key, input value); @M@ is the main checkout, @W@ the worktree of the profile,
@WD@ its worktrees directory, @TMP@ a temp dir, @HOME@ the home directory. The cases run as a subagent (agent_id set): the main
session's cd into a worktree is refused on its own (tests/test_front_cd.py), and these cases judge the other rules.
RELAY_QUICK=1 (bin/ci --quick): the shared cases (COMMON) run once, under Kartoteka's kit.toml; each profile's own cases always
run. Without it every profile runs all cases."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple

from hook_helpers import ROOT, SoftCases

CORE = os.path.join(ROOT, "plugins", "relay")
HOOK = os.path.join(CORE, "hooks", "guard-main.sh")
PROFILES = os.path.join(CORE, "tests", "profiles")
Case = Tuple[str, str, str, str, str, str]

COMMON = [
    ('block', 'edit main file', 'Edit', '@M@', 'file_path', '@M@/src/main.tsx'),
    ('block', 'write main, relative path', 'Write', '@M@', 'file_path', 'openspec/changes/new/proposal.md'),
    ('allow', 'edit worktree file', 'Edit', '@M@', 'file_path', '@W@/src/main.tsx'),
    ('allow', 'write outside the repo', 'Write', '@M@', 'file_path', '@HOME@/.claude/projects/x/memory/a.md'),
    ('allow', 'Read tool', 'Read', '@M@', 'file_path', '@M@/CLAUDE.md'),
    ('block', 'cd main && commit', 'Bash', '@W@', 'command', 'cd @M@ && git commit -m x'),
    ('block', 'git switch in main', 'Bash', '@M@', 'command', 'git switch wt/foo'),
    ('block', 'git -C main merge', 'Bash', '@W@', 'command', 'git -C @M@ merge wt/foo'),
    ('block', 'no-ff merge in main', 'Bash', '@M@', 'command', 'git merge --no-ff wt/foo'),
    ('block', 'ff-only of non-wt branch', 'Bash', '@M@', 'command', 'git merge --ff-only some-branch'),
    ('allow', 'ff-only origin/default sync', 'Bash', '@M@', 'command', 'git merge --ff-only origin/master'),
    ('block', 'ff-only FETCH_HEAD', 'Bash', '@M@', 'command', 'git merge --ff-only FETCH_HEAD'),
    ('block', 'fetch . then ff-only FETCH_HEAD', 'Bash', '@M@', 'command', 'git fetch . side && git merge --ff-only FETCH_HEAD'),
    ('block', 'ff-only --no-ff origin/default', 'Bash', '@M@', 'command', 'git merge --ff-only --no-ff --no-edit origin/master'),
    ('block', 'merge origin/default', 'Bash', '@M@', 'command', 'git merge origin/master'),
    ('block', 'ff-only other remote', 'Bash', '@M@', 'command', 'git merge --ff-only upstream/master'),
    ('allow', 'ff-only wt/ merge in main', 'Bash', '@M@', 'command', 'git merge --ff-only wt/add-library && git log --oneline -1 && bin/wt rm add-library'),
    ('allow', 'ff-only with its output cut', 'Bash', '@M@', 'command', 'git merge --ff-only wt/add-library 2>&1 | tail -3'),
    ('block', 'ff-only, redirect, commit', 'Bash', '@M@', 'command', 'git merge --ff-only wt/foo 2>&1 && git commit --amend'),
    ('block', 'ff-only then commit', 'Bash', '@M@', 'command', 'git merge --ff-only wt/foo && git commit --amend'),
    ('allow', 'merge in worktree', 'Bash', '@M@', 'command', 'git -C @W@ merge --no-ff wt/foo'),
    ('allow', 'status/log in main', 'Bash', '@M@', 'command', 'git status && git log --oneline -5'),
    ('allow', 'bin/wt new in main', 'Bash', '@M@', 'command', 'bin/wt new foo master'),
    ('block', 'bare git stash', 'Bash', '@W@', 'command', 'git stash'),
    ('block', 'git stash pop', 'Bash', '@W@', 'command', 'git stash pop'),
    ('allow', 'git stash list', 'Bash', '@W@', 'command', 'git stash list'),
    ('block', 'shell tracing via set', 'Bash', '@W@', 'command', 'set -x; ./probe.sh'),
    ('block', 'set with x among flags', 'Bash', '@W@', 'command', 'set -euxo pipefail; curl -s https://example.com'),
    ('block', 'bash tracing a script', 'Bash', '@W@', 'command', 'bash -x scripts/release.sh'),
    ('block', 'curl -v with auth header', 'Bash', '@W@', 'command', 'curl -v -H "Authorization: token $FORGEJO_TOKEN" https://git.example.dev/api/v1/user'),
    ('allow', 'curl -v public endpoint', 'Bash', '@W@', 'command', 'curl -v https://registry.npmjs.org/preact'),
    ('allow', 'chmod +x', 'Bash', '@W@', 'command', 'chmod +x bin/ci'),
    ('allow', 'curl -s with auth header', 'Bash', '@W@', 'command', 'curl -s -H "Authorization: token $FORGEJO_TOKEN" https://git.example.dev/api/v1/user'),
    ('block', 'heredoc into a main file', 'Bash', '@M@', 'command', "cat > docs/handover.md <<'EOF'\nnew text; more\nEOF"),
    ('block', 'sed -i on a main file', 'Bash', '@M@', 'command', "sed -i '' 's/a/b/' README.md"),
    ('block', 'redirect into main src', 'Bash', '@M@', 'command', 'echo hi > src/x.ts'),
    ('block', 'append into main file', 'Bash', '@M@', 'command', 'echo hi >> README.md'),
    ('block', 'rm -rf in main', 'Bash', '@M@', 'command', 'rm -rf src'),
    ('block', 'tee into main', 'Bash', '@M@', 'command', 'echo hi | tee notes.md'),
    ('block', 'cp into main', 'Bash', '@M@', 'command', 'cp /etc/hosts hosts.txt'),
    ('block', 'mv in main', 'Bash', '@M@', 'command', 'mv README.md README.old'),
    ('block', 'mkdir in main', 'Bash', '@M@', 'command', 'mkdir -p src/new'),
    ('block', 'redirect by absolute path from a worktree', 'Bash', '@W@', 'command', 'echo hi > @M@/src/x.ts'),
    ('block', 'cd main, then redirect', 'Bash', '@W@', 'command', 'cd @M@ && echo hi > x.txt'),
    ('allow', 'redirect to /dev/null', 'Bash', '@M@', 'command', 'ls > /dev/null 2>&1'),
    ('allow', 'stderr to stdout', 'Bash', '@M@', 'command', 'ls 2>&1 | head -3'),
    ('allow', 'git-ignored log in main', 'Bash', '@M@', 'command', 'mkdir -p .ci && echo ok > .ci/ci.log'),
    ('block', 'unquoted unknown $F is read literally', 'Bash', '@M@', 'command', 'touch $F'),
    ('block', '$PWD is the tracked directory', 'Bash', '@M@', 'command', 'rm -rf $PWD/src'),
    ('block', '$PWD after cd to main, from a worktree', 'Bash', '@W@', 'command', 'cd @M@ && rm -rf $PWD/src'),
    ('allow', '$PWD in a worktree', 'Bash', '@W@', 'command', 'rm -rf $PWD/src'),
    ('block', 'unknown variable in a path under main', 'Bash', '@M@', 'command', 'echo hi > .worktrees/$N/../../README.md'),
    ('block', 'cd to an unknown variable stays in main', 'Bash', '@M@', 'command', 'cd .worktrees/$NAME && git commit -m x'),
    ('allow', 'quoted unknown $F is skipped', 'Bash', '@M@', 'command', 'touch "$F"'),
    ('allow', 'variable path outside main (brief case)', 'Bash', '@M@', 'command', "S=@TMP@/scratch; mkdir -p $S/briefs $S/reports; cat > $S/drop.toml <<'EOF'\nx = 1\nEOF"),
    ('block', 'variable pointing into main, from a worktree', 'Bash', '@W@', 'command', 'X=@M@; touch $X/x'),
    ('block', 'quoted variable pointing into main', 'Bash', '@W@', 'command', 'X=@M@; touch "$X/x"'),
    ('block', 'export and braces, path in main', 'Bash', '@W@', 'command', 'export X=@M@ && touch ${X}/x'),
    ('allow', 'git -C var to a worktree, relative', 'Bash', '@M@', 'command', 'G=@WD@/any-change; git -C $G commit -m x'),
    ('block', 'git -C var to main', 'Bash', '@W@', 'command', 'G=@M@; git -C $G commit -m x'),
    ('allow', 'TMPDIR from the hook environment', 'Bash', '@M@', 'command', 'touch $TMPDIR/x'),
    ('allow', 'variable assigned twice is not followed', 'Bash', '@W@', 'command', 'X=@TMP@/ok; X=@M@; touch $X/x'),
    ('allow', 'name in a commit message', 'Bash', '@M@', 'command', "G=@WD@/any-change; git -C $G commit -m 'G fix'"),
    ('allow', 'name in a later echo', 'Bash', '@M@', 'command', 'wt=@WD@/any-change; git -C $wt branch -d x && echo wt gone'),
    ('block', 'name in a later echo, main target', 'Bash', '@W@', 'command', 'M=@M@; touch $M/x && echo M done'),
    ('block', 'unset makes the name unknown', 'Bash', '@M@', 'command', 'W=@WD@/any-change; unset W; git -C $W commit -m x'),
    ('block', '+= makes the name unknown', 'Bash', '@M@', 'command', 'W=@WD@/any-change; W+=/..; git -C $W commit -m x'),
    ('allow', 'redirect in a worktree', 'Bash', '@W@', 'command', 'echo hi > src/x.ts && rm -f src/x.ts'),
    ('allow', 'redirect into a worktree from main', 'Bash', '@M@', 'command', 'cp README.md @W@/README.copy'),
    ('allow', 'quoted > is no redirect', 'Bash', '@M@', 'command', 'echo \'a > b\' && grep -n "x > y" README.md'),
    ('allow', 'cat a main file', 'Bash', '@M@', 'command', 'cat README.md | head -2'),
    ('block', 'worktree log, then merge in main', 'Bash', '@M@', 'command', 'git -C @W@ log -1 && git merge wt/foo'),
    ('block', 'subshell commit, then reset', 'Bash', '@M@', 'command', '(cd @W@ && git commit -m x); git reset --hard HEAD~1'),
    ('block', 'worktree status, then checkout', 'Bash', '@M@', 'command', 'git -C @W@ status; git checkout -b oops'),
    ('block', 'cd worktree, back, then commit', 'Bash', '@M@', 'command', 'cd @W@ && git status && cd @M@ && git commit -m x'),
    ('block', 'pipe then commit', 'Bash', '@M@', 'command', 'git -C @W@ log | head -1 && git commit -m x'),
    ('block', 'command substitution, then commit', 'Bash', '@M@', 'command', 'echo $(git -C @W@ rev-parse HEAD) && git commit -m x'),
    ('block', 'if/then commit', 'Bash', '@M@', 'command', 'if true; then git commit -m x; fi'),
    ('allow', 'all parts in the worktree', 'Bash', '@M@', 'command', 'git -C @W@ log -1 && git -C @W@ commit -m x && (cd @W@ && git merge wt/foo)'),
    ('allow', 'read-only parts around a worktree commit', 'Bash', '@M@', 'command', 'git status && git -C @W@ commit -m x; git log -1'),
    ('allow', 'subshell cd does not leak into main checks', 'Bash', '@W@', 'command', '(cd @M@ && git status); git commit -m x'),
    ('block', 'git stash -u', 'Bash', '@W@', 'command', 'git stash -u'),
    ('block', 'git stash push, no message', 'Bash', '@W@', 'command', 'git stash push src/a.ts'),
    ('block', 'git stash pop with a ref', 'Bash', '@W@', 'command', 'git stash pop stash@{0}'),
    ('block', 'git -C stash', 'Bash', '@W@', 'command', 'git -C @W@ stash'),
    ('allow', 'git stash push -m', 'Bash', '@W@', 'command', 'git stash push -m wip'),
    ('allow', 'git stash show', 'Bash', '@W@', 'command', 'git stash show -p'),
    ('block', 'printenv', 'Bash', '@W@', 'command', 'printenv'),
    ('block', 'bare env', 'Bash', '@W@', 'command', 'env | sort'),
    ('block', 'export -p', 'Bash', '@W@', 'command', 'export -p'),
    ('allow', 'env running a command', 'Bash', '@W@', 'command', 'env FOO=1 ls'),
    ('allow', 'echo of one variable name', 'Bash', '@W@', 'command', 'echo "home is $HOME"'),
    ('block', 'git -c before the subcommand', 'Bash', '@M@', 'command', 'git -c user.name=x commit -m y'),
    ('block', 'git --no-pager -c ... reset', 'Bash', '@M@', 'command', 'git --no-pager -c core.x=y reset --hard HEAD~1'),
    ('block', 'time git reset', 'Bash', '@M@', 'command', 'time git reset --hard HEAD~1'),
    ('block', 'nohup git checkout -b', 'Bash', '@M@', 'command', 'nohup git checkout -b x'),
    ('block', 'git branch -f', 'Bash', '@M@', 'command', 'git branch -f master HEAD~1'),
    ('block', 'git branch -D', 'Bash', '@M@', 'command', 'git branch -D wt/foo'),
    ('block', 'git update-ref', 'Bash', '@M@', 'command', 'git update-ref refs/heads/master HEAD~1'),
    ('block', 'git tag -d', 'Bash', '@M@', 'command', 'git tag -d v1'),
    ('block', 'bash -c with a commit', 'Bash', '@M@', 'command', 'bash -c "git commit -m x"'),
    ('block', 'sh -c with a reset', 'Bash', '@M@', 'command', "sh -c 'cd . && git reset --hard HEAD~1'"),
    ('block', 'xargs into git reset', 'Bash', '@M@', 'command', 'git log --format=%H | xargs -I{} git reset --hard {}'),
    ('block', 'cd -, back to main, commit', 'Bash', '@M@', 'command', 'cd @W@; cd -; git commit -m x'),
    ('block', 'cd - with no known previous', 'Bash', '@W@', 'command', 'cd -; git commit -m x'),
    ('block', 'popd with an empty stack', 'Bash', '@W@', 'command', 'popd; git commit -m x'),
    ('block', 'pushd, popd, back in main', 'Bash', '@M@', 'command', 'pushd @W@; popd; git commit -m x'),
    ('allow', 'cd - lands in the worktree', 'Bash', '@M@', 'command', 'cd @W@ && cd @M@ && cd - && git commit -m x'),
    ('allow', 'pushd to a worktree', 'Bash', '@M@', 'command', 'pushd @W@ && git commit -m x'),
    ('allow', 'git branch lists', 'Bash', '@M@', 'command', "git branch --list 'wt/*'"),
    ('allow', 'git tag lists', 'Bash', '@M@', 'command', 'git tag -l'),
    ('allow', 'git -c in a worktree', 'Bash', '@M@', 'command', 'git -C @W@ -c user.name=x commit -m y'),
    ('allow', 'bash -c, harmless', 'Bash', '@M@', 'command', "bash -c 'git status'"),
    ('allow', 'xargs into a harmless git', 'Bash', '@M@', 'command', 'git log --format=%H | xargs -n1 git show --stat'),
    ('block', 'find -delete', 'Bash', '@M@', 'command', 'find src -delete'),
    ('block', 'perl -pi', 'Bash', '@M@', 'command', "perl -pi -e 's/a/b/' README.md"),
    ('block', 'xargs rm', 'Bash', '@M@', 'command', 'ls | xargs rm'),
    ('block', 'xargs -I rm', 'Bash', '@M@', 'command', 'ls | xargs -I{} rm {}'),
    ('block', 'rsync into main', 'Bash', '@M@', 'command', 'rsync -a @W@/ src/'),
    ('block', 'patch from stdin', 'Bash', '@M@', 'command', 'patch -p1 < x.diff'),
    ('block', 'unzip -o', 'Bash', '@M@', 'command', 'unzip -o x.zip'),
    ('block', 'tar -xf', 'Bash', '@M@', 'command', 'tar -xf x.tar'),
    ('block', 'tar xzf, old style', 'Bash', '@M@', 'command', 'tar xzf x.tgz'),
    ('allow', 'find without -delete', 'Bash', '@M@', 'command', "find src -name '*.ts' -print"),
    ('allow', 'perl without -i', 'Bash', '@M@', 'command', "perl -ne 'print if /a/' README.md"),
    ('allow', 'perl -pi on a worktree file', 'Bash', '@M@', 'command', "perl -pi -e 's/a/b/' @W@/f.txt"),
    ('allow', 'xargs rm in a worktree', 'Bash', '@W@', 'command', 'ls | xargs rm -f'),
    ('allow', 'rsync into a worktree', 'Bash', '@M@', 'command', 'rsync -a src/ @W@/src/'),
    ('allow', 'rsync from a remote', 'Bash', '@W@', 'command', 'rsync -a host:/data/ out/'),
    ('allow', 'unzip -l lists', 'Bash', '@M@', 'command', 'unzip -l x.zip'),
    ('allow', 'tar -tf lists', 'Bash', '@M@', 'command', 'tar -tf x.tar'),
    ('allow', 'tar -xf into a worktree', 'Bash', '@M@', 'command', 'tar -xf x.tar -C @W@'),
    ('allow', 'unzip into a worktree', 'Bash', '@M@', 'command', 'unzip -o x.zip -d @W@'),
    ('allow', 'patch in a worktree', 'Bash', '@M@', 'command', 'patch -p1 -d @W@ < x.diff'),
    ('allow', 'arithmetic expansion', 'Bash', '@M@', 'command', 'echo $(( 3 > 2 ))'),
    ('allow', '(( )) test in a wait loop', 'Bash', '@M@', 'command', 'n=4; if (( n > 3 )); then echo big; fi'),
    ('allow', '(( )) for loop', 'Bash', '@M@', 'command', 'for ((i=0;i<3;i++)); do echo $i; done'),
    ('allow', 'touch -t value', 'Bash', '@M@', 'command', 'touch -t 202601010000 @W@/f.txt'),
    ('allow', 'install -m value', 'Bash', '@M@', 'command', 'install -m 755 README.md @W@/x.sh'),
    ('allow', 'mkdir -m value', 'Bash', '@M@', 'command', 'mkdir -m 755 @W@/newdir'),
    ('allow', 'ln -s from a main file', 'Bash', '@M@', 'command', 'ln -s @M@/README.md @W@/link'),
    ('allow', 'git add --help', 'Bash', '@M@', 'command', 'git add --help'),
    ('block', 'touch -t, target in main', 'Bash', '@M@', 'command', 'touch -t 202601010000 README.md'),
    ('block', 'install into main', 'Bash', '@M@', 'command', 'install -m 755 @W@/f.txt tool.sh'),
    ('block', 'ln -s into main', 'Bash', '@M@', 'command', 'ln -s @W@/f.txt link'),
]

KARTOTEKA = [
    ('allow', 'cd relative worktree', 'Bash', '@M@', 'command', 'cd .worktrees/any-change && bin/ci'),
    ('allow', "grep for 'cargo test'", 'Bash', '@M@', 'command', "grep -rn 'cargo test' docs"),
    ('block', 'bun add in main', 'Bash', '@M@', 'command', 'bun add @tauri-apps/api'),
    ('block', 'bun remove in main', 'Bash', '@M@', 'command', 'bun remove preact'),
    ('block', 'bun install in main', 'Bash', '@M@', 'command', 'bun install'),
    ('block', 'bun i in main', 'Bash', '@M@', 'command', 'git status && bun i'),
    ('allow', 'frozen install in main', 'Bash', '@M@', 'command', 'bun install --frozen-lockfile'),
    ('block', 'bun run format in main', 'Bash', '@M@', 'command', 'bun run format'),
    ('allow', 'format:check in main', 'Bash', '@M@', 'command', 'bun run format:check'),
    ('block', 'prettier --write in main', 'Bash', '@M@', 'command', 'bunx prettier --write src'),
    ('block', 'eslint --fix in main', 'Bash', '@M@', 'command', 'bun run lint --fix'),
    ('block', 'snapshot update in main', 'Bash', '@M@', 'command', 'bun run test -u'),
    ('allow', 'bun run check in main', 'Bash', '@M@', 'command', 'bun run check'),
    ('allow', 'bun run dev in main', 'Bash', '@M@', 'command', 'bun run dev'),
    ('allow', 'bin/ci --check in main', 'Bash', '@M@', 'command', 'bin/ci --check'),
    ('allow', 'bun add in worktree cwd', 'Bash', '@W@', 'command', 'bun add @tauri-apps/api'),
    ('allow', 'cd worktree && bun add', 'Bash', '@M@', 'command', 'cd @W@ && bun add @tauri-apps/api'),
    ('allow', 'bun --cwd worktree', 'Bash', '@M@', 'command', 'bun --cwd @W@ run format'),
    ('block', 'bun --cwd main from wt', 'Bash', '@W@', 'command', 'bun add --cwd @M@ zod'),
    ('allow', 'bun info is not install', 'Bash', '@M@', 'command', 'bun info preact'),
    ('allow', 'commit message says cargo', 'Bash', '@W@', 'command', "git commit -m 'run cargo fmt'"),
    ('allow', 'cargo is no rule here', 'Bash', '@M@', 'command', 'cargo test'),
]

TAURI = [
    ('block', 'cargo in main src-tauri', 'Bash', '@M@', 'command', 'cd src-tauri && cargo clippy'),
    ('block', 'env-prefixed cargo in main', 'Bash', '@M@', 'command', 'RUST_BACKTRACE=1 cargo test'),
    ('block', 'manifest-path into main', 'Bash', '@W@', 'command', 'cargo build --manifest-path @M@/src-tauri/Cargo.toml'),
    ('allow', 'cargo in worktree cwd', 'Bash', '@W@', 'command', 'cd src-tauri && cargo clippy'),
    ('allow', 'cd worktree && cargo', 'Bash', '@M@', 'command', 'cd @W@/src-tauri && cargo clippy'),
    ('allow', 'tauri info in main', 'Bash', '@M@', 'command', 'bun run tauri info'),
    ('allow', 'tauri dev in main', 'Bash', '@M@', 'command', 'bun run tauri dev'),
    ('block', 'tauri add in main', 'Bash', '@M@', 'command', 'bun run tauri add haptics'),
    ('block', 'tauri ios init in main', 'Bash', '@M@', 'command', 'bun run tauri ios init'),
    ('block', 'tauri icon in main', 'Bash', '@M@', 'command', 'bunx tauri icon src-tauri/app-icon.svg'),
    ('allow', 'tauri add in worktree', 'Bash', '@W@', 'command', 'bun run tauri add haptics'),
    ('allow', 'commit message says cargo', 'Bash', '@W@', 'command', "git commit -m 'run cargo fmt'"),
]

MIX = [
    ('block', 'edit through deps symlink', 'Edit', '@M@', 'file_path', '@W@/deps/jason/mix.exs'),
    ('block', 'mix test in main', 'Bash', '@M@', 'command', 'mix test'),
    ('block', 'env-prefixed mix in main', 'Bash', '@M@', 'command', 'ALIX_EXCHANGE_KEY=x mix test --only venue'),
    ('allow', 'mix in worktree cwd', 'Bash', '@W@', 'command', 'mix test'),
    ('allow', 'cd worktree && mix', 'Bash', '@M@', 'command', 'cd @W@ && mix ci'),
    ('allow', 'cd relative worktree', 'Bash', '@M@', 'command', 'cd .worktree/any-change && mix ci'),
    ('allow', "grep for 'mix test'", 'Bash', '@M@', 'command', "grep -rn 'mix test' docs"),
    ('allow', 'commit message says mix', 'Bash', '@W@', 'command', "git commit -m 'run mix format'"),
    ('block', 'curl -v with key header', 'Bash', '@W@', 'command', 'curl -v -H "X-BAPI-API-KEY: $ALIX_EXCHANGE_KEY" https://api-demo.bybit.com/v5/account'),
    ('allow', 'curl -v public endpoint', 'Bash', '@W@', 'command', 'curl -v https://api-demo.bybit.com/v5/market/time'),
    ('allow', 'curl -s with key header', 'Bash', '@W@', 'command', 'curl -s -H "X-BAPI-API-KEY: $ALIX_EXCHANGE_KEY" https://api-demo.bybit.com/v5/account'),
    ('allow', 'the other worktrees dir is main', 'Bash', '@M@', 'command', 'cd .worktrees/any-change && git status'),
    ('allow', 'edit in a registered worktree of the other dir', 'Edit', '@M@', 'file_path', '@M@/.worktrees/any-change/x.ex'),
    ('block', 'edit in the other dir, not a worktree', 'Edit', '@M@', 'file_path', '@M@/.worktrees/nothing/x.ex'),
]

BUN_ALL = [
    ('block', 'bun test in main', 'Bash', '@M@', 'command', 'bun test'),
    ('block', 'acton build in main', 'Bash', '@M@', 'command', 'acton build'),
    ('block', 'bunx in main', 'Bash', '@M@', 'command', 'bunx vite build'),
    ('block', 'env-prefixed bun in main', 'Bash', '@M@', 'command', 'TONCENTER_KEY=x bun test'),
    ('allow', 'bun in worktree cwd', 'Bash', '@W@', 'command', 'bun test'),
    ('allow', 'cd worktree && bun', 'Bash', '@M@', 'command', 'cd @W@ && bun run check'),
    ('allow', "grep for 'bun test'", 'Bash', '@M@', 'command', "grep -rn 'bun test' docs"),
    ('block', 'curl -v with key header', 'Bash', '@W@', 'command', 'curl -v -H "Authorization: $TONCENTER_API_KEY" https://testnet.toncenter.com/api/v2/getAddressInformation'),
]

NONE = [
    ('allow', 'stack commands are no rule', 'Bash', '@M@', 'command', 'bun add zod'),
    # no kit.toml: the git-registered worktree .worktree/any-change (ALIX's bin/wt folder) is a task worktree whatever its folder
    ('allow', 'edit in a worktree of an unlisted folder', 'Edit', '@M@', 'file_path', '@M@/.worktree/any-change/x.ex'),
    ('allow', 'git -C into that worktree', 'Bash', '@M@', 'command', 'git -C @M@/.worktree/any-change commit --allow-empty -m x'),
    ('block', 'main file is still main (the main entry is not exempt)', 'Edit', '@M@', 'file_path', '@M@/README.md'),
    ('block', 'a file named like the worktree', 'Edit', '@M@', 'file_path', '@M@/.worktree/any-change.txt'),
    ('block', 'through the deps symlink into main', 'Edit', '@M@', 'file_path', '@M@/.worktree/any-change/deps/jason/x.ex'),
    ('block', 'commit in main', 'Bash', '@M@', 'command', 'git commit --allow-empty -m x'),
]

BROKEN = [
    ('allow', 'a directory outside any repo', 'Edit', '@TMP@', 'file_path', '@TMP@/x.txt'),
]

# profile name -> (kit.toml or None, worktrees dir, its own cases)
PROFILE_SETUP = {
    "kartoteka": (os.path.join(PROFILES, "kartoteka.toml"), ".worktrees", KARTOTEKA),
    "tauri": (os.path.join(PROFILES, "tauri.toml"), ".worktrees", TAURI),
    "mix": (os.path.join(PROFILES, "mix.toml"), ".worktree", MIX),
    "bun-all": (os.path.join(PROFILES, "bun-all.toml"), ".worktree", BUN_ALL),
    "none": (None, ".worktrees", NONE),
}


def git(cwd: str, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(args), cwd=cwd, check=True, capture_output=True)


class Guard(SoftCases):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = os.path.realpath(tempfile.mkdtemp())

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def mkrepo(self, name: str) -> str:
        """A fresh repository with a worktree in each of the two directories the profiles use."""
        m = os.path.join(self.tmp, name)
        os.makedirs(m)
        git(m, "init", "-q", "-b", "master", ".")
        git(m, "commit", "-q", "--allow-empty", "-m", "init")
        git(m, "worktree", "add", "-q", ".worktrees/any-change", "-b", "wt/any-change")
        git(m, "worktree", "add", "-q", ".worktree/any-change", "-b", "wt/any-change2")
        with open(os.path.join(m, ".gitignore"), "w") as handle:
            handle.write(".ci/\n")
        with open(os.path.join(m, "README.md"), "w") as handle:
            handle.write("a\n")
        os.makedirs(os.path.join(m, "deps", "jason"))
        os.symlink(os.path.join(m, "deps"), os.path.join(m, ".worktree", "any-change", "deps"))
        return m

    def verdicts(self, m: str, worktrees: str, cases: List[Case]) -> List[str]:
        w = os.path.join(m, worktrees, "any-change")
        open(os.path.join(w, "f.txt"), "w").close()
        subs = {"@M@": m, "@W@": w, "@WD@": worktrees, "@TMP@": self.tmp, "@HOME@": os.path.join(self.tmp, "home")}
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        env["TMPDIR"] = self.tmp

        def sub(text: str) -> str:
            for key, val in subs.items():
                text = text.replace(key, val)
            return text

        def one(case: Case) -> str:
            _, _, tool, cwd, key, val = case
            event = {"tool_name": tool, "cwd": sub(cwd), "agent_id": "a1", "tool_input": {key: sub(val)}}
            done = subprocess.run([HOOK], input=json.dumps(event), capture_output=True, text=True, env=env)
            return "block" if done.returncode == 2 else "allow"

        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(one, cases))

    def run_profile(self, profile: str) -> None:
        toml, worktrees, own = PROFILE_SETUP[profile]
        m = self.mkrepo(profile)
        os.makedirs(os.path.join(m, ".claude"))
        if toml:
            shutil.copy(toml, os.path.join(m, ".claude", "kit.toml"))
        cases = ([] if os.environ.get("RELAY_QUICK") == "1" and profile != "kartoteka" else COMMON) + own
        got = self.verdicts(m, worktrees, cases)
        bad = ["%s [%s] %s" % (v, profile, c[1]) for v, c in zip(got, cases) if v != c[0]]
        self.assertEqual(bad, [])

    def test_kartoteka(self) -> None:
        self.run_profile("kartoteka")

    def test_tauri(self) -> None:
        self.run_profile("tauri")

    def test_mix(self) -> None:
        self.run_profile("mix")

    def test_bun_all(self) -> None:
        self.run_profile("bun-all")

    def test_no_kit_toml_only_the_generic_rules(self) -> None:
        self.run_profile("none")

    def test_the_guard_starts_no_grep(self) -> None:
        # A grep earlier on PATH than the real one logs every start. Judging a command against the tracing, curl and
        # project patterns (kartoteka has [[guard.block]] rules) must start none: the patterns are matched in Python.
        m = self.mkrepo("nogrep")
        os.makedirs(os.path.join(m, ".claude"))
        shutil.copy(PROFILE_SETUP["kartoteka"][0], os.path.join(m, ".claude", "kit.toml"))
        fake = os.path.join(self.tmp, "fakebin")
        log = os.path.join(self.tmp, "grep.log")
        os.makedirs(fake, exist_ok=True)
        with open(os.path.join(fake, "grep"), "w") as handle:
            handle.write('#!/bin/sh\necho "started $PPID $*" >> "%s"\nexit 1\n' % log)
        os.chmod(os.path.join(fake, "grep"), 0o755)
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        env["PATH"] = fake + os.pathsep + env["PATH"]
        event = {"tool_name": "Bash", "cwd": m, "agent_id": "a1", "tool_input": {"command": "ls && bun add x"}}
        done = subprocess.run([HOOK], input=json.dumps(event), capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 2, done.stderr)  # the project rule still fires: bun add in main
        self.assertFalse(os.path.exists(log), open(log).read() if os.path.exists(log) else '')

    def run_hook(self, m: str, event: dict, project: str = "") -> "subprocess.CompletedProcess[str]":
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        return subprocess.run([HOOK], input=json.dumps(event), capture_output=True, text=True, env=env)

    def test_a_removed_but_registered_worktree_is_not_a_task_worktree(self) -> None:
        # F2: git still lists a worktree whose folder was deleted (prunable); a write there lands in the main checkout.
        m = self.mkrepo("prunable")
        git(m, "worktree", "add", "-q", ".worktree/gone", "-b", "wt/gone")
        shutil.rmtree(os.path.join(m, ".worktree", "gone"))
        event = {"tool_name": "Write", "cwd": m, "agent_id": "a1", "tool_input": {"file_path": m + "/.worktree/gone/x.ex"}}
        self.assertEqual(self.run_hook(m, event).returncode, 2)
        live = dict(event, tool_input={"file_path": m + "/.worktree/any-change/x.ex"})
        self.assertEqual(self.run_hook(m, live).returncode, 0)

    def test_a_locked_removed_worktree_is_not_a_task_worktree(self) -> None:
        # F1: git never marks a locked entry prunable, so a deleted locked worktree must be dropped by its missing folder.
        m = self.mkrepo("lockedgone")
        git(m, "worktree", "add", "-q", ".worktree/b", "-b", "wt/b")
        git(m, "worktree", "lock", ".worktree/b")
        git(m, "worktree", "add", "-q", ".worktree/c", "-b", "wt/c")
        git(m, "worktree", "lock", ".worktree/c")
        shutil.rmtree(os.path.join(m, ".worktree", "b"))
        gone = {"tool_name": "Write", "cwd": m, "agent_id": "a1", "tool_input": {"file_path": m + "/.worktree/b/x.ex"}}
        self.assertEqual(self.run_hook(m, gone).returncode, 2)
        live = dict(gone, tool_input={"file_path": m + "/.worktree/c/x.ex"})
        self.assertEqual(self.run_hook(m, live).returncode, 0)

    def test_the_cd_guard_knows_a_worktree_of_any_folder(self) -> None:
        # F4: the main session's cd into a registered worktree is refused whatever the folder is called.
        m = self.mkrepo("cdguard")
        event = {"tool_name": "Bash", "cwd": m, "tool_input": {"command": "cd %s/.worktree/any-change && ls" % m}}
        done = self.run_hook(m, event)
        self.assertEqual(done.returncode, 2)
        self.assertIn("cd into a worktree", done.stderr)

    def test_kit_folder_is_an_extra_not_a_replacement(self) -> None:
        # F6: kit.toml worktrees = ".worktrees" (as relay setup writes) must not hide the .worktree/ worktree.
        m = self.mkrepo("union")
        os.makedirs(os.path.join(m, ".claude"))
        with open(os.path.join(m, ".claude", "kit.toml"), "w") as handle:
            handle.write('[project]\nworktrees = ".worktrees"\n')
        event = {"tool_name": "Edit", "cwd": m, "agent_id": "a1", "tool_input": {"file_path": m + "/.worktree/any-change/x.ex"}}
        self.assertEqual(self.run_hook(m, event).returncode, 0)

    def test_an_absolute_worktrees_folder_is_the_extra_folder(self) -> None:
        # worktrees = "<main>/wts" (absolute): a write under it is inside a task worktree although git lists none;
        # joined onto main it would read "<main>//<main>/wts" and the write would be refused as a write to main.
        m = self.mkrepo("absextra")
        os.makedirs(os.path.join(m, ".claude"))
        with open(os.path.join(m, ".claude", "kit.toml"), "w") as handle:
            handle.write('[project]\nworktrees = "%s/wts"\n' % m)
        event = {"tool_name": "Edit", "cwd": m, "agent_id": "a1", "tool_input": {"file_path": m + "/wts/a/f.py"}}
        self.assertEqual(self.run_hook(m, event).returncode, 0)

    def test_the_advice_names_the_projects_own_worktree_tool(self) -> None:
        # F5: a project with bin/wt is told to use it, not `git worktree add .worktrees/<name>`.
        m = self.mkrepo("advice")
        os.makedirs(os.path.join(m, "bin"))
        with open(os.path.join(m, "bin", "wt"), "w") as handle:
            handle.write("#!/bin/sh\n")
        os.chmod(os.path.join(m, "bin", "wt"), 0o755)
        event = {"tool_name": "Edit", "cwd": m, "agent_id": "a1", "tool_input": {"file_path": m + "/README.md"}}
        done = self.run_hook(m, event)
        self.assertEqual(done.returncode, 2)
        self.assertIn("bin/wt new", done.stderr)
        self.assertNotIn("git worktree add", done.stderr)

    def hook_with_rule(self, name: str, pattern: str, command: str, unless: str = "") -> "subprocess.CompletedProcess[str]":
        """Bash `command` in a main checkout whose kit.toml has one [[guard.block]] rule (TOML literal strings)."""
        m = self.mkrepo(name)
        os.makedirs(os.path.join(m, ".claude"))
        with open(os.path.join(m, ".claude", "kit.toml"), "w") as handle:
            handle.write("[[guard.block]]\npattern = '%s'\nreason = \"rule fired\"\n" % pattern)
            if unless:
                handle.write("unless = '%s'\n" % unless)
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        event = {"tool_name": "Bash", "cwd": m, "agent_id": "a1", "tool_input": {"command": command}}
        return subprocess.run([HOOK, ], input=json.dumps(event), capture_output=True, text=True, env=env)

    def test_ere_word_edge_in_a_project_rule_fires(self) -> None:
        # grep -E reads \< as a word start; so `npm install x` matches and the rule blocks (not a silent no-op).
        done = self.hook_with_rule("wordedge", r"\<npm[[:space:]]+install", "npm install x")
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("rule fired", done.stderr)

    def test_ere_class_graph_in_a_project_rule_fires(self) -> None:
        # [[:graph:]] matches "a", so "ax" matches; Python must not warn about a nested set.
        done = self.hook_with_rule("graphclass", "[[:graph:]]x", "ax")
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("rule fired", done.stderr)
        self.assertNotIn("FutureWarning", done.stderr)

    def test_ere_backslash_in_brackets_is_literal(self) -> None:
        # In ERE [\.] is a backslash or a dot: it matches the backslash in "a\b".
        done = self.hook_with_rule("bsbracket", r"a[\.]b", "echo a\\b")
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("rule fired", done.stderr)

    def test_a_pattern_the_guard_cannot_read_blocks_naming_it(self) -> None:
        for name, pattern in (("badclass", "[[:nosuch:]]x"), ("badre", "a(b")):
            done = self.hook_with_rule(name, pattern, "ls")
            self.assertEqual(done.returncode, 2, done.stderr)
            self.assertIn(pattern, done.stderr)

    def test_alternation_is_leftmost_first_as_the_readme_says(self) -> None:
        # Python takes "cargo" (first branch), so unless 'fmt' does not match it and the rule blocks; the longer branch
        # written first gives "cargo fmt", which unless lets through.
        short = self.hook_with_rule("altshort", "{start}(cargo|cargo[[:space:]]+fmt)", "cargo fmt --check", "fmt")
        self.assertEqual(short.returncode, 2, short.stderr)
        longer = self.hook_with_rule("altlong", "{start}(cargo[[:space:]]+fmt|cargo)", "cargo fmt --check", "fmt")
        self.assertEqual(longer.returncode, 0, longer.stderr)

    def test_an_unreadable_kit_toml_never_silently_drops_the_rules(self) -> None:
        m = self.mkrepo("broken")
        os.makedirs(os.path.join(m, ".claude"))
        with open(os.path.join(m, ".claude", "kit.toml"), "w") as handle:
            handle.write("[gate\n")
        w = os.path.join(m, ".worktrees", "any-change")
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        for tool, cwd, key, val in (("Bash", w, "command", "ls"), ("Edit", m, "file_path", w + "/a.txt")):
            event = {"tool_name": tool, "cwd": cwd, "tool_input": {key: val}}
            done = subprocess.run([HOOK], input=json.dumps(event), capture_output=True, text=True, env=env)
            self.assertEqual(done.returncode, 2, tool)
            self.assertIn("kit.toml is unreadable", done.stderr)
        os.remove(os.path.join(m, ".claude", "kit.toml"))
        # outside any repository nothing is guarded
        self.assertEqual(self.verdicts(m, ".worktrees", BROKEN), [c[0] for c in BROKEN])


if __name__ == "__main__":
    unittest.main()
