# Product work: what a person sees
> A person-facing change is shown live in the real medium, starts from the leading apps, uses plain language, and is checked by the owner before merge.

A change is person-facing when it alters what a person sees or does:
screens, messages, wording, flows, defaults, notifications. Everything else
(engines, storage, jobs, libraries, tool internals) is engineering.

- Engineering is mine within your principles. A person-facing change is
  shown live, never settled alone and never asked as abstract text. A
  rejected text form means: show it live instead, not: decide it for me.
- Shape before plan: each question is a live example in the product's real
  medium (the app on the device, the message in the real chat, the rendered
  page), look only, throwaway, made in 10 minutes at most; bigger means the
  question is too big. Play the whole journey once and get "lock it";
  record locked decisions in the change's design.md, quoted exactly by the
  specs.
- Modern apps are the starting point. I am sensitive to UX and expect what
  today's popular apps in the same domain give people. Before shaping a
  screen, message or flow, look at how two or three leading apps of that
  kind do it, and start from the best of them, not from scratch or from
  what is easiest to build. Show each sample next to its reference: which
  app, what it does, and where yours differs and why. I then correct it,
  and my corrections win over the reference. The project lists its
  reference apps under "Product surface".
- Plain language for users: nothing a person sees holds internal terms
  (scores, weights, tokens, model or tool names, HTTP codes, ids, raw
  errors); diagnostics go to logs or an owner-only view.
- Before handing over, I check it myself in the real medium; then the
  project's own look check runs, and you walk it. No merge until what you
  found is fixed.
- Shape one journey at a time; engineering may run in parallel.
- A project names its real medium, its preview tool, its look check and its
  reference apps in its own CLAUDE.md ("Product surface"). A project with no person-facing
  surface says so, and then only the plain-words rule applies, to operator
  replies, status and tool descriptions.

