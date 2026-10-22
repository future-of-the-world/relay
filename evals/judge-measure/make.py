#!/usr/bin/env python3
"""Builds, or checks, the measurement cases of evals/judge-measure/.

Each measure-<question>/ case judges recorded replies from files. This script
writes, from items.txt and the production rubric, the files the eval reads:

  judged/<NN>.txt                    the reply of item NN, composed into a real full reply
  graders/<yes|no>--<NN>-<name>.md   one llm grader per item; its body is the production
                                     rubric (evals/plugin/<case>/graders/<grader>.md) byte for byte

  python3 evals/judge-measure/make.py           write the files, print every item's length
  python3 evals/judge-measure/make.py --check   write nothing; exit 1 when a committed file
                                                differs, or when an item breaks a rule below

items.txt line:  yes|no <source, relative to evals/> [into <template, relative to the case folder>]
A template holds one line {{FINDING}}; the source's finding lines replace it. Rules (--check):
  - every composed item is 1,000 characters or more (the length and form of a real reply)
  - every item, yes and no, passes the question's code graders (the judge must be the one that decides)
  - a template outside its slot never mentions the finding (the question's `mention` regex), so a
    "no" item cannot report the fact in a second place and be right to pass (check-judge-v5 N1)
  - every recorded bad reply named after a question's llm grader is listed in that question's items.txt
    (an item counts only as a parsed line of items.txt, not as text in a comment)
  - every known wrong answer (the question's `known_wrong` phrases in questions.json: wrong replies that
    pass the code graders, so only the judge can refuse them) appears in a "no" item
Standard library and node only; no model is called.
"""
import argparse, glob, json, os, re, subprocess, sys

MIN_LEN = 1000
MARK = "{{FINDING}}"


def split_front(text):
    lines = text.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        raise SystemExit("no front matter")
    end = lines.index("---", 1)
    meta = {}
    for line in lines[1:end]:
        k, _, v = line.partition(":")
        v = v.strip()
        meta[k.strip()] = json.loads(v) if v.startswith('"') else v
    return meta, "\n".join(lines[end + 1:])


