#!/usr/bin/env bash
# For a case whose session runs `relay queue show|note`: puts relay-stub.py where the `relay` wrapper
# (plugins/front/bin/relay) looks last, $HOME/relay/bin/relay (the run's own $HOME). Why a stub: relay-stub.py.
# Refuses unless HOME is a run's own throwaway home, exactly what the eval tool lays out: HOME under TMPDIR, or
# HOME == dirname(TMPDIR)/home (a run is <root>/home beside <root>/tmp). Not any folder under TMPDIR's parent: with
# TMPDIR=$HOME/tmp that would let the owner's real HOME pass. And never writes into a git checkout: with the owner's real HOME it would replace the live bin/relay.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
home="$(cd "$HOME" && pwd -P)"
tmp="$(cd "${TMPDIR:-/tmp}" && pwd -P)"
parent="$(dirname "$tmp")"
ok=0
case "$home/" in "$tmp"/*) ok=1 ;; esac
if [ "$parent" != / ] && [ "$home" = "$parent/home" ]; then ok=1; fi
if [ "$ok" != 1 ]; then
  echo "setup-relay-stub.sh: refusing, HOME=$HOME is not a throwaway home. Run the scaffold with HOME set to a temporary folder." >&2
  exit 1
fi
# The eval tool gives the run's home its own .git: a checkout whose top is $home itself is fine; any other
# checkout (one at $home/relay, or one a symlink leads to) is refused.
refuse_checkout() { # dir
  top="$(git -C "$1" rev-parse --show-toplevel 2>/dev/null || true)"
  if [ -n "$top" ]; then top="$(cd "$top" && pwd -P)"; fi
  if [ -n "$top" ] && [ "$top" != "$home" ]; then
    echo "setup-relay-stub.sh: refusing, $1 is inside the git checkout $top; the stub would replace its bin/relay." >&2
    exit 1
  fi
}
if [ -e "$home/relay" ]; then refuse_checkout "$home/relay"; fi
mkdir -p "$home/relay/bin"
bin="$(cd "$home/relay/bin" && pwd -P)"
refuse_checkout "$bin"
rm -f "$home/relay/bin/relay"  # a symlink is replaced, never written through
cp "$here/relay-stub.py" "$home/relay/bin/relay"
chmod +x "$home/relay/bin/relay"
