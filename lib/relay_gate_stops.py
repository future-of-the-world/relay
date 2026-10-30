"""The gate's stop signals: the log line for a command ended by a signal, and the hold of stops while a command starts.
Split out of relay_gate.py (module size limit); relay_gate re-exports both names."""

from __future__ import annotations

import signal
from typing import Any, Callable

import relay_procs


def signal_line(number: int, command_pid: int = 0, since: float = 0.0) -> str:
    """The gate log's line for a command ended by a signal: relay's record of the stop (to its pid or group, from `since`), else that no relay sender that logs its signals sent it (never "not sent by relay": some senders do not log)."""
    name = {int(s): s.name for s in signal.Signals}.get(number, "signal %d" % number)
    try: record = relay_procs.sent_by_relay(command_pid, since) if command_pid else None
    except OSError as exc: return "gate command ended by %s, cannot tell whether relay sent it (the signal log %s could not be read: %s)" % (name, relay_procs.signal_log(), exc)
    return "gate command ended by %s, sent by relay: %s" % (name, record) if record else "gate command ended by %s, no relay sender that logs its signals sent it (those are the gate, its reclaim and leftover sweep, and bin/ci; other senders of relay do not log yet; no record of it in %s)" % (name, relay_procs.signal_log())


def hold_stops() -> tuple[list[int], Callable[[], None]]:
    """Hold SIGINT, SIGTERM and SIGHUP: arrivals are appended to the returned list instead of acting. The function returned
    puts the earlier handlers back. Not the main thread: nothing is held (the caller owns its signals)."""
    held: list[int] = []
    saved: dict[int, Any] = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            if signal.getsignal(sig) == signal.SIG_IGN:      # an ignored stop needs no hold, and the command must inherit the ignore
                continue
            saved[sig] = signal.signal(sig, lambda signum, frame: held.append(signum))
    except ValueError:
        pass

    def release() -> None:
        for sig, old in saved.items():
            signal.signal(sig, old)
    return held, release
