"""What `relay doctor` says about leftovers of finished work (design docs/plans/review-gate.md, 11.3).

Read-only: it lists, it never removes. One line per finding, as a (fix, text) pair: `fix` is true
where someone has something to do, false where the line is information.
"""

import os
import re

import relay_config
import relay_git

QUEUE_DIR = ".relay/queue"


def _item_fields(text):
    """The `key: value` lines of an item file's front matter (the block between the first two `---` lines)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        fields[key.strip()] = value.split("#", 1)[0].strip()
    return fields


def _taken_items(main, default):
    """(slug, taken-by) of every committed queue item on the default branch whose state is `taken`."""
    rc, names = relay_git.git(main, "ls-tree", "--name-only", "refs/heads/" + default, QUEUE_DIR + "/")
    if rc != 0:
        return []
    taken = []
    for name in sorted(names.splitlines()):
        if not name.endswith(".md"):
            continue
        rc, text = relay_git.git(main, "show", "refs/heads/%s:%s" % (default, name), raw=True)
        fields = _item_fields(text) if rc == 0 else {}
        if fields.get("state") == "taken" and fields.get("taken-by"):
            taken.append((os.path.basename(name)[:-3], fields["taken-by"]))
    return taken


def _merged(main, default, branch):
    heads = ["refs/heads/" + default, "refs/remotes/origin/" + default]
    return any(relay_git.git(main, "show-ref", "--verify", "--quiet", h)[0] == 0
               and relay_git.git(main, "merge-base", "--is-ancestor", "refs/heads/" + branch, h)[0] == 0 for h in heads)


def lines(repo):
    """[(fix, text)] for the repository holding `repo`; empty where the default branch cannot be told."""
    main = relay_git.main_checkout(repo)
    default = relay_git.default_branch(main) if main else None
    if default is None:
        return []
    found = []
    for tree in relay_git.worktrees(main):
        branch = tree["branch"]
        if tree["path"] == main or not branch or not branch.startswith("wt/") or branch.startswith("wt/queue-"):
            continue
        if not _merged(main, default, branch) or not relay_git.has_own_commits(main, branch):
            continue
        name = os.path.relpath(tree["path"], main)
        session = re.match(r"session (\S+)$", tree["locked"] or "")
        if session:
            found.append((True, "merged worktree %s (%s) is locked by session %s; remove it once that session is closed" % (name, branch, session.group(1))))
        else:
            found.append((True, "merged worktree still present: %s (%s)" % (name, branch)))
    rc, refs = relay_git.git(main, "for-each-ref", "--format=%(refname:short) %(upstream:track)", "refs/heads/wt/")
    for ref in sorted(refs.splitlines()) if rc == 0 else []:
        branch, _, track = ref.partition(" ")
        if track == "[gone]":
            found.append((False, "%s: its upstream is gone (probably merged on the server, a squash); not removed" % branch))
        if branch.startswith("wt/queue-"):
            found.append((True, "leftover queue branch: %s" % branch))
    cache = os.path.join(relay_config.claude_dir(), "plugins", "cache", "relay")
    if os.path.isdir(cache):
        home = os.path.expanduser("~")
        shown = "~" + cache[len(home):] if cache.startswith(home + os.sep) else cache
        found.append((False, "unused plugin copy: %s/ (informational)" % shown))
    for slug, branch in _taken_items(main, default):
        if relay_git.git(main, "show-ref", "--verify", "--quiet", "refs/heads/" + branch)[0] != 0:
            found.append((True, "queue item %s is taken by %s, which no longer exists" % (slug, branch)))
    return found
