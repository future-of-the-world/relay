---
type: llm
focus: {source: file, path: judged/08.txt}
---
The agent reviewed OpenSpec change add-saved-shelf. Reference facts:
- specs/shelf/spec.md lines 15-18, scenario "Corrupt data": THEN "the shelf is empty and
  the file is left as it is".
- design.md lines 11-13, D2 "A corrupt file": "A file that is not valid JSON is moved aside
  to `shelf.json.bad` and a fresh empty file is written".
These contradict each other: the spec leaves a corrupt file in place; the design moves it
aside and writes a new one. A build cannot satisfy both.
Question: does the output report this contradiction, between the spec's "Corrupt data"
scenario and design D2, about what happens to a corrupt file?
PASS if it does, in any wording ("contradicts", "conflicts", "vs", "against", "the spec
says ... but D2 ..."). FAIL if it says the two agree, reports only a different
contradiction or problem, or names both places without saying they disagree.
