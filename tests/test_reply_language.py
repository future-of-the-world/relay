"""The Stop hook of the front plugin: a reply to the owner in the wrong language is blocked once."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "plugins", "front", "hooks", "reply_language.py")

# Shaped like the front's two replies of 24 Oct 2026 (session 3207dc59): English report, then the Russian one.
ENGLISH = ("Done. The workflow finished and OpenSpec shows the change as complete. I merged the branch into "
           "the default branch, the gate is green and the paid run cost $9. Details are in "
           "/private/tmp/claude-501/scratchpad/reports/final.md and https://example.com/run/42.\n"
           "```\nbin/ci --quick\n```\nNext I will start the next item from the queue.")
RUSSIAN = ("Готово. Workflow завершился, а OpenSpec показывает изменение как выполненное. Ветку я влил в "
           "основную, проверка зелёная, платный прогон стоил $9. Подробности лежат в "
           "/private/tmp/claude-501/scratchpad/reports/final.md и на https://example.com/run/42.\n"
           "```\nbin/ci --quick\n```\nДальше возьму следующий пункт из очереди, `relay queue` его покажет.")
MOSTLY_CODE = "See `relay queue` and /Users/amidman/relay/.relay/queue/some-item.json now.\n```\nbin/ci --quick --all\n```"


class ReplyLanguage(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)

    def claude_md(self, line):
        os.makedirs(os.path.join(self.home.name, ".claude"), exist_ok=True)
        with open(os.path.join(self.home.name, ".claude", "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("# Defaults\n\n" + line + "\n\nOther text.\n")

    def run_hook(self, reply, env_extra=None, **extra):
        drop = ("RELAY_REPLY_LANG_SHARE", "CLAUDE_CODE_ENTRYPOINT", "RELAY_BENCH", "CLAUDE_CONFIG_DIR")
        env = {k: v for k, v in os.environ.items() if k not in drop}
        env["HOME"] = self.home.name
        env.update(env_extra or {})
        done = subprocess.run([sys.executable, HOOK], input=json.dumps(dict(last_assistant_message=reply, **extra)),
                              capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def test_english_reply_is_blocked_once_with_rewrite_request(self):
        self.claude_md("My native language: Russian.")
        out = self.run_hook(ENGLISH)
        # the prose has 0 Cyrillic letters out of well over 40: share 0% is under 60%
        self.assertEqual(out["decision"], "block")
        self.assertIn("Rewrite the reply in Russian", out["reason"])
        self.assertIn("code, paths and names stay as they are", out["reason"])

    def test_russian_reply_with_english_terms_passes(self):
        self.claude_md("My native language: Russian.")
        self.assertIsNone(self.run_hook(RUSSIAN))

    def test_reply_that_is_mostly_code_or_paths_passes(self):
        self.claude_md("My native language: Russian.")
        self.assertIsNone(self.run_hook(MOSTLY_CODE))

    def test_unset_or_latin_language_checks_nothing(self):
        self.assertIsNone(self.run_hook(ENGLISH))       # no CLAUDE.md at all
        self.claude_md("My native language: English.")
        self.assertIsNone(self.run_hook(ENGLISH))
        self.claude_md("Some other line.")
        self.assertIsNone(self.run_hook(ENGLISH))

    def test_second_stop_after_a_block_is_let_through(self):
        self.claude_md("My native language: Russian.")
        self.assertIsNone(self.run_hook(ENGLISH, stop_hook_active=True))

    def test_agent_stop_is_not_checked(self):
        self.claude_md("My native language: Russian.")
        self.assertIsNone(self.run_hook(ENGLISH, agent_id="a1"))
        self.assertEqual(self.run_hook(ENGLISH)["decision"], "block")

    def test_program_started_sessions_are_not_checked(self):
        self.claude_md("My native language: Russian.")
        self.assertIsNone(self.run_hook(ENGLISH, env_extra={"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}))
        self.assertIsNone(self.run_hook(ENGLISH, env_extra={"RELAY_BENCH": "1"}))
        self.assertEqual(self.run_hook(ENGLISH, env_extra={"CLAUDE_CODE_ENTRYPOINT": "cli"})["decision"], "block")
        self.assertIsNone(self.run_hook(RUSSIAN, env_extra={"CLAUDE_CODE_ENTRYPOINT": "cli"}))

    def test_language_is_read_from_claude_config_dir(self):
        self.claude_md("My native language: Russian.")
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        self.assertIsNone(self.run_hook(ENGLISH, env_extra={"CLAUDE_CONFIG_DIR": empty.name}))
        with open(os.path.join(empty.name, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("My native language: Russian.\n")
        self.assertEqual(self.run_hook(ENGLISH, env_extra={"CLAUDE_CONFIG_DIR": empty.name})["decision"], "block")
        self.assertEqual(self.run_hook(ENGLISH)["decision"], "block")   # unset: HOME/.claude

    def test_share_setting_percent_and_garbage(self):
        self.claude_md("My native language: Russian.")
        # 60 means 60 percent: the Russian fixture (about 97%) passes
        self.assertIsNone(self.run_hook(RUSSIAN, env_extra={"RELAY_REPLY_LANG_SHARE": "60"}))
        self.assertEqual(self.run_hook(ENGLISH, env_extra={"RELAY_REPLY_LANG_SHARE": "0.6"})["decision"], "block")
        # not a number: the default 0.60 applies, so English is still blocked
        self.assertEqual(self.run_hook(ENGLISH, env_extra={"RELAY_REPLY_LANG_SHARE": "abc"})["decision"], "block")

    def test_block_reason_counts_letters_not_words(self):
        self.claude_md("My native language: Russian.")
        reason = self.run_hook(ENGLISH)["reason"]
        self.assertIn("of its letters", reason)
        self.assertNotIn("words", reason)

    def test_tilde_fence_is_removed_like_backtick_fence(self):
        self.claude_md("My native language: Russian.")
        # 60+ Russian letters; the English log has 200 letters. Only the prose counts: 100%
        ru = "Это сообщение написано по русски и содержит достаточно букв для проверки доли."
        log = "error " * 40
        self.assertIsNone(self.run_hook(ru + "\n~~~\n" + log + "\n~~~\n"))
        self.assertIsNone(self.run_hook(ru + "\n```\n" + log + "\n```\n"))

    def test_threshold_is_a_share_not_every_character(self):
        self.claude_md("My native language: Russian.")
        # 45 Russian letters + 20 English letters: 69% is over 60%, so it passes despite the English words
        mixed = "Это сообщение написано по русски и содержит слова " + "x" * 5 + " " + "y" * 15
        letters = [c for c in mixed if c.isalpha()]
        self.assertGreater(sum(c > "Ѐ" for c in letters) / len(letters), 0.6)
        self.assertIsNone(self.run_hook(mixed))

    def test_reply_is_read_from_the_transcript_when_not_in_the_input(self):
        self.claude_md("My native language: Russian.")
        path = os.path.join(self.home.name, "t.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": RUSSIAN}]}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": ENGLISH}]}}) + "\n")
        drop = ("RELAY_REPLY_LANG_SHARE", "CLAUDE_CODE_ENTRYPOINT", "RELAY_BENCH", "CLAUDE_CONFIG_DIR")
        env = dict({k: v for k, v in os.environ.items() if k not in drop}, HOME=self.home.name)
        done = subprocess.run([sys.executable, HOOK], input=json.dumps({"transcript_path": path}), capture_output=True, text=True, env=env)
        self.assertEqual(json.loads(done.stdout)["decision"], "block")


if __name__ == "__main__":
    unittest.main()
