"""`relay queue migrate`: rewrite the item files of the shape with `state` to the shape with dated events.

The dates come from the git history of each item (the commit time, in UTC, of the commit that added the item, took it,
closed it, dropped it). The command works on the files of one checkout, changes only item files that still have the old
shape, and does nothing for a file already migrated, so it can run again after a branch took the default branch.
It writes nothing unless every old-shape file can be converted.
"""

import datetime as dt
import json
import os

import relay_queue as rq
import relay_where_migrate

OPEN_END = ("done", "dropped")


def _utc(seconds):
    return dt.datetime.fromtimestamp(int(seconds), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(root, paths):
    """[(commit, UTC time)] of the commits that changed any of `paths`, oldest first."""
    rc, out, err = rq._git(root, "log", "--reverse", "--format=%H %ct", "--", *paths)
    if rc != 0:
        raise rq.Refused(f"git log failed: {err}")
    return [tuple(line.split()) for line in rq._text(out).split("\n") if line.strip()]


def _state_at(root, commit, slug):
    """The state an item had at `commit` (None when it had no file there), whichever shape and folder it was in."""
    for sub in ("done/", ""):
        rc, out, _ = rq._git(root, "cat-file", "blob", f"{commit}:{rq.QDIR}/{sub}{slug}.json")
        if rc == 0:
            try:
                data = json.loads(out.decode("utf-8", "replace"))
            except ValueError:
                return None
            return data["state"] if "state" in data else rq.state_of(data)
    return None


def history(root, slug):
    """(found_at, taken_at, ended_at) of an item from git: the first commit that has the item (its .md form included); the last
    time it went from open (or from nothing) into the taken state; the last time it went into done or dropped. taken_at / ended_at are None when it never did."""
    paths = [f"{rq.QDIR}/{slug}.json", f"{rq.QDIR}/done/{slug}.json", f"{rq.QDIR}/{slug}.md"]
    commits = _log(root, paths)
    if not commits:
        raise rq.Refused(f"{slug}: no commit in the git history holds this item; commit the file first")
    taken = ended = None
    prev = None
    for commit, seconds in commits:
        state = _state_at(root, commit, slug)
        if state is None:
            continue
        if state == "taken" and prev in (None, "open"):       # a revert that brings a closed item back to taken is not a take
            taken = _utc(seconds)
        if state in OPEN_END and prev not in OPEN_END:
            ended = _utc(seconds)
        if state not in OPEN_END:
            ended = None
        prev = state
    return _utc(commits[0][1]), taken, ended


def convert(slug, data, found_at, taken_at, ended_at):
    """The new-shape item of the old-shape `data`, given its dates (None for an event that did not happen)."""
    state = data["state"]
    taken_by = data.get("taken_by") or data.get("closed_by") or None
    item = {key: data[key] for key in rq.ORDER if key in data}
    if isinstance(item.get("where"), str):                            # the old shape: one string, now a list of places
        if item["where"].strip():
            item["where"] = relay_where_migrate.split_where(slug, item["where"])[0]
        else:
            del item["where"]
    item.update(found_at=found_at, taken_at=None, taken_by=None, closed_at=None, test=None, dropped_at=None,
                dropped_why=data.get("dropped_why"))
    if state in ("taken", "done"):
        if taken_at is None:
            raise rq.Refused(f"{slug}: it is {state} but no commit in its history took it")
        item.update(taken_at=max(taken_at, found_at), taken_by=taken_by)
    if state == "done":
        if ended_at is None:
            raise rq.Refused(f"{slug}: it is done but no commit in its history closed it")
        item.update(closed_at=max(ended_at, item["taken_at"]), test=data.get("test") or None)
    if state == "dropped":
        if ended_at is None:
            raise rq.Refused(f"{slug}: it is dropped but no commit in its history dropped it")
        item.update(dropped_at=max(ended_at, found_at))
    return item


def migrate(root):
    """Rewrite every old-shape item file under `root`/.relay/queue (and its done/ folder, if the checkout still has one). Returns the paths rewritten, sorted."""
    base = os.path.join(root, rq.QDIR)
    if not os.path.isdir(base):
        raise rq.Refused(f"no {rq.QDIR} folder under {root}")
    todo = []
    for sub in ("", "done"):          # a checkout from before the removal of done/ still has the folder
        folder = os.path.join(base, sub)
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if not name.endswith(".json"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as handle:
                try:
                    data = json.load(handle)
                except ValueError as exc:
                    raise rq.Refused(f"{path} is not valid JSON: {exc}")
            if isinstance(data, dict) and any(k in data for k in rq.OLD_ONLY):
                if "state" not in data or data["state"] not in ("open", "taken", "done", "dropped"):
                    raise rq.Refused(f"{path} has no readable state")
                todo.append((path, name[:-5], data))
    converted = []
    for path, slug, data in todo:
        found_at, taken_at, ended_at = history(root, slug)
        text = rq.serialize(slug, convert(slug, data, found_at, taken_at, ended_at))
        converted.append((path, text))
    for path, text in converted:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    return sorted(os.path.relpath(p, root) for p, _ in converted)


def move_done_back(root: str) -> list[str]:
    """Move every `.relay/queue/done/<slug>.json` of the checkout `root` to `.relay/queue/<slug>.json` with `git mv` (the staged result
    is renames only, so `git log --follow` keeps each item's history). Returns the new paths, sorted. Nothing is moved when a
    file of that name is already in the queue folder. The caller commits."""
    stray = os.path.join(root, rq.QDIR, "done")
    names = sorted(n for n in os.listdir(stray) if n.endswith(".json")) if os.path.isdir(stray) else []
    clash = [n for n in names if os.path.exists(os.path.join(root, rq.QDIR, n))]
    if clash:
        raise rq.Refused(f"{', '.join(clash)} exist in both {rq.QDIR}/ and {rq.QDIR}/done/; nothing moved")
    for name in names:
        rc, _, err = rq._git(root, "mv", f"{rq.QDIR}/done/{name}", f"{rq.QDIR}/{name}")
        if rc != 0:
            raise rq.Refused(f"git mv {name} failed: {err}")
    return [f"{rq.QDIR}/{n}" for n in names]
