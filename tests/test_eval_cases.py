"""Eval case files must load, and the relay stand-in used by queue cases must behave like `relay queue show|note`."""
import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest
import datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import relay_queue as rq  # noqa: E402
PLUGIN = os.path.join(ROOT, "evals", "plugin")
STUB = os.path.join(PLUGIN, "relay-stub.py")


def description_line(path: str) -> str:
    for line in open(path, encoding="utf-8").read().split("\n"):
        if line.startswith("description:"):
            return line.partition(":")[2].strip()
    raise AssertionError("%s has no description" % path)


class CaseFiles(unittest.TestCase):
    def test_shared_fixture_turns_the_lanes_stop_reminder_off(self):
        # No plugin eval case is about lanes; with the Stop refusal on, the last reply is a short lanes sentence and the
        # last-message graders of recall-decision read it instead of the answer. 0 = the lanes line only, no refusal.
        import tomllib
        with open(os.path.join(PLUGIN, "fixture", ".claude", "kit.toml"), "rb") as fh:
            cfg = tomllib.load(fh)
        self.assertEqual(cfg["front"]["stop_nudge"], 0)
        for path in sorted(glob.glob(os.path.join(PLUGIN, "*", "case.yaml"))):
            self.assertNotIn("lanes", os.path.basename(os.path.dirname(path)))  # a lanes case would need its own fixture

    def test_every_description_is_one_valid_double_quoted_string(self):
        # a quote inside a description broke recall-decision's case.yaml ("YAML parse failed"): `claude plugin eval` then
        # skipped the case and the gate stayed green without it. A JSON string is valid YAML, so json.loads is the check.
        for path in sorted(glob.glob(os.path.join(PLUGIN, "*", "case.yaml"))):
            text = description_line(path)
            if text.startswith('"'):
                json.loads(text)


