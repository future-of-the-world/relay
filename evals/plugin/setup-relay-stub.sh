#!/usr/bin/env bash
# For a case whose session runs `relay queue show|note`: puts relay-stub.py where the `relay` wrapper
# (plugins/front/bin/relay) looks last, $HOME/relay/bin/relay (the run's own $HOME). Why a stub: relay-stub.py.
# Refuses unless HOME is a run's own throwaway home: under TMPDIR, or under TMPDIR's parent (the eval tool lays a run
# out as <root>/home beside <root>/tmp); and never writes into a git checkout: with the owner's real HOME it would replace the live bin/relay.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
home="$(cd "$HOME" && pwd -P)"
tmp="$(cd "${TMPDIR:-/tmp}" && pwd -P)"
parent="$(dirname "$tmp")"
ok=0
case "$home/" in "$tmp"/*) ok=1 ;; esac
if [ "$parent" != / ]; then case "$home/" in "$parent"/*) ok=1 ;; esac; fi
if [ "$ok" != 1 ]; then
  echo "setup-relay-stub.sh: refusing, HOME=$HOME is not a throwaway home. Run the scaffold with HOME set to a temporary folder." >&2
  exit 1
fi
if git -C "$home/relay" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "setup-relay-stub.sh: refusing, $home/relay is a git checkout; the stub would replace its bin/relay." >&2
  exit 1
fi
mkdir -p "$home/relay/bin"
bin="$(cd "$home/relay/bin" && pwd -P)"
if git -C "$bin" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "setup-relay-stub.sh: refusing, $bin is inside a git checkout." >&2
  exit 1
fi
rm -f "$home/relay/bin/relay"  # a symlink is replaced, never written through
cp "$here/relay-stub.py" "$home/relay/bin/relay"
chmod +x "$home/relay/bin/relay"
