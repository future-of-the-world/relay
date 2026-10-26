---
type: llm
focus: {source: file, path: judged/04.txt}
---
The owner's native language is Russian. Two questions about the reply.
1. Gender: an English IT noun (branch, commit, hook, merge, gate, ... any English IT noun) takes the masculine gender every
time it is used with an adjective or a verb ("в отдельном branch", "основной branch сдвинулся"). FAIL if the same reply
uses a feminine or neuter form for one ("в отдельной branch", "эта branch") or mixes genders for the same term. A Russian
gloss beside the term does not change this: in "Gate, то есть полная проверка, тоже зелёная" the subject is gate, so the
feminine "зелёная" (which agrees with the gloss "проверка") is a feminine form of the term: FAIL; "gate ... тоже прошёл"
or "тоже зелёный" is right. A pronoun that points at the Russian gloss ("hook, то есть автоматическая проверка, и она
прошла") is not a breach: only a verb or an adjective that agrees with the term itself counts.
2. Opener: the reply must start with the substance. FAIL if its first sentence is a remark that the project, its name
or its purpose was not named or is unknown ("название и назначение в сообщении не прозвучали", "проект не назван").
PASS only if both hold.
