#!/usr/bin/env bash
# The fixture, plus the queue items in ./queue committed on master (.relay/queue/).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
"$here/../setup-fixture.sh"
"$here/../setup-relay-stub.sh"
mkdir -p .relay/queue
cp "$here"/queue/*.json .relay/queue/
git add -A
git -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "queue items"