class CriticRoleRuleScaffold(unittest.TestCase):
    def test_the_agent_may_not_read_the_rule_file_but_the_hook_still_can(self):
        # Permission deny rules bind the agent's Read/Grep/Glob tools; a hook is run by relay itself and is not bound. So the
        # rule file stays on disk (the hook delivers it) while the agent can reach it only through the hook's injection.
        scaffold = os.path.join(PLUGIN, "critic-role-rule", "scaffold.sh")
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["bash", scaffold], cwd=tmp, check=True, capture_output=True, text=True)
            self.assertTrue(os.path.isfile(os.path.join(tmp, ".claude", "kit", "judge.md")))
            # The runner starts its child with --setting-sources user, so only the case's own frontmatter reaches the child's
            # --disallowed-tools; a deny in the fixture's .claude/settings.json is never read and must not count.
            self.assertFalse(os.path.exists(os.path.join(tmp, ".claude", "settings.json")))
            with open(os.path.join(PLUGIN, "critic-role-rule", "prompt.md"), encoding="utf-8") as fh:
                front = fh.read().split("---")[1]
            line = [x for x in front.splitlines() if x.startswith("disallowed_tools:")]
            self.assertEqual(len(line), 1)
            deny = json.loads(line[0].partition(":")[2])
            self.assertIn("Read(./.claude/kit/**)", deny)
            self.assertIn("Read(./.claude/**)", deny)
            # committed on master, so it is in neither `git status` nor the diff under review
            status = subprocess.run(["git", "-C", tmp, "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
            self.assertEqual(status, "")


class Stub(unittest.TestCase):
    def run_stub(self, work: str, *args: str) -> subprocess.CompletedProcess:
        env = {"PATH": os.environ.get("PATH", ""), "TZ": "UTC"}  # the real code is called with UTC below
        return subprocess.run([sys.executable, "-I", STUB, *args], cwd=work, capture_output=True, text=True, env=env)

    def project(self, tmp: str) -> str:
        os.makedirs(os.path.join(tmp, ".relay", "queue"))
        with open(os.path.join(tmp, ".relay", "queue", "an-item.json"), "w", encoding="utf-8") as fh:
            fh.write('{"title": "An item"}')
        return tmp

    def test_note_prints_the_text_back_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.project(tmp)
            toml = os.path.join(tmp, "n.toml")
            with open(toml, "w", encoding="utf-8") as fh:
                fh.write("said = '''минуты ожидания проверки'''\n")
            done = self.run_stub(work, "queue", "note", "an-item", "--input", toml)
            self.assertEqual(done.returncode, 0, done.stderr)
            # the judge reads the reply, so the stored words must come back verbatim
            self.assertEqual(done.stdout, 'noted an-item: said: "минуты ожидания проверки"\n')
            self.assertEqual(open(os.path.join(work, ".relay", "queue", "an-item.json"), encoding="utf-8").read(), '{"title": "An item"}')

    def test_note_refuses_two_kinds_and_an_unknown_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.project(tmp)
            toml = os.path.join(tmp, "n.toml")
            with open(toml, "w", encoding="utf-8") as fh:
                fh.write("said = 'a'\nfact = 'b'\n")
            self.assertEqual(self.run_stub(work, "queue", "note", "an-item", "--input", toml).returncode, 1)
            self.assertEqual(self.run_stub(work, "queue", "note", "nope", "--input", toml).returncode, 1)

    def test_show_prints_the_item_found_by_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.project(tmp)
            done = self.run_stub(work, "queue", "show", "AN-item")
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout, "an-item: An item\n")

    def test_show_finds_a_word_inside_the_item_and_lists_several_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self.project(tmp)
            with open(os.path.join(work, ".relay", "queue", "other-thing.json"), "w", encoding="utf-8") as fh:
                fh.write('{"title": "Other", "notes": [{"at": "2026-10-27T03:00:00Z", "said": ["Is the done/ folder needed?"]}]}')
            # "done" is only in the notes of other-thing, not in any file name: found by content, one match is shown
            one = self.run_stub(work, "queue", "show", "done")
            self.assertEqual(one.returncode, 0, one.stderr)
            self.assertTrue(one.stdout.startswith("other-thing: Other\n"), one.stdout)
            # "item" is in an-item (name) only; "t" is in both names: two matches are listed by name, sorted
            many = self.run_stub(work, "queue", "show", "t")
            self.assertEqual(many.stdout, "an-item\nother-thing\n")
            self.assertEqual(self.run_stub(work, "queue", "list").stdout, "an-item\nother-thing\n")

    def test_note_takes_the_exact_slug_only(self):
        # F4: the real command refuses 'nothing noted: no queue item' for anything but the slug; a word found inside the item is not one
        with tempfile.TemporaryDirectory() as tmp:
            work = self.project(tmp)
            toml = os.path.join(tmp, "n.toml")
            with open(toml, "w", encoding="utf-8") as fh:
                fh.write("said = 'a'\n")
            self.assertEqual(self.run_stub(work, "queue", "note", "an-item", "--input", toml).returncode, 0)
            for word in ("item", "An", "an"):  # in the name or the title, but not the slug
                self.assertEqual(self.run_stub(work, "queue", "note", word, "--input", toml).returncode, 1, word)
            # show still finds by words
            self.assertEqual(self.run_stub(work, "queue", "show", "item").returncode, 0)


class StubShowMatchesTheRealNotes(unittest.TestCase):
    """F2: the stub's show prints the Notes lines the real `relay queue show` prints (notes_text), not the raw JSON."""

    def stub_show(self, slug_dir: str, slug: str) -> str:
        env = {"PATH": os.environ.get("PATH", ""), "TZ": "UTC"}
        return subprocess.run([sys.executable, "-I", STUB, "queue", "show", slug], cwd=slug_dir, capture_output=True, text=True, env=env).stdout

    def check_item(self, text: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".relay", "queue"))
            with open(os.path.join(tmp, ".relay", "queue", "x.json"), "w", encoding="utf-8") as fh:
                fh.write(text)
            out = self.stub_show(tmp, "x")
        item = rq.parse("x", text)
        self.assertEqual(item["problems"], [])
        want = rq.notes_text(item, dt.timezone.utc)
        got = out.split("\n")
        if want:
            self.assertIn("\n".join(want), out)
            self.assertEqual(got[got.index("Notes:"):][: len(want)], want)
        else:
            self.assertNotIn("Notes:", out)  # an item with no notes prints no Notes section
        return out

    def test_recall_decision_fixture_items_print_the_real_notes(self):
        for path in sorted(glob.glob(os.path.join(PLUGIN, "recall-decision", "queue", "*.json"))):
            with open(path, encoding="utf-8") as fh:
                out = self.check_item(fh.read())
            self.assertNotIn('"answer"', out)  # not the raw JSON
            self.assertRegex(out, r"the owner answered '[^']+' asked 20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ \(whole reply\):")

    def test_a_said_note_a_fact_and_an_open_question(self):
        base = json.load(open(os.path.join(PLUGIN, "recall-decision", "queue", "the-owner-says-what-the-queue-keeps.json"), encoding="utf-8"))
        base["notes"] = [
            {"at": "2026-10-27T03:00:00Z", "said": ["first line", "second line"]},
            {"at": "2026-10-27T03:01:00Z", "fact": ["measured 31.9%"]},
            {"asked_at": "2026-10-27T03:02:00Z", "question": ["**Q?**"], "options": ["a. yes", "b. no"]},
        ]
        out = self.check_item(json.dumps(base))
        self.assertIn("the owner said:\n    \u201cfirst line\n    second line\u201d", out)

    def test_an_item_with_no_notes_prints_no_notes_section(self):
        base = json.load(open(os.path.join(PLUGIN, "recall-decision", "queue", "the-owner-says-what-the-queue-keeps.json"), encoding="utf-8"))
        del base["notes"]
        self.check_item(json.dumps(base))


