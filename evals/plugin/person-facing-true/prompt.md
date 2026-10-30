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
Branch wt/merge-screen, one commit, one file: plugins/front/skills/front/SKILL.md.
The section "The merge question" is rewritten. Before: the screen opened with the branch name and a list of file names. After: it opens with a bold title in plain words, then a two-line intro saying what the change does for the owner, then lettered options with the recommendation first. Nothing else changes.

Reply with exactly one line, `person_facing: true` or `person_facing: false`, and nothing else.
