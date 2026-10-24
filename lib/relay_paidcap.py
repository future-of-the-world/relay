"""The owner's daily cap for paid runs and the day's spend, from relay's own records.

The cap is `paid_cap_usd_per_day` in projects.toml [global]. The spend of a UTC day is the sum of
  - the eval records bin/eval-record stores ($RELAY_HOME/evals/<repo>/*.json: startedAt, costUsd), and
  - the bench results (bench_dir()/*/results.json: started, the cost_usd of every row).
A record that cannot be read or has no numeric cost is left out (it is not counted as zero spend that was measured).
"""
import json
import os
import re

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


def set_cap(usd, path=None):
    """Write the cap into projects.toml [global], replacing the line or adding it after `title`; the rest of the file is untouched."""
    path = path or projects_file()
    if not _num(usd) or usd <= 0:
        raise ValueError("the cap must be above 0")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    line = f"{KEY} = {usd:g}"
    if re.search(rf"^{KEY}\s*=.*$", text, re.M):
        text = re.sub(rf"^{KEY}\s*=.*$", line, text, count=1, flags=re.M)
    else:
        text, n = re.subn(r"^(\[global\]\n)", rf"\1{line}   # the owner's cap for paid runs per UTC day (bin/paid-cost cap)\n", text, count=1, flags=re.M)
        if not n:
            raise ValueError(f"no [global] section in {path}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _day(stamp):
    """YYYY-MM-DD of a stamp such as 2026-10-24T07:47:54Z or 2026-10-24T07-47-54Z, else None."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})T", stamp) if isinstance(stamp, str) else None
    return m.group(1) if m else None


def _json_files(folder, only_results=False):
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return
    for name in names:
        p = os.path.join(folder, name, "results.json") if only_results else os.path.join(folder, name)
        if not only_results and not name.endswith(".json"):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                yield json.load(f)
        except (OSError, ValueError):
            continue


def eval_batches(home=None):
    """[(day, cost)] of every stored eval record that has a numeric costUsd."""
    out = []
    root = os.path.join(home or home_dir(), "evals")
    try:
        repos = sorted(os.listdir(root))
    except OSError:
        return out
    for repo in repos:
        for d in _json_files(os.path.join(root, repo)):
            if isinstance(d, dict) and _num(d.get("costUsd")):
                out.append((_day(d.get("startedAt")), float(d["costUsd"])))
    return out


def bench_rows(folder=None):
    """[(day, cost)] of every bench row that has a numeric cost_usd."""
    out = []
    for d in _json_files(folder or bench_dir(), only_results=True):
        if not isinstance(d, dict) or not isinstance(d.get("rows"), list):
            continue
        day = _day(d.get("started"))
        out += [(day, float(r["cost_usd"])) for r in d["rows"] if isinstance(r, dict) and _num(r.get("cost_usd"))]
    return out


def spend_today(today, home=None, bench=None):
    """(spend in USD, number of runs) of the UTC day `today` (YYYY-MM-DD): eval batches and bench sessions."""
    items = [c for d, c in eval_batches(home) if d == today] + [c for d, c in bench_rows(bench) if d == today]
    return sum(items), len(items)


def check(today, estimate, kind, path=None, home=None, bench=None):
    """None when spend + estimate stays within the cap; else the refusal line naming the cap, the spend and the estimate."""
    limit = cap(path)
    spent, _ = spend_today(today, home, bench)
    if spent + estimate > limit:
        return (f"{kind} refused: the day's cap is ${limit:g}, ${spent:.2f} is spent today ({today}) and this run is estimated at "
                f"${estimate:.2f}; raise the cap with `bin/paid-cost cap <USD>` or run tomorrow")
    return None


def bench_estimate(sessions, bench=None):
    """The estimate of a bench run: its sessions x the largest session cost measured so far (0 when none was measured)."""
    return sessions * max((c for _, c in bench_rows(bench)), default=0.0)


def eval_estimate(home=None):
    """The estimate of a plugin eval batch: the largest full batch stored so far (0 when none was measured)."""
    return max((c for _, c in eval_batches(home)), default=0.0)
