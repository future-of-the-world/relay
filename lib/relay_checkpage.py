"""`relay check page`: the private page for the person's step, built as one HTML file (docs/plans/review-gate.md 8.1).

Reads only the files of `.relay/checks/` at the branch head and git; writes plain HTML with a style block, no script, no
outside link or asset, code excerpts in `<pre>`. It never publishes: the front publishes the file with its own tool.
"""

import html
import os

import relay_git
import relay_inert
import relay_marks
import relay_queue
import relay_verdict

# Lines of finding content (a linter line, a status line, a code line, a failing-case line) the page shows before the
# rest is cut with "N more findings in ..." (bound 100-2000: at 100 about 12 findings fit, at 2000 the page costs the
# front about five times the tokens of the 400 default to publish).
PAGE_MAX_LINES = 400
CONTEXT = 2          # code lines shown above and below the finding's line

STYLE = (
    "body{font:15px/1.5 -apple-system,Helvetica,Arial,sans-serif;max-width:60em;margin:2em auto;padding:0 1em;color:#1a1a1a}"
    "h1{font-size:1.4em}h2{font-size:1.1em;margin-top:1.6em}.verdict{padding:.6em .9em;background:#eef5ee;border-left:4px solid #3a8a3a}"
    ".verdict.bad{background:#fbeeee;border-color:#b33}.finding{margin:1em 0;padding-bottom:.6em;border-bottom:1px solid #ddd}"
    ".linter{font-family:ui-monospace,Menlo,monospace;font-weight:600}.met{color:#2a7a2a}.notmet{color:#b33;font-weight:600}"
    "pre{background:#f5f5f5;padding:.5em;overflow:auto}p{margin:.3em 0}"
)


class PageError(Exception):
    """The page could not be built; the text says why in one line."""


def finding_view(finding, owner=()):
    """The page's view of a recorded finding: path, line, severity, id, what, linter, case (the failing case in one
    paragraph)."""
    return {"path": finding["path"], "line": finding["line"], "severity": finding["severity"], "rank": finding["rank"], "id": finding["id"],
            "what": finding["summary"], "linter": relay_verdict.linter(finding), "case": " ".join(l.strip() for l in finding["failing_case"] if l.strip()),
            "owner": [("moved to queue item %s: " % o["queue"] if o.get("queue") else "not wrong: ")
                      + " ".join(l.strip() for l in o["words"] if l.strip()) + " (%s)" % o["date"] for o in owner]}


def statuses_of(check):
    """{F<n>: "MET tests/x.py:88" or "NOT MET why"} from the stored check data (the verdict, then its reason in one line)."""
    return {item["id"]: (item["verdict"] + " " + " ".join(l.strip() for l in item.get("reason") or [] if l.strip())).strip() for item in check["findings"]}


def excerpt(repo, commit, finding):
    """The code lines around the finding at the reviewed commit, [(number, text)]; [] when the file is not there."""
    rc, text = relay_git.git(repo, "show", "%s:%s" % (commit, finding["path"]), raw=True)
    if rc != 0:
        return []
    lines = text.splitlines()
    first = max(1, finding["line"] - CONTEXT)
    last = min(len(lines), finding["line"] + CONTEXT)
    return [(n, lines[n - 1]) for n in range(first, last + 1)]


def queue_slug(repo, default, finding):
    """(slug, note) of the queue item on the default branch that carries this finding's linter line, else None. The note is ""
    for an item still in the queue, " (closed)" or " (dropped)" for one that moved to `done/`: the finding was queued all the same."""
    if relay_git.git(repo, "show-ref", "--verify", "--quiet", "refs/heads/" + default)[0] != 0:
        return None
    main = relay_git.main_checkout(repo) or repo
    reader = relay_queue.Reader(main, "refs/heads/" + default)
    for note, items in (("", reader.items()), (" (closed)", reader.closed_items())):
        for slug, item in sorted(items.items()):
            if not item["problems"] and finding["linter"] in item["what"]:
                return slug, (" (dropped)" if item["state"] == "dropped" else note)
    return None


def cost(finding, shown):
    return 2 + len(shown) + (1 if finding["case"] else 0)


def e(text):
    return html.escape(str(text), quote=True)


def render_finding(finding, status, shown, slug=None, outside=False):
    parts = ['<div class="finding"><p class="linter">%s</p>' % e(finding["linter"])]
    if outside:
        parts.append("<p>%s</p>" % (("queued as <b>%s</b>%s" % (e(slug[0]), e(slug[1]))) if slug else "not queued"))
    else:
        css = "met" if status.startswith("MET") else "notmet"
        parts.append('<p class="%s">%s</p>' % (css, e(status) if status != "not checked" else "not checked"))
    if shown:
        parts.append("<pre>%s</pre>" % e("\n".join("%4d  %s" % (n, t) for n, t in shown)))
    if finding["case"]:
        parts.append("<p>%s</p>" % e(finding["case"]))
    for words in finding["owner"]:
        parts.append("<p>Owner: %s</p>" % e(words))
    parts.append("</div>")
    return "".join(parts)


def date_of(repo, commit):
    rc, out = relay_git.git(repo, "log", "-1", "--format=%cs", commit)
    return out if rc == 0 and out else "unknown date"