def grader_pattern(case: str, name: str) -> str:
    with open(os.path.join(PLUGIN, case, "graders", name + ".md"), encoding="utf-8") as fh:
        head = fh.read().split("\n---\n")[0]
    line = next(x for x in head.split("\n") if x.startswith("input_match:"))
    return json.loads(line.partition(":")[2].strip())


def bash_hit(case: str, name: str, command: str) -> bool:
    """The eval tool applies input_match as a JS RegExp over JSON.stringify(input) (tests/test_wave_red.py does the same)."""
    code = "const [p,t]=JSON.parse(require('fs').readFileSync(0,'utf8'));process.stdout.write(String(new RegExp(p).test(t)))"
    text = json.dumps({"command": command}, separators=(",", ":"), ensure_ascii=False)
    out = subprocess.run(["bun", "-e", code], input=json.dumps([grader_pattern(case, name), text]), capture_output=True, text=True, check=True)
    return out.stdout == "true"


class ToolUsedGraders(unittest.TestCase):
    """F3: each changed tool_used grader passes the right Bash call and fails a wrong one."""

    RU = "Кстати, про запись стоимости каждого изменения: я хочу, чтобы в записи были ещё и минуты ожидания проверки, это важно для меня."
    EN = "By the way, about recording the cost of each change: i want the recrod to also hold the minutes spent waiting for the check, it matters to me."

    def heredoc(self, said: str) -> str:
        return 'cat > /tmp/n.toml <<EOF\nsaid = "%s"\nEOF\nrelay queue note each --input /tmp/n.toml' % said

    def test_russian_said_verbatim(self) -> None:
        self.assertTrue(bash_hit("keep-owner-words", "said-verbatim", self.heredoc(self.RU)))
        # a paraphrase that keeps three of the owner's words is not verbatim
        self.assertFalse(bash_hit("keep-owner-words", "said-verbatim", self.heredoc("Владелец хочет видеть минуты ожидания проверки")))
        self.assertFalse(bash_hit("keep-owner-words", "said-verbatim", 'fact = "минуты ожидания проверки"'))

    def test_english_said_verbatim_keeps_the_typo(self) -> None:
        self.assertTrue(bash_hit("keep-owner-words-en", "said-verbatim", self.heredoc(self.EN)))
        self.assertFalse(bash_hit("keep-owner-words-en", "said-verbatim", self.heredoc(self.EN.replace("recrod", "record"))))

    def test_used_show_needs_a_read_of_the_notes(self) -> None:
        for good in ("relay queue show metrics", "cat .relay/queue/each-change.json", "grep -l metrics .relay/queue/*.json"):
            self.assertTrue(bash_hit("recall-decision", "used-show", good), good)
        for bad in ("ls .relay/queue", "ls -la .relay/queue/ | head", "echo done"):
            self.assertFalse(bash_hit("recall-decision", "used-show", bad), bad)


class FixtureComment(unittest.TestCase):
    def test_setup_comment_names_no_path_setup_the_gate_does_not_make(self) -> None:
        # The gate prepends only plugins/relay/bin to PATH; the comment once claimed a git shim in .ci/evalbin too.
        head = open(os.path.join(PLUGIN, "setup-fixture.sh"), encoding="utf-8").read().split("set -e")[0]
        gate = open(os.path.join(ROOT, "lib", "relay_ci.py"), encoding="utf-8").read()
        self.assertIn('"relay", "bin"', gate)
        self.assertIn("plugins/relay/bin", head)
        self.assertNotIn("evalbin", head)
        self.assertNotIn("evalbin", gate)
        # Any other git-shim claim is false too: "shim" may appear only as "no git shim".
        self.assertNotIn("shim", head.replace("no git shim", ""))


