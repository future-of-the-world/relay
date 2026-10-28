"""One list of relay's command names for the tests: the module walk of lib/relay_cmd plus bin/relay's COMMANDS table.

`names()` is the commands, `queue_words()` the words of `relay queue`; both read the walk and the table, so a command
moved out of bin/relay stays in the list and a new command module needs no test edit. bin/relay is loaded as a module
(never searched as text), so the table can live there or move.
"""
import importlib.machinery
import importlib.util
import os
import re
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NAME = re.compile(r"[a-z][a-z0-9_]*")

# Today's 21 commands, written out: one that drops out of both the walk and the table fails the tests that use this.
FLOOR = frozenset("status report calibrate improve bench candidate profile sync setup install migrate doctor flows rules "
                  "changed gate land precheck check queue license".split())


def load_relay(root: str = ROOT) -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader("relay_cli_under_test", os.path.join(root, "bin", "relay"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def walk(root: str = ROOT) -> list[tuple[str, str]]:
    """(command, action) for each module under lib/relay_cmd: action is "" for a file or a package's own use, else the action module."""
    top = os.path.join(root, "lib", "relay_cmd")
    found: list[tuple[str, str]] = []
    if not os.path.isdir(top):
        return found
    for entry in sorted(os.listdir(top)):
        path = os.path.join(top, entry)
        if os.path.isfile(path) and entry.endswith(".py") and entry != "__init__.py" and NAME.fullmatch(entry[:-3]):
            found.append((entry[:-3], ""))
        elif os.path.isdir(path) and NAME.fullmatch(entry) and os.path.isfile(os.path.join(path, "__init__.py")):
            found.append((entry, ""))
            for sub in sorted(os.listdir(path)):
                if sub.endswith(".py") and sub != "__init__.py" and NAME.fullmatch(sub[:-3]):
                    found.append((entry, sub[:-3]))
    return found


def names(root: str = ROOT) -> list[str]:
    table = getattr(load_relay(root), "COMMANDS", {}) if os.path.isfile(os.path.join(root, "bin", "relay")) else {}
    return sorted({cmd for cmd, _ in walk(root)} | set(table))


def queue_words(root: str = ROOT) -> set[str]:
    """Action modules of lib/relay_cmd/queue/, QUEUE_WRITES and the words of the `relay queue [a|b|...]` usage line."""
    module = load_relay(root)
    words = {action for cmd, action in walk(root) if cmd == "queue" and action}
    words |= set(getattr(module, "QUEUE_WRITES", ()))
    usage = (getattr(module, "__doc__", "") or "") + "\n" + str(getattr(module, "QUEUE_USAGE", ""))
    for found in re.findall(r"relay queue \[([a-z|]+)\]", usage):
        words |= set(found.split("|"))
    return words


def missing_test_files(root: str = ROOT, tests: str = HERE) -> list[str]:
    """Test files the walk requires and tests/ lacks: test_cmd_<name>.py, or test_cmd_<cmd>_<action>.py for a package action."""
    walked = walk(root)
    packages_with_actions = {cmd for cmd, action in walked if action}
    need = sorted({f"test_cmd_{cmd}_{action}.py" if action else f"test_cmd_{cmd}.py"
                   for cmd, action in walked if action or cmd not in packages_with_actions})
    return [name for name in need if not os.path.isfile(os.path.join(tests, name))]
