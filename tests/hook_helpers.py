"""Shared helper of the hook test suites ported from plugins/*/tests/*.test.sh: run a hook script on a JSON event."""
import os
import subprocess
import sys
from typing import Mapping, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_hook(script: str, stdin: str, env: Optional[Mapping[str, str]] = None, cwd: Optional[str] = None) -> str:
    """Stdout of `python3 script` fed `stdin`; the hook's own failure is not an error here (fail-open hooks print nothing)."""
    full = dict(os.environ)
    full.update(env or {})
    done = subprocess.run([sys.executable, script], input=stdin, capture_output=True, text=True, env=full, cwd=cwd)
    return done.stdout
