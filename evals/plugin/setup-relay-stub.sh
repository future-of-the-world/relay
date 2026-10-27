#!/usr/bin/env bash
# For a case whose session runs `relay queue show|note`: puts relay-stub.py where the `relay` wrapper
# (plugins/front/bin/relay) looks last, $HOME/relay/bin/relay (the run's own $HOME). Why a stub: relay-stub.py.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
mkdir -p "$HOME/relay/bin"
cp "$here/relay-stub.py" "$HOME/relay/bin/relay"
chmod +x "$HOME/relay/bin/relay"
