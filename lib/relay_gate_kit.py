"""The settings schema `relay gate` checks a branch's .claude/kit.toml with: the branch's own lib/relay_kit.py."""
from __future__ import annotations

import importlib.util
import os
import sys
from types import ModuleType


def branch_kit(worktree: str, installed: ModuleType) -> ModuleType:
    """The branch's own lib/relay_kit.py (the code under test, so a branch that renames or adds a key passes), the installed
    module only when the branch has none. A module that does not load raises RuntimeError: the caller refuses the gate."""
    path = os.path.join(worktree, "lib", "relay_kit.py")
    if not os.path.isfile(path):
        return installed
    spec = importlib.util.spec_from_file_location("relay_kit_of_branch", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load %s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module      # the module's dataclasses look their module up by name while the class bodies run
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(spec.name, None)
        raise RuntimeError("the branch's lib/relay_kit.py cannot be loaded: %s" % exc)
    return module
