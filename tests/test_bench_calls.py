"""Library tests: tool_calls on transcripts shaped like Claude Code's real ones (blob lines, refused calls)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relay_testbase import Base  # noqa: E402


def use(ident, command, kind="assistant", name="Bash"):
    return {"type": kind, "message": {"content": [{"type": "tool_use", "id": ident, "name": name,
                                                   "input": {"command": command}}]}}


def result(ident, text, is_error):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": ident,
                                                     "is_error": is_error, "content": text}]}}


class BenchCalls(Base):
    def config(self, sid, entries):
        config = os.path.join(self.tmp, "cfg")
        proj = os.path.join(config, "projects", "-p")
        os.makedirs(proj)
        with open(os.path.join(proj, sid + ".jsonl"), "w") as handle:
            handle.write("".join(json.dumps(e) + "\n" for e in entries))
        return config

    def test_an_api_request_blob_line_does_not_double_a_call(self):
        import relay_bench as rb
        # one real call T1, repeated by a blob line with a hook's cd prefix: 1 call, so count 2 fails
        cfg = self.config("a", [use("T1", "python3 x.py"), use("T1", "cd /w && python3 x.py", kind="api-request-blob")])
        calls = rb.tool_calls("a", cfg)
        self.assertEqual(len(calls), 1)
        self.assertFalse(rb.tool_called({"input": "python3", "count": 2}, "a", calls)[0])
        self.assertTrue(rb.tool_called({"input": "python3", "count": 1}, "a", calls)[0])

    def test_two_distinct_calls_both_count(self):
        import relay_bench as rb
        cfg = self.config("b", [use("T1", "python3 a.py"), use("T2", "python3 b.py")])
        self.assertTrue(rb.tool_called({"input": "python3", "count": 2}, "b", rb.tool_calls("b", cfg))[0])

    def test_a_call_a_hook_refused_did_not_run_but_a_failed_one_did(self):
        import relay_bench as rb
        cfg = self.config("c", [
            use("T1", "python3 blocked.py"), result("T1", "PreToolUse:Bash hook error: blocked", True),
            use("T2", "python3 failed.py"), result("T2", "Exit code 1\nboom", True),
            use("T3", "python3 fine.py"), result("T3", "ok", False),
            use("T4", "python3 cut_off.py"),                       # no result yet: counted as attempted
        ])
        commands = [c for _, c in rb.tool_calls("c", cfg)]
        self.assertEqual(commands, ["python3 failed.py", "python3 fine.py", "python3 cut_off.py"])

    def test_a_refusal_in_list_content_is_read_too(self):
        import relay_bench as rb
        cfg = self.config("d", [use("T1", "ls"), result("T1", [{"type": "text", "text": "PreToolUse:Write hook error"}], True)])
        self.assertEqual(rb.tool_calls("d", cfg), [])

    def test_database_urls_and_passwords_are_redacted_whatever_the_name(self):
        import relay_bench as rb
        url = "postgres://u:s3cretpass@h/db"
        for name, value in (("FAKE_PG_DATASOURCE", url), ("FAKE_PLAIN_NAME", url), ("FAKE_SVC_LOGIN", "loginvalue123")):
            os.environ[name] = value
            self.addCleanup(os.environ.pop, name, None)
        cfg = self.config("e", [use("T1", f"psql {url}"), use("T2", "login loginvalue123")])
        text = " ".join(c for _, c in rb.tool_calls("e", cfg))
        self.assertNotIn("s3cretpass", text)
        self.assertNotIn("loginvalue123", text)

    def test_ordinary_values_are_not_redacted(self):
        import relay_bench as rb
        os.environ["FAKE_WORKDIR"] = "/Users/x/scratch"
        self.addCleanup(os.environ.pop, "FAKE_WORKDIR", None)
        cfg = self.config("f", [use("T1", "python3 /Users/x/scratch/s.py")])
        self.assertTrue(rb.tool_called({"input": "scratch"}, "f", rb.tool_calls("f", cfg))[0])

    def test_the_llm_grader_gets_the_tool_calls_without_secrets(self):
        import relay_bench as rb
        fake = "sk-fake-0123456789abcdef"
        os.environ["FAKE_X_API_KEY"] = fake
        self.addCleanup(os.environ.pop, "FAKE_X_API_KEY", None)
        cfg = self.config("g", [use("T1", f"python3 s.py {fake}")])
        prompt_file = os.path.join(self.tmp, "prompt.txt")
        fake_bin = os.path.join(self.tmp, "fakeclaude")
        with open(fake_bin, "w") as handle:
            handle.write(f"#!{sys.executable}\nimport sys, json\nopen({prompt_file!r}, 'w').write(sys.argv[2])\n"
                         "print(json.dumps({'result': 'PASS: ok'}))\n")
        os.chmod(fake_bin, 0o755)
        scen = {"graders": [{"name": "j", "type": "llm", "rubric": "r"}]}
        out = rb.grade(scen, self.tmp, "reply", fake_bin, "haiku", session_id="g", config_dir=cfg)
        self.assertTrue(out[0]["passed"])
        prompt = open(prompt_file).read()
        self.assertIn("- Bash: python3 s.py [redacted]", prompt)
        self.assertNotIn(fake, prompt)
        # no session id: no Tool calls section
        rb.grade(scen, self.tmp, "reply", fake_bin, "haiku", session_id=None, config_dir=cfg)
        self.assertNotIn("Tool calls", open(prompt_file).read())