def node_test(triples):
    js = ("const t=JSON.parse(require('fs').readFileSync(0,'utf8'));"
          "process.stdout.write(JSON.stringify(t.map(([p,f,x])=>new RegExp(p,f).test(x))))")
    out = subprocess.run(["node", "-e", js], input=json.dumps(triples), capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def compose(source, template, keep):
    """The source's finding lines, as bullets, in the template's slot."""
    body = []
    for line in source.split("\n"):
        line = line.rstrip()
        if not line or line.startswith("Report:") or line.startswith("Review of master"):
            continue
        line = re.sub(r"^\d+ confirmed\.\s*", "", line)
        if not line or not re.search(keep, line):
            continue
        line = re.sub(r"^\d+\.\s+", "", line)
        body.append(line if line.startswith(("- ", "* ")) else "- " + line)
    return template.replace(MARK, "\n".join(body))


def load(root):
    here = os.path.join(root, "judge-measure")
    questions = json.load(open(os.path.join(here, "questions.json"), encoding="utf-8"))
    out = {}
    for name, q in questions.items():
        cdir = os.path.join(here, name)
        rubric = split_front(open(os.path.join(root, "plugin", q["case"], "graders", q["grader"] + ".md"), encoding="utf-8").read())[1]
        code = [split_front(open(os.path.join(root, "plugin", q["case"], "graders", g + ".md"), encoding="utf-8").read())[0] for g in q["code"]]
        items = []
        for raw in open(os.path.join(cdir, "items.txt"), encoding="utf-8").read().split("\n"):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            m = re.match(r"^(yes|no) (\S+)(?: into (\S+))?$", raw)
            if not m:
                raise SystemExit(f"{name}/items.txt: cannot read the line: {raw}")
            items.append({"want": m.group(1), "source": m.group(2), "template": m.group(3)})
        out[name] = {"q": q, "dir": cdir, "rubric": rubric, "code": code, "items": items}
    return here, out


def build(root):
    """Returns (files, problems, report): the files make.py owns (path relative to judge-measure/ -> text)."""
    here, qs = load(root)
    files, problems, report, triples, where = {}, [], [], [], []
    for name, d in qs.items():
        q = d["q"]
        no_texts = []
        for i, it in enumerate(d["items"], 1):
            label = f"{name} item {i:02d} ({it['want']} {os.path.basename(it['source'])})"
            sp = os.path.join(root, it["source"])
            if not os.path.exists(sp):
                problems.append(f"{label}: source {it['source']} does not exist"); continue
            src = open(sp, encoding="utf-8").read()
            if it["template"]:
                tp = os.path.join(d["dir"], it["template"])
                if not os.path.exists(tp):
                    problems.append(f"{label}: template {it['template']} does not exist"); continue
                tpl = open(tp, encoding="utf-8").read()
                if tpl.count(MARK) != 1:
                    problems.append(f"{label}: template {it['template']} needs exactly one {MARK}"); continue
                text = compose(src, tpl, q["keep"])
                outside = tpl.replace(MARK, "")
                hit = re.search(q["mention"], outside, re.I)
                if hit:
                    problems.append(f"{label}: template {it['template']} mentions the finding outside its slot ({hit.group(0)!r}); a {it['want']} item built on it is not a clean {it['want']}")
            elif it["want"] == "no":
                problems.append(f"{label}: a 'no' item needs a template (into ...)"); continue
            else:
                text = src
            nn = f"{i:02d}"
            if it["want"] == "no":
                no_texts.append(text)
            slug = re.sub(r"[^A-Za-z0-9]+", "-", os.path.splitext(os.path.basename(it["source"]))[0]).strip("-")
            files[f"{name}/judged/{nn}.txt"] = text
            files[f"{name}/graders/{it['want']}--{nn}-{slug}.md"] = (
                f"---\ntype: llm\nfocus: {{source: file, path: judged/{nn}.txt}}\n---\n" + d["rubric"])
            report.append(f"{name} {nn} {it['want']:3} {len(text):5} chars  {os.path.basename(it['source'])}")
            if len(text) < MIN_LEN:
                problems.append(f"{label}: {len(text)} characters, under {MIN_LEN} (not the length of a real reply)")
            for g in d["code"]:
                triples.append([g["pattern"], g.get("flags", ""), text]); where.append(f"{label}: code grader {g.get('pattern')[:40]}...")
        for phrase in q.get("known_wrong", []):
            if not any(phrase in t for t in no_texts):
                problems.append(f"{name}: the known wrong answer {phrase!r} is in no 'no' item (add an item that says it)")
        # every recorded bad reply named after the llm grader is measured
        listed = {it["source"] for it in d["items"]}
        for p in sorted(glob.glob(os.path.join(root, "plugin", q["case"], "recorded", "bad", q["grader"] + "__*.txt"))):
            rel = os.path.relpath(p, root)
            if rel not in listed:
                problems.append(f"{name}: {rel} is a recorded wrong reply and is in no items.txt")
    for ok, w in zip(node_test(triples) if triples else [], where):
        if not ok:
            problems.append(w + " does not pass (the judge must decide every item, so the code check has to pass)")
    return here, files, problems, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), help="the evals/ folder")
    a = ap.parse_args()
    here, files, problems, report = build(a.root)
    for line in report:
        print(line)
    owned = set()
    for q in glob.glob(os.path.join(here, "measure-*")):
        for sub in ("judged", "graders"):
            for p in glob.glob(os.path.join(q, sub, "*")):
                owned.add(os.path.relpath(p, here))
    if a.check:
        for rel, text in sorted(files.items()):
            p = os.path.join(here, rel)
            if not os.path.exists(p):
                problems.append(f"{rel} is missing (run make.py)")
            elif open(p, encoding="utf-8").read() != text:
                problems.append(f"{rel} differs from what make.py builds (grader bodies must equal the production rubric byte for byte; run make.py)")
        for rel in sorted(owned - set(files)):
            problems.append(f"{rel} is not built from any items.txt line (stale; run make.py)")
        for p in problems:
            print("FAIL", p)
        print("make.py --check: ok" if not problems else f"make.py --check: {len(problems)} problem(s)")
        return 1 if problems else 0
    if problems:
        for p in problems:
            print("FAIL", p)
        return 1
    for rel in owned - set(files):
        os.remove(os.path.join(here, rel))
    for rel, text in files.items():
        p = os.path.join(here, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8").write(text)
    print(f"make.py: wrote {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
