"""The record of gate hosts, `$RELAY_HOME/gate-hosts.json`, and `relay hosts add|set|remove|status` (plan gates-on-the-vps-hosts-transport-watch-bring-up 5.7, 5.9).

This is the only module that names the record: one record per host, schema-checked on every read, written only here. No record means no
remote gate. relay's code never runs a root command and never logs in to a host as root: when the key does not open the account, `add`
prints the three root commands for the owner to see and stops."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, replace
from typing import Any, Optional, Sequence

import relay_config

RECORD = "gate-hosts.json"
KEY = os.path.join("keys", "gate-host")
# name: (default, lowest, highest) -- plan 5.7; watch_default is on or off
SETTINGS: dict[str, tuple[int, int, int]] = {
    "slots": (2, 1, 3), "cpus": (4, 2, 8), "memory_gib": (4, 2, 12), "cpu_shares": (256, 2, 1024), "connect_timeout_s": (3, 1, 15),
    "keepalive_s": (10, 5, 20), "keepalive_count": (3, 2, 6), "remote_wait_s": (900, 0, 3600), "images_kept": (3, 1, 10),
    "build_limit_s": (900, 300, 3600), "stop_after": (3, 1, 10), "rerun_disagreement": (1, 0, 3),
}
ON_OFF = ("watch_default", "twin_red_landings")      # the two settings that are on or off
DEFAULT_USER = "relay-gate"


@dataclass(frozen=True)
class Host:
    name: str
    user: str
    values: dict[str, int]
    watch_default: bool = True
    twin_red_landings: bool = True

    def get(self, setting: str) -> int:
        return self.values.get(setting, SETTINGS[setting][0])


def record_path(home: Optional[str] = None) -> str:
    return os.path.join(home or relay_config.home_dir(), RECORD)


def key_path(home: Optional[str] = None) -> str:
    return os.path.join(home or relay_config.home_dir(), KEY)


def _host(name: str, raw: Any) -> Host:
    if not isinstance(raw, dict) or not isinstance(raw.get("user"), str) or not raw["user"] or raw["user"] == "root":
        raise ValueError("%s: the host %s needs a `user` that is not root" % (RECORD, name))
    values: dict[str, int] = {}
    for key, value in (raw.get("settings") or {}).items():
        if key in ON_OFF:
            continue
        if key not in SETTINGS or isinstance(value, bool) or not isinstance(value, int) or not SETTINGS[key][1] <= value <= SETTINGS[key][2]:
            raise ValueError("%s: the setting %s of %s is not understood or is outside its bound" % (RECORD, key, name))
        values[key] = value
    watch = (raw.get("settings") or {}).get("watch_default", True)
    if not isinstance(watch, bool):
        raise ValueError("%s: watch_default of %s is on or off" % (RECORD, name))
    twin = (raw.get("settings") or {}).get("twin_red_landings", True)
    if not isinstance(twin, bool):
        raise ValueError("%s: twin_red_landings of %s is on or off" % (RECORD, name))
    return Host(name, raw["user"], values, watch, twin)


def load(home: Optional[str] = None) -> dict[str, Host]:
    """The hosts of the record; {} when there is no record; ValueError (naming the file) when it is not valid."""
    try:
        with open(record_path(home), encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise ValueError("%s cannot be read: %s" % (record_path(home), exc))
    hosts = data.get("hosts") if isinstance(data, dict) else None
    if not isinstance(hosts, dict):
        raise ValueError("%s has no `hosts` table" % record_path(home))
    return {name: _host(name, raw) for name, raw in sorted(hosts.items())}


def save(hosts: dict[str, Host], home: Optional[str] = None) -> None:
    path = record_path(home)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"hosts": {h.name: {"user": h.user, "settings": {**h.values, "watch_default": h.watch_default, "twin_red_landings": h.twin_red_landings}} for h in hosts.values()}}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def first(home: Optional[str] = None) -> Optional[Host]:
    """The host gates go to: the first by name (there is one VPS), None when there is no record."""
    hosts = load(home)
    return hosts[sorted(hosts)[0]] if hosts else None


def set_value(name: str, setting: str, value: str, home: Optional[str] = None) -> Host:
    hosts = load(home)
    if name not in hosts:
        raise ValueError("there is no host %s in the record; add it first: relay hosts add %s" % (name, name))
    host = hosts[name]
    if setting in ON_OFF:
        if value not in ("on", "off"):
            raise ValueError("%s is on or off" % setting)
        host = replace(host, watch_default=value == "on") if setting == "watch_default" else replace(host, twin_red_landings=value == "on")
    elif setting in SETTINGS:
        low, high = SETTINGS[setting][1:]
        if not value.isdigit() or not low <= int(value) <= high:
            raise ValueError("%s is a whole number from %d to %d" % (setting, low, high))
        host = replace(host, values={**host.values, setting: int(value)})
    else:
        raise ValueError("unknown setting %s; the settings are %s, %s" % (setting, ", ".join(SETTINGS), ", ".join(ON_OFF)))
    save({**hosts, name: host}, home)
    return host


def root_commands(user: str, public_key: str) -> list[str]:
    """The three commands the owner sees and the front runs as root on the server (plan 5.9 steps 2-3); relay's code never runs them."""
    return [
        "useradd --create-home --shell /bin/bash %s" % user,
        "install -d -m 700 -o %s -g %s ~%s/.ssh" % (user, user, user),
        "printf 'restrict %%s\\n' '%s' > ~%s/.ssh/authorized_keys && chown %s: ~%s/.ssh/authorized_keys && chmod 600 ~%s/.ssh/authorized_keys"
        % (public_key, user, user, user, user),
    ]