def build(repo, branch):
    """The page's HTML text for `branch`."""
    repo = relay_git.main_checkout(repo)
    if repo is None:
        raise PageError("not a git repository")
    default = relay_git.default_branch(repo)
    ref = "refs/heads/" + branch
    if default is None:
        raise PageError("cannot tell the default branch: set project.default_branch in .claude/kit.toml")
    if relay_git.git(repo, "rev-parse", "--verify", "-q", ref)[0] != 0:
        raise PageError("no branch %s" % branch)
    mark = relay_marks.newest(repo, ref, relay_marks.marks(repo, ref))
    if mark is None:
        raise PageError("no check mark for %s yet: run delegate:checker on its head first" % branch)
    commit, data = mark
    reviewed = data["verdict"]["reviewed"]
    review_name = str(data.get("review") or "%s.review.json" % reviewed)
    try:
        review_set = relay_marks.review_set(repo, ref, review_name)
        check = relay_marks.check_data(repo, ref, str(data.get("check") or "%s.check.json" % commit))
    except relay_marks.MarkError as exc:
        raise PageError(str(exc))
    if review_set is None or check is None:
        raise PageError("the review or check data of %s is not stored for %s (the mark is from before the data form: run delegate:checker again)" % (commit, branch))
    statuses = statuses_of(check)
    inside = [finding_view(f, relay_verdict.owner_of(r, f["id"])) for r in review_set["reviews"] for f in r["findings"] if f["kind"] in ("inside", "design", "feature")]
    outside = [finding_view(f, relay_verdict.owner_of(r, f["id"])) for r in review_set["reviews"] for f in r["findings"] if f["kind"] == "outside"]
    new = [finding_view(f) for f in check["new"]]
    questions = [finding_view(f, relay_verdict.owner_of(r, f["id"])) for r in review_set["reviews"] for f in r["findings"] if f["kind"] == "question"]
    title_line = branch

    gate = relay_marks.newest(repo, ref, relay_marks.gate_logs(repo, ref))
    if gate is None:
        free = "none yet"
    elif gate[1] == 0:
        stale = relay_inert.changed(repo, gate[0], ref)           # code changed after the gate: the merge refuses (step 6)
        free = "green, but code changed since (gate of %s)" % date_of(repo, gate[0]) if stale else "green (gate of %s)" % date_of(repo, gate[0])
    else:
        free = "red (gate of %s, exit %d)" % (date_of(repo, gate[0]), gate[1])
    met = sum(1 for f in inside if statuses.get(f["id"], "").startswith("MET"))
    all_met = inside and met == len(inside) and not new and data["verdict"]["open"] == 0
    done = "all fixed and checked" if all_met else "%d fixed and checked" % met
    review_part = "%d found inside the change, %s" % (len(inside), done) if inside else "nothing found inside the change"
    if new:
        review_part += ", %d new in the check" % len(new)
    queued = sum(1 for f in outside if queue_slug(repo, default, f))
    verdict = "Free checks: %s. Review: %s; %d outside, %s. Open: %d." % (
        free, review_part, len(outside), "none queued" if not queued else "%d queued" % queued, data["verdict"]["open"])
    bad = data["verdict"]["open"] != 0 or gate is None or gate[1] != 0 or free.startswith("green, but")

    budget, hidden, body = PAGE_MAX_LINES, 0, []
    for heading, group, is_outside in (("Inside the change", inside, False), ("New in the check", new, False),
                                       ("Questions for the owner", questions, False), ("Outside this change", outside, True)):
        if not group:
            continue
        body.append("<h2>%s</h2>" % heading)
        for finding in group:
            shown = [] if finding["path"] == "artifact" else excerpt(repo, reviewed, finding)
            need = cost(finding, shown)
            if hidden or need > budget:
                hidden += 1
                continue
            budget -= need
            slug = queue_slug(repo, default, finding) if is_outside else None
            status = {"New in the check": "new in the check", "Questions for the owner": "question"}.get(heading) or statuses.get(finding["id"], "not checked")
            body.append(render_finding(finding, status, shown, slug, is_outside))
    if hidden:
        body.append("<p>%d more finding%s in .relay/checks/%s</p>" % (hidden, "" if hidden == 1 else "s", e(review_name)))

    green = relay_marks.newest(repo, ref, [(c, x) for c, x in relay_marks.gate_logs(repo, ref) if x == 0])
    log = (relay_marks._show(repo, ref, "%s.gate.log" % green[0]) or "").splitlines()[2:-1] if green else []
    gate_html = "<h2>The gate</h2><pre>%s</pre>" % e("\n".join(log)) if log else ""
    rc, stat = relay_git.git(repo, "diff", "--numstat", "refs/heads/%s...%s" % (default, ref))
    files = []
    for line in stat.splitlines() if rc == 0 else []:
        added, deleted, path = line.split("\t", 2)
        if not relay_inert.matches(path):
            files.append("%s  +%s -%s" % (path, added, deleted))
    files_html = "<h2>The branch's own files</h2><pre>%s</pre>" % e("\n".join(files)) if files else ""

    project = os.path.basename(repo)
    return ('<!doctype html><html><head><meta charset="utf-8"><title>%s</title><style>%s</style></head><body>'
            '<h1>%s: %s</h1><p class="verdict%s">%s</p>%s%s%s</body></html>\n') % (
        e(project), STYLE, e(project), e(title_line), " bad" if bad else "", e(verdict), "".join(body), gate_html, files_html)


def write(repo, branch, out=None):
    """Build the page and write it to `out` (default `<repo>/.ci/page-<name>.html`); returns the path. PageError when
    the page cannot be built, with no file written."""
    text = build(repo, branch)
    if out is None:
        out = os.path.join(os.path.realpath(repo), ".ci", "page-%s.html" % branch.split("/", 1)[-1])
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(text)
    return out
