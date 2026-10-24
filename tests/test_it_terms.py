"""English IT terms inside a reply in the owner's language do not count against it (the reply-language Stop hook)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "plugins", "front", "hooks", "reply_language.py")

# Cyrillic letters in the prose: 'Основная ветка сдвинулась' etc. The Latin runs are 1 to 3 words next to Russian
# words, so they are IT terms: merge train, paid eval run, hook. Counting every Latin letter, about 18 of 50 letters are Latin, so the share falls under 60%; without them it is 100%.
TERMY = ("Мы сделали merge, и fast-forward прошёл: основной branch сдвинулся, hook не сработал. "
         "Дальше paid eval run, потом merge train.")
# A real English reply keeps blocking: the Latin run is a whole clause, longer than three words.
ENGLISH = ("Done. The workflow finished and the change is complete. I merged the branch into the default "
           "branch, the gate is green and the paid run cost nine dollars. Next I will start the next item.")
# English clause with one Russian word next to it: still not an IT term run.
ENGLISH_WITH_ONE_RUSSIAN_WORD = ENGLISH + " Готово."


class ItTerms(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        os.makedirs(os.path.join(self.home.name, ".claude"))
        with open(os.path.join(self.home.name, ".claude", "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("My native language: Russian.\n")

    def run_hook(self, reply):
        drop = ("RELAY_REPLY_LANG_SHARE", "CLAUDE_CODE_ENTRYPOINT", "RELAY_BENCH", "CLAUDE_CONFIG_DIR")
        env = {k: v for k, v in os.environ.items() if k not in drop}
        env["HOME"] = self.home.name
        done = subprocess.run([sys.executable, HOOK], input=json.dumps({"last_assistant_message": reply}),
                              capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def test_q1_russian_reply_full_of_english_it_terms_is_not_refused(self):
        self.assertIsNone(self.run_hook(TERMY))

    def test_q1_a_reply_really_in_english_is_still_refused(self):
        self.assertEqual(self.run_hook(ENGLISH)["decision"], "block")
        self.assertEqual(self.run_hook(ENGLISH_WITH_ONE_RUSSIAN_WORD)["decision"], "block")

    def test_q1_rule_text_keeps_it_terms_in_english_and_internal_names_out(self):
        with open(os.path.join(ROOT, "rules", "working-with-me.md"), encoding="utf-8") as f:
            text = " ".join(f.read().split())
        self.assertIn("Standard IT terms stay in their English form", text)
        self.assertIn("relay's own names (branches, files, slugs, commands) stay out of replies", text)
        self.assertIn("one-line definition the first time", text)


if __name__ == "__main__":
    unittest.main()