def ensure_key(home: Optional[str] = None) -> str:
    """The public key line of relay's key for gate hosts; the key (ed25519, no passphrase) is made when missing."""
    path = key_path(home)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        done = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "relay-gate", "-f", path], capture_output=True, text=True, timeout=60)
        if done.returncode != 0:
            raise ValueError("ssh-keygen could not make the key: %s" % done.stderr.strip())
    with open(path + ".pub", encoding="utf-8") as handle:
        return handle.read().strip()


def add(name: str, user: str, repo: str, home: Optional[str] = None) -> list[str]:
    """Prove the host and record it: log in as `user`, install the gate program, read podman's limits and the subuid range. Builds and
    gates nothing (the first Linux watch does). Returns the lines to print; ValueError when it cannot (with the root commands when the key is refused)."""
    import relay_gate_ssh      # not at the top: relay_gate_ssh reads this module's Host
    if user == "root":
        raise ValueError("relay does not log in as root: use the gate account (%s)" % DEFAULT_USER)
    public = ensure_key(home)
    try:
        lines = relay_gate_ssh.prove(Host(name, user, {}), repo, home)
    except relay_gate_ssh.LoginRefused:
        raise ValueError(refused_text(name, user, public))
    hosts = load(home)
    old = hosts.get(name)
    save({**hosts, name: replace(old, user=user) if old else Host(name, user, {})}, home)
    return lines + ["recorded %s as %s" % (name, user)]


def refused_text(name: str, user: str, public_key: str) -> str:
    cmds = root_commands(user, public_key)
    return ("relay's key does not open %s@%s. The owner sees these 3 commands, then they are run as root on %s (relay never runs them):\n  %s\n"
            "then run: relay hosts add %s --user %s" % (user, name, name, "\n  ".join(cmds), name, user))


def remove(name: str, home: Optional[str] = None) -> list[str]:
    """Delete the record of the host and relay's key; print the one root command that removes the account (relay never runs it)."""
    hosts = load(home)
    if name not in hosts:
        raise ValueError("there is no host %s in the record" % name)
    user = hosts[name].user
    del hosts[name]
    save(hosts, home)
    for path in ((key_path(home), key_path(home) + ".pub") if not hosts else ()):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    return ["removed %s from the record%s" % (name, "" if hosts else " and relay's key"),
            "the account stays on the server; to remove it, run as root on %s: userdel -r %s" % (name, user)]


def main(args: Sequence[str]) -> list[str]:
    usage = "relay hosts add <host> [--user <account>] [-C <repo>] | set <host> <setting> <value> | remove <host> | status | compare [--waves <1-20>] [-C <repo>]"
    args = list(args)
    repo, user = ".", DEFAULT_USER
    for flag in ("-C", "--user"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                raise ValueError(usage)
            value = args[i + 1]
            del args[i:i + 2]
            repo, user = (value, user) if flag == "-C" else (repo, value)
    if args[:1] == ["add"] and len(args) == 2:
        return add(args[1], user, repo)
    if args[:1] == ["set"] and len(args) == 4:
        host = set_value(args[1], args[2], args[3])
        return ["%s: %s" % (host.name, settings_text(host))]
    if args[:1] == ["remove"] and len(args) == 2:
        return remove(args[1])
    if args[:1] == ["status"] and len(args) == 1:
        import relay_gate_watch
        return relay_gate_watch.status_lines(repo)
    if args[:1] == ["compare"]:
        import relay_gate_compare
        waves = relay_gate_compare.DEFAULT_WAVES
        rest = args[1:]
        if rest[:1] == ["--waves"] and len(rest) == 2:
            low, high = relay_gate_compare.WAVES_BOUNDS
            if not rest[1].isdigit() or not low <= int(rest[1]) <= high:
                raise ValueError("--waves is a whole number from %d to %d" % (low, high))
            waves, rest = int(rest[1]), []
        if rest:
            raise ValueError(usage)
        return relay_gate_compare.compare_lines(repo, waves)
    raise ValueError(usage)


def settings_text(host: Host) -> str:
    return " ".join("%s=%d" % (key, host.get(key)) for key in SETTINGS) + " watch_default=%s twin_red_landings=%s" % ("on" if host.watch_default else "off", "on" if host.twin_red_landings else "off")
