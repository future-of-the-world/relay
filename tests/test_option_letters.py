"""The option-letters rule (queue item option-letters-have-no-fixed-alphabet)."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEXTS = ["rules/working-with-me.md", "rules/front.md", "plugins/front/skills/front/SKILL.md"]
CLAUSE = (
    "a look-alike letter is read by its position in the owner's alphabet "
    "only when the reply is in that alphabet"
)


def _flat(name: str) -> str:
    return " ".join((ROOT / name).read_text().split())


@pytest.mark.parametrize("name", TEXTS)
class TestOptionLetters:
    def test_look_alike_clause(self, name: str) -> None:
        assert CLAUSE in _flat(name)

    def test_latin_letters_and_cyrillic_map(self, name: str) -> None:
        flat = _flat(name)
        assert "Letters are Latin a, b, c in every language" in flat
        assert "Cyrillic а = a, б = b, в = c" in flat

    def test_edited_lines_not_overlong(self, name: str) -> None:
        # F2: a line carrying the sentence is no longer than the longest other line of its paragraph
        lines = (ROOT / name).read_text().split("\n")
        hit = [i for i, l in enumerate(lines) if "Letters are Latin" in l or "look-alike" in l or "alphabet)." in l]
        assert hit
        for i in hit:
            assert len(lines[i]) <= 100
