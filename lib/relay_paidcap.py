"""The owner's daily cap for paid runs and the day's spend, from relay's own records.

The cap is `paid_cap_usd_per_day` in projects.toml [global]. The spend of a UTC day is the sum of
  - the eval records bin/eval-record stores ($RELAY_HOME/evals/<repo>/*.json: startedAt, costUsd), and
  - the direct runs: the aggregate-result.json a `claude plugin eval` leaves in <checkout>/evals/plugin/results/<stamp>/ of the
    repo's main checkout and its worktrees, when no stored record has the same startedAt (a bin/ci run is both; it counts once), and
  - the bench results (bench_dir()/*/results.json: started, the cost_usd of every row).
A record that cannot be read or has no numeric cost is left out (it is not counted as zero spend that was measured).
"""
import json
import os
import re
import subprocess

from relay_config import bench_dir, home_dir, projects_file, read_toml

KEY = "paid_cap_usd_per_day"


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


def cap(path=None):
    """The cap in USD per day, from projects.toml [global]; ValueError when it is missing or not a positive number."""
    path = path or projects_file()
    value = read_toml(path).get("global", {}).get(KEY)
    if not _num(value) or value <= 0:
        raise ValueError(f"{KEY} is missing or not above 0 in [global] of {path}")
    return float(value)


def with_cap(text, usd):
    """`text` of projects.toml with the cap set to `usd`: the value of an existing line is replaced and its comment kept;
    else the line is added right after [global]. ValueError for a cap not above 0 or a file with no [global] section."""
    if not _num(usd) or usd <= 0:
        raise ValueError("the cap must be above 0")
    value = f"{usd:.12g}"
    if re.search(rf"^{KEY}\s*=", text, re.M):
        return re.sub(rf"^({KEY}\s*=\s*)[^\s#]+", lambda m: m.group(1) + value, text, count=1, flags=re.M)
    text, n = re.subn(r"^(\[global\]\n)", lambda m: f"{m.group(1)}{KEY} = {value}   # the owner's cap for paid runs per UTC day (bin/paid-cost cap)\n", text, count=1, flags=re.M)
    if not n:
        raise ValueError("no [global] section in projects.toml")
    return text


def set_cap(usd, path=None):
    """Write the cap into the projects.toml `path` in place (the rest of the file is untouched)."""
    path = path or projects_file()
    with open(path, encoding="utf-8") as f:
        text = f.read()
    new = with_cap(text, usd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)


def land_cap(usd):
    """Set the cap where the next paid run reads it: with RELAY_PROJECTS the file in place; else one commit of projects.toml
    on the default branch, landed the way `relay queue` lands its file (the main checkout stays clean). Returns the line to print."""
    if os.environ.get("RELAY_PROJECTS"):
        set_cap(usd)
        return f"{usd:.12g}"
    import relay_queue
    from relay_config import ROOT

    def planner(reader):
        blob = relay_queue.cat_batch(reader.main, [f"{reader.rev}:projects.toml"])[0]
        if blob is None:
            raise relay_queue.Refused("the default branch has no projects.toml")
        try:
            new = with_cap(blob.decode("utf-8"), usd)
        except ValueError as e:
            raise relay_queue.Refused(str(e))
        return relay_queue.Plan("paid-cap", {"projects.toml": new}, f"cap {usd:.12g}", "set")
    try:
        relay_queue._land(ROOT, planner)
    except relay_queue.Refused as e:
        raise ValueError(str(e))
    return f"{usd:.12g}"


