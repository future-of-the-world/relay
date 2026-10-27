"""The one way a test reads a pid file that a shell writes (`echo $$ > file`): the file exists a moment before the number is in it,
so a reader that stops at "exists" can see ''. wait_pid waits for a whole line instead."""
import os
import re
import time
from typing import Callable, Optional, Union

POLL = 0.05             # seconds between two reads
MIN_TIMEOUT = 1.0       # seconds; a shorter wait fails on a slow machine for no reason
MAX_TIMEOUT = 900.0     # seconds; the gate tests' own limit (test_gate.GATE_TIMEOUT)
WHOLE_LINE = re.compile(r"\d+\n")


def wait_pid(path: Union[str, "os.PathLike[str]"], timeout: float = 60.0,
             writer_alive: Optional[Callable[[], bool]] = None) -> int:
    """The pid in `path`, once the file holds digits and a newline (the newline is written after the digits, so the write is
    done). When `writer_alive` is given and returns False, the file is read one last time and, if still not whole, the test fails
    at once saying the writer never wrote its pid. Fails the test with AssertionError, naming what the file held, when that does not happen within `timeout` seconds."""
    if not MIN_TIMEOUT <= timeout <= MAX_TIMEOUT:
        raise ValueError("timeout %s is outside %s..%s seconds" % (timeout, MIN_TIMEOUT, MAX_TIMEOUT))
    deadline = time.monotonic() + timeout
    text = "missing"
    while True:
        gone = writer_alive is not None and not writer_alive()   # asked before the read: a write just before death is seen
        try:
            with open(path) as handle:
                raw = handle.read()
        except FileNotFoundError:
            text = "missing"
        else:
            text = repr(raw)
            if WHOLE_LINE.fullmatch(raw):
                return int(raw)
        if gone:
            raise AssertionError("the writer of pid file %s ended and never wrote its pid: %s" % (os.fspath(path), text))
        if time.monotonic() >= deadline:
            raise AssertionError("pid file %s held no whole number within %s s: %s" % (os.fspath(path), timeout, text))
        time.sleep(POLL)
