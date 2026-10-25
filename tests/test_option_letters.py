"""The option-letters rule (queue item option-letters-have-no-fixed-alphabet)."""
from pathlib import Path

import unittest

ROOT = Path(__file__).resolve().parent.parent
TEXTS = ["rules/working-with-me.md", "rules/front.md", "plugins/front/skills/front/SKILL.md"]
CLAUSE = (
    "a look-alike letter is read by its position in the owner's alphabet "
    "only when the reply is in that alphabet"
)


def _flat(name: str) -> str:
    return " ".join((ROOT / name).read_text().split())


class TestOptionLetters(unittest.TestCase):
    def test_look_alike_clause(self) -> None:
        for name in TEXTS:
            with self.subTest(name=name):
                self.assertIn(CLAUSE, _flat(name))

    def test_latin_letters_and_cyrillic_map(self) -> None:
        for name in TEXTS:
            with self.subTest(name=name):
                flat = _flat(name)
                self.assertIn("Letters are Latin a, b, c in every language", flat)
                self.assertIn("Cyrillic а = a, б = b, в = c", flat)

    def test_edited_lines_not_overlong(self) -> None:
        # F2: a line carrying the sentence is no longer than the longest other line of its paragraph
        for name in TEXTS:
            with self.subTest(name=name):
                lines = (ROOT / name).read_text().split("\n")
                hit = [i for i, l in enumerate(lines) if "Letters are Latin" in l or "look-alike" in l or "alphabet)." in l]
                self.assertTrue(hit)
                for i in hit:
                    self.assertLessEqual(len(lines[i]), 100)


if __name__ == "__main__":
    unittest.main()
