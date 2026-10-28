"""Texts still telling the front to number questions (review of no-numbers, F1-F4)."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text()


def flat(text: str) -> str:
    return " ".join(text.split())


def test_f1_spec_review_questions_have_bold_title_no_number() -> None:
    text = flat(read("plugins", "openspec", "skills", "spec-review", "SKILL.md"))
    assert "numbered questions" not in text
    assert "bold title" in text and "no number" in text
    assert "lettered options, your recommendation first, the difference made visible" in text


def test_f1_no_numbered_questions_anywhere_in_rule_texts() -> None:
    out = subprocess.run(["git", "grep", "-n", "-i", "numbered questions", "--", "rules", "roles", "plugins"],
                         cwd=ROOT, capture_output=True, text=True).stdout
    assert out == ""


def test_f2_queue_rule_note_keys_have_no_number() -> None:
    text = flat(read("rules", "queue.md"))
    assert "`options`, `number`" not in text
    assert "`question`, `options`" in text
    assert "`answer`" in text and "`reading`" in text and "`to`" in text


def test_f3_descriptions_say_lettered_choices() -> None:
    assert "numbered choices" not in flat(read("README.md"))
    market = json.loads(read(".claude-plugin", "marketplace.json"))
    front = next(p for p in market["plugins"] if p["name"] == "front")
    assert "lettered choices" in front["description"]
    assert "numbered" not in front["description"]


def test_f4_front_skill_says_questions_of_one_reply_get_own_at() -> None:
    text = flat(read("plugins", "front", "skills", "front", "SKILL.md"))
    assert "one second apart" in text
