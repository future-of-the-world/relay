---
max_turns: 5
timeout_seconds: 300
runs: 3
model: haiku
allowed_tools: [Read]
---
A checker agent judges one field of a change before the change lands. Answer that field for the change below.

Field person_facing (boolean): true only when the change alters what the owner reads in the conversation: the merge question screen, the digest of a wave, or the reply rules the front follows (their wording, order or content). Example that is true: the wording of the merge question screen in the front skill is rewritten. Example that is false: a fixer's or a worker's instructions, a role text, a test, a lib function, a hook or a queue rule changes with no change to those screens. In a project whose product has screens or texts for people (an app), a change to what those people see is true as well. Judge the change as a whole, not one file.

The change:
Ветка wt/land-fix, два файла.
1. plugins/delegate/agents/fixer.md: в тексте роли fixr переписан абзац про отчёт (порядок пунктов, формулировки для агента).
2. lib/relay_land.py: в функции _landed исправлено вычисление номера строки в журнале. Тесты в tests/test_land.py добавлены.
Экраны и тексты, которые читает владелец, не менялись.

Reply with exactly one line, `person_facing: true` or `person_facing: false`, and nothing else.
