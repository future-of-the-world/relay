---
type: llm
focus: {source: file, path: judged/07.txt}
---
The owner's native language is Russian. Two questions about the reply.
1. Gender: an English IT noun (branch, commit, hook, merge) takes the masculine gender every time it is used with an
adjective or a verb ("в отдельном branch", "основной branch сдвинулся"). FAIL if the same reply uses a feminine or
neuter form for one ("в отдельной branch", "эта branch") or mixes genders for the same term.
2. Opener: the reply must start with the substance. FAIL if its first sentence is a remark that the project, its name
or its purpose was not named or is unknown ("название и назначение в сообщении не прозвучали", "проект не назван").
PASS only if both hold.
