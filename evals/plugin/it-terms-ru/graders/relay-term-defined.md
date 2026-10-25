---
type: llm
---
The owner's native language is Russian. The question asked about relay's full local check before a merge, which
the project calls the "gate". The reply must keep "gate" in English and, because it is a term only relay uses,
give a one-line definition of it the first time it appears (what it checks, in plain Russian).
Question: does the reply use the word "gate" in English and define it in one line where it first appears?
PASS if "gate" appears in English with a short definition at first use. FAIL if "gate" is used with no
definition, or is replaced by a translation ("ворота", "шлюз") instead of the English term.