def _day(stamp):
    """YYYY-MM-DD of a stamp such as 2026-10-24T07:47:54Z or 2026-10-24T07-47-54Z, else None."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})T", stamp) if isinstance(stamp, str) else None
    return m.group(1) if m else None


def _json_files(folder, only_results=False, name=None):
    """The parsed JSON files of `folder`; with only_results the results.json of each subfolder, with `name` that file of each subfolder."""
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return
    for name_ in names:
        sub = name or ("results.json" if only_results else None)
        p = os.path.join(folder, name_, sub) if sub else os.path.join(folder, name_)
        if not sub and not name_.endswith(".json"):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                yield json.load(f)
        except (OSError, ValueError):
            continue


def eval_batches(home=None, roots=None):
    """[(day, cost)] of every stored eval record that has a numeric costUsd, and of the direct runs in `roots` no record has."""
    out = []
    known: set[str] = set()
    root = os.path.join(home or home_dir(), "evals")
    try:
        repos = sorted(os.listdir(root))
    except OSError:
        return out
    for repo in repos:
        for d in _json_files(os.path.join(root, repo)):
            if isinstance(d, dict) and _num(d.get("costUsd")):
                out.append((_day(d.get("startedAt")), float(d["costUsd"])))
                known.add(str(d.get("startedAt")))
    out += [(day, cost) for day, cost, _ in direct_batches(roots or [], known)]
    return out


def suite_roots(repo: str) -> list[str]:
    """The checkouts of `repo` (its main checkout and every worktree) where a direct eval run may have left its results; [] when git cannot say."""
    try:
        done = subprocess.run(["git", "-C", repo, "worktree", "list", "--porcelain"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line[len("worktree "):] for line in done.stdout.splitlines() if line.startswith("worktree ")]


def direct_batches(roots: list[str], known: set[str]) -> list[tuple[str | None, float, str]]:
    """[(day, cost, startedAt)] of every aggregate-result.json under <root>/evals/plugin/results/*/ with a numeric costUsd whose
    startedAt is not in `known` (the stamps of the stored records); one run seen from two checkouts counts once."""
    out: list[tuple[str | None, float, str]] = []
    seen = set(known)
    for root in roots:
        for d in _json_files(os.path.join(root, "evals", "plugin", "results"), only_results=False, name="aggregate-result.json"):
            stamp = d.get("startedAt") if isinstance(d, dict) else None
            if isinstance(stamp, str) and _num(d.get("costUsd")) and stamp not in seen:
                seen.add(stamp)
                out.append((_day(stamp), float(d["costUsd"]), stamp))
    return out


def bench_rows(folder=None):
    """[(day, cost)] of every bench row that has a numeric cost_usd."""
    out = []
    for d in _json_files(folder or bench_dir(), only_results=True):
        out += _rows(d)
    return out


def _rows(d):
    if not isinstance(d, dict) or not isinstance(d.get("rows"), list):
        return []
    day = _day(d.get("started"))
    return [(day, float(r["cost_usd"])) for r in d["rows"] if isinstance(r, dict) and _num(r.get("cost_usd"))]


def link_dir(home=None):
    """Where a bench run with --out leaves a link to its results folder, so the day's spend counts it ($RELAY_HOME/bench-out)."""
    return os.path.join(home or home_dir(), "bench-out")


def link_out(out_dir, stamp, home=None):
    """Record that the bench run `stamp` writes its results.json into `out_dir`."""
    os.makedirs(link_dir(home), exist_ok=True)
    with open(os.path.join(link_dir(home), stamp + ".json"), "w", encoding="utf-8") as f:
        json.dump({"results": os.path.join(os.path.abspath(out_dir), "results.json")}, f)


def all_bench_rows(home=None, extra=None):
    """The bench rows of the default folder (home/bench), of every --out run linked from home/bench-out, and of `extra` (a folder) when it is another one."""
    default = os.path.join(home, "bench") if home else bench_dir()
    out = bench_rows(default)
    for link in _json_files(link_dir(home)):
        try:
            with open(link["results"], encoding="utf-8") as f:
                out += _rows(json.load(f))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if extra and os.path.realpath(extra) != os.path.realpath(default):
        out += bench_rows(extra)
    return out


def spend_today(today, home=None, bench=None, roots=None):
    """(spend in USD, number of runs) of the UTC day `today` (YYYY-MM-DD): eval batches (direct runs in `roots` included) and bench sessions."""
    items = [c for d, c in eval_batches(home, roots) if d == today] + [c for d, c in all_bench_rows(home, bench) if d == today]
    return sum(items), len(items)


def check(today, estimate, kind, path=None, home=None, bench=None, roots=None):
    """None when spend + estimate stays within the cap; else the refusal line naming the cap, the spend and the estimate."""
    limit = cap(path)
    spent, _ = spend_today(today, home, bench, roots)
    if spent + estimate > limit:
        return (f"{kind} refused: the day's cap is ${limit:g}, ${spent:.2f} is spent today ({today}) and this run is estimated at "
                f"${estimate:.2f}; raise the cap with `bin/paid-cost cap <USD>` or run tomorrow")
    return None


def bench_estimate(sessions, bench=None, home=None):
    """The estimate of a bench run: its sessions x the largest session cost measured so far (0 when none was measured)."""
    return sessions * max((c for _, c in all_bench_rows(home, bench)), default=0.0)


def eval_estimate(home=None):
    """The estimate of a plugin eval batch: the largest full batch stored so far (0 when none was measured)."""
    return max((c for _, c in eval_batches(home)), default=0.0)
