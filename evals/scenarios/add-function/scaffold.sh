#!/usr/bin/env bash
set -euo pipefail
git init -q -b master . && git add -A && git -c user.name=f -c user.email=f@x commit -qm fixture
