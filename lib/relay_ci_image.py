"""The clean-image quick gate (container/Containerfile's recipe, podman only): build the image, clone the head with no
hardlinks into a temporary folder, run `bin/ci --quick` in a fresh clone inside the image (split from relay_ci)."""
from __future__ import annotations

import os
import tempfile
from typing import Any, TextIO

CLEAN_IMAGE = "relay-clean-gate"   # the podman image tag of container/Containerfile


def clean_image(ci: Any, log: TextIO) -> int:
    """Red (non-zero) when the image's quick gate is, or podman is missing."""
    if ci.which("podman") is None:
        log.write("podman is not on PATH: the clean-image gate cannot run (install podman)\n")
        return 127
    head = ci.run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="relay-clean-gate-") as tmp:
        src = os.path.join(tmp, "src")
        # a worktree's .git file points outside the mount, so the image gets a plain clone of the head
        for argv in (["podman", "build", "-q", "-f", "container/Containerfile", "-t", CLEAN_IMAGE, "."],
                     ["git", "clone", "-q", "--no-hardlinks", ci.root, src],
                     ["git", "-C", src, "checkout", "-q", "-B", "master", head],   # the image's clone then has a default branch, as relay's tests need
                     ["podman", "run", "--rm", "-v", "%s:/src:ro" % src, CLEAN_IMAGE, "sh", "-c",
                      "git clone -q /src /work/relay && cd /work/relay && bin/ci --quick"]):
            rc = ci.run(argv, log).returncode
            if rc != 0:
                log.write("clean image gate: `%s` exited %d\n" % (" ".join(argv[:3]), rc))
                return rc
    return 0
