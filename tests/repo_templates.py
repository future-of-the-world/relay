"""The run's folder for template repositories: built once per run, copied for every case, removed when the process exits."""
import atexit
import os
import shutil
import tempfile
from typing import Dict, List

import tmp_default

_ROOTS: Dict[str, str] = {}


def template_root(kind: str) -> str:
    """The folder holding the `kind` templates ("queue", "gate"): inside the run's own temporary folder (not the running test's,
    which is removed after the test), made at the first call."""
    if kind not in _ROOTS:
        root = os.path.realpath(tempfile.mkdtemp(prefix="relay-%s-template-" % kind, dir=tmp_default.run_temp()))
        atexit.register(shutil.rmtree, root, ignore_errors=True)
        _ROOTS[kind] = root
    return _ROOTS[kind]


def roots() -> List[str]:
    return sorted(_ROOTS.values())
