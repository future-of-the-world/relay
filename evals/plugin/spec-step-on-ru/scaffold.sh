#!/usr/bin/env bash
# The fixture with spec steps turned on, as `relay setup --specs openspec` leaves a project: [specs] method in
# .claude/kit.toml, and the project's rules (the OpenSpec rule and its steps table) rendered by relay's own code
# into CLAUDE.local.md. No relay sync is run; the renderer is called on this scratch copy only.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
"$here/../setup-fixture.sh"
printf '\n[specs]\nmethod = "openspec"\n' >> .claude/kit.toml
python3 -I - "$here/../../.." "$PWD" <<'PY'
import os, sys
root, work = sys.argv[1:3]
sys.path.insert(0, os.path.join(root, "lib"))
import relay_rules
text = relay_rules.render_target("project", {"file": os.path.join(work, "CLAUDE.local.md"), "load": []}, relay_rules.rules(), {})
open(os.path.join(work, "CLAUDE.local.md"), "w", encoding="utf-8").write(text)
PY
git add -A
git -c user.name=fixture -c user.email=fixture@example.invalid commit -qm "Spec steps on"
bin/wt new sort-by-name master >/dev/null