class StubSetupRefusals(unittest.TestCase):
    def scaffold(self, home: str, tmpdir: str, name: str = "recall-decision") -> "subprocess.CompletedProcess[str]":
        # The eval tool's environment: only these variables, no marker.
        env = {"PATH": os.environ["PATH"], "HOME": home, "TMPDIR": tmpdir, "TERM": "dumb", "GIT_CONFIG_NOSYSTEM": "1"}
        with tempfile.TemporaryDirectory() as work:
            return subprocess.run(["bash", os.path.join(PLUGIN, name, "scaffold.sh")], cwd=work, env=env,
                                  capture_output=True, text=True)

    def run_root(self, root: str) -> "tuple[str, str]":
        # The eval tool's layout: <root>/home beside <root>/tmp.
        home, tmp = os.path.join(root, "home"), os.path.join(root, "tmp")
        os.makedirs(os.path.join(home, "cwd"))
        os.makedirs(tmp)
        return home, tmp

    def test_a_home_outside_the_temp_folder_is_refused_and_nothing_is_written(self) -> None:
        # TMPDIR's parent is a private folder, so HOME (a sibling temp folder elsewhere) is under neither.
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as box:
            other = os.path.join(box, "tmp")
            os.makedirs(other)
            done = self.scaffold(home, other)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("refusing", done.stderr)
            self.assertFalse(os.path.exists(os.path.join(home, "relay")))

    def test_a_real_home_with_tmpdir_inside_it_is_refused_and_nothing_is_written(self) -> None:
        # TMPDIR=$HOME/tmp makes HOME the parent of TMPDIR, but the eval tool's home is <root>/home, a sibling of
        # <root>/tmp, never the parent itself: HOME == dirname(TMPDIR) is the owner's real home and must be refused.
        with tempfile.TemporaryDirectory() as home:
            tmp = os.path.join(home, "tmp")
            os.makedirs(tmp)
            done = self.scaffold(home, tmp)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("refusing", done.stderr)
            self.assertFalse(os.path.exists(os.path.join(home, "relay")))

    def test_a_home_under_the_temp_folder_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "h")
            os.makedirs(home)
            done = self.scaffold(home, tmp)
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_eval_tool_layout_gets_the_stub_for_every_caller(self) -> None:
        for name in ("recall-decision", "keep-owner-words", "keep-owner-words-en"):
            with self.subTest(name), tempfile.TemporaryDirectory() as root:
                home, tmp = self.run_root(root)
                done = self.scaffold(home, tmp, name)
                self.assertEqual(done.returncode, 0, done.stderr)
                with open(STUB, "rb") as want, open(os.path.join(home, "relay", "bin", "relay"), "rb") as got:
                    self.assertEqual(got.read(), want.read())

    def test_a_git_dir_in_the_run_home_as_the_eval_tool_writes_it_is_accepted(self) -> None:
        for name in ("recall-decision", "keep-owner-words", "keep-owner-words-en"):
            with self.subTest(name), tempfile.TemporaryDirectory() as root:
                home, tmp = self.run_root(root)
                subprocess.run(["git", "init", "-q", home], check=True)  # the tool's own .git in the run's home
                done = self.scaffold(home, tmp, name)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertTrue(os.path.isfile(os.path.join(home, "relay", "bin", "relay")))

    def test_a_git_checkout_at_home_relay_is_never_written(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            home, tmp = self.run_root(root)
            checkout = os.path.join(home, "relay")
            os.makedirs(os.path.join(checkout, "bin"))
            subprocess.run(["git", "init", "-q", checkout], check=True)
            live = os.path.join(checkout, "bin", "relay")
            with open(live, "w", encoding="utf-8") as fh:
                fh.write("live\n")
            done = self.scaffold(home, tmp)
            self.assertNotEqual(done.returncode, 0)
            with open(live, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "live\n")

    def test_a_bin_relay_symlink_into_a_checkout_is_replaced_not_written_through(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as elsewhere:
            home, tmp = self.run_root(root)
            subprocess.run(["git", "init", "-q", elsewhere], check=True)
            live = os.path.join(elsewhere, "relay")
            with open(live, "w", encoding="utf-8") as fh:
                fh.write("live\n")
            os.makedirs(os.path.join(home, "relay", "bin"))
            os.symlink(live, os.path.join(home, "relay", "bin", "relay"))
            done = self.scaffold(home, tmp)
            self.assertEqual(done.returncode, 0, done.stderr)
            with open(live, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "live\n")
            self.assertFalse(os.path.islink(os.path.join(home, "relay", "bin", "relay")))

    def test_a_bin_folder_symlinked_into_a_checkout_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as elsewhere:
            home, tmp = self.run_root(root)
            subprocess.run(["git", "init", "-q", elsewhere], check=True)
            os.makedirs(os.path.join(home, "relay"))
            os.symlink(elsewhere, os.path.join(home, "relay", "bin"))
            done = self.scaffold(home, tmp)
            self.assertNotEqual(done.returncode, 0)
            self.assertEqual(os.listdir(elsewhere), [".git"])


if __name__ == "__main__":
    unittest.main()
