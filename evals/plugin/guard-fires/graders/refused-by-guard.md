---
type: regex
pattern: "guard-main"
---
The core plugin's guard hook refuses a shell write in the main checkout and says so ("guard-main: ..."). If this case fails, plugin hooks do not run in `claude plugin eval`, and the other cases run unguarded.
