"""Fake tool scripts shared between tests.

macOS scans a newly written executable on its first run (about 0.75 s); a hardlink or symlink to a file that
already ran costs about 4 ms. So a fake tool's text is written once per test run into a cache folder in the
run's temporary area (never HOME, ~/.relay or the repo), and each test gets a hardlink to it (a symlink if a
hardlink cannot be made). The cache key is the text, so a tool that differs by text is a different file.
"""
import atexit
import hashlib
import os
import shutil
import tempfile
from typing import Optional

import tmp_default

_cache: Optional[str] = None


def _cache_dir() -> str:
    global _cache
    if _cache is None:
        _cache = tempfile.mkdtemp(prefix="relay-fake-tools-", dir=tmp_default.run_temp())
        atexit.register(shutil.rmtree, _cache, True)
    return _cache


def install_fake(path: str, text: str) -> None:
    """Make `path` an executable with `text`, replacing what is there; the same text shares one cached file."""
    cached = os.path.join(_cache_dir(), hashlib.sha256(text.encode()).hexdigest())
    if not os.path.exists(cached):
        partial = cached + f".{os.getpid()}"
        with open(partial, "w") as handle:
            handle.write(text)
        os.chmod(partial, 0o555)    # read-only: an in-place write through one link would change every test's tool
        os.replace(partial, cached)
    if os.path.lexists(path):
        os.remove(path)
    try:
        os.link(cached, path)
    except OSError:
        os.symlink(cached, path)
