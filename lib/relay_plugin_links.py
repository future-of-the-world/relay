"""Plugin lib files are links to the one source in lib/ (one copy of each module in git). The eval tool's OS sandbox
reads a plugin folder but not a link's target outside it, so `import relay_toml` in a plugin's bin failed there
(paid run 30 Oct, master 9aa7248a, plan-one-line). `real_files` makes the links real files for the length of a run."""
import contextlib
import os
import shutil
from collections.abc import Iterator


def plugin_links(root: str) -> list[tuple[str, str]]:
    """(path, link text) of every symlink to a file under <root>/plugins that points outside its own plugin folder."""
    found: list[tuple[str, str]] = []
    plugins = os.path.join(root, "plugins")
    if not os.path.isdir(plugins):
        return found
    for plugin in sorted(os.listdir(plugins)):
        folder = os.path.realpath(os.path.join(plugins, plugin))
        for here, _dirs, files in os.walk(os.path.join(plugins, plugin)):
            for name in sorted(files):
                path = os.path.join(here, name)
                if not os.path.islink(path):
                    continue
                target = os.path.realpath(path)
                if os.path.isfile(target) and os.path.commonpath([folder, target]) != folder:
                    found.append((path, os.readlink(path)))
    return found


@contextlib.contextmanager
def real_files(root: str) -> Iterator[list[str]]:
    """Inside the block every plugin link that leaves its folder is a real copy of its target; on exit the links are back."""
    links = plugin_links(root)
    done: list[tuple[str, str]] = []
    try:
        for path, text in links:
            source = os.path.realpath(path)
            os.remove(path)
            shutil.copyfile(source, path)
            done.append((path, text))
        yield [path for path, _ in links]
    finally:
        for path, text in done:
            if os.path.lexists(path):
                os.remove(path)
            os.symlink(text, path)
