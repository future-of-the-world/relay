# Task flows and spec steps

Relay has one change cycle for any change: queue item, worktree, brief, build,
gate, review, fix, gate again, check, take the default branch, merge (the
delegate skill, "Review loop"). Two plugin slots hang off it:

- **work** (`"slot": "work"`): where the work comes from. No work flow ships today;
  the slot stays, a project's `[flow] kind` is `"none"`, and a new flow is a plugin with a `flow.json` (below).
- **specs** (`"slot": "specs"`): extra steps about the spec, never about
  building. A project turns them on with `[specs] method = "openspec"` (default
  `none`). OpenSpec only wraps the project's documentation; a new way of
  writing specs would be added as another plugin beside `openspec`.

## Binding

`.claude/kit.toml`:

```toml
[flow]
kind = "none"          # no work flow ships today

[specs]
method = "openspec"    # or "none" (the default)
```

`relay setup <dir> --specs openspec` (or `--specs none`) writes the setting,
enables or removes the plugin in `.claude/settings.json`, installs or
uninstalls it at project scope and runs `relay sync` for the project. The
`openspec/` folder is never touched. A project found with an `openspec/`
folder and no `[specs]` setting gets the steps on, and setup says so in one
line; turning them off is explicit.

The spec method answers for itself: the openspec plugin's hook
(`plugins/openspec/hooks/spec-rule.py`) reads `[specs] method` and speaks only
where the plugin is loaded and the method is `"openspec"`; nothing is stored
twice and `relay sync` writes no spec rule. At SessionStart and SubagentStart it
gives the main session and every agent it starts the rule
(`plugins/openspec/rules/openspec.md`) followed by the table "Spec steps in the
change cycle", rendered from the plugin's `flow.json` `steps`. On every prompt
that starts with an `/opsx:*` trigger it adds one line: load the stage's skill
and follow it, or, for a stage with only a `note`, the note.
`relay doctor <dir>` names drift between the setting and
`.claude/settings.json`, an unknown method, a stored spec rule in
`projects.toml`, and old forms left over from the plugin's earlier name.

The core plugin's stage hook binds `[flow] kind` only. When a prompt starts with
a trigger of that manifest (`/issue 42`, ...), it adds the same kind of line.

## The manifest: `plugins/<name>/flow.json`

```json
{
  "kind": "openspec",
  "slot": "specs",
  "description": "...",
  "detect": { "dirs": ["openspec"] },
  "requires_plugins": ["core", "openspec"],
  "bindings_required": ["project.default_branch", "gate.check", ...],
  "steps": [ { "at": "before 1", "does": "write the spec", "skill": "openspec:plan" }, ... ],
  "stages": [ { "name": "plan", "skill": "openspec:plan", "triggers": ["/opsx:propose"] },
              { "name": "apply", "triggers": ["/opsx:apply"], "note": "Build it as step 2 ..." } ]
}
```

- `slot`: `work` or `specs`. A spec method has no `roles` for build or fix:
  building and fixing are the cycle's `delegate:worker` and `delegate:fixer`.
- `steps` (spec methods): each entry names the step of the change cycle it
  hooks into (`before 1`, `1`, `2`, `4`, `5`, `after 7`, ...), what it does, and
  its skill or agent. `relay sync` renders them into the project's rules.
- `stages[].triggers`: the first word of the prompt, exact or followed by
  `:` (`/opsx:apply` matches `/opsx:apply`; `/issue` matches `/issue`).
- `roles` (work flows): which agent plays each tier.
- `detect`: what `relay setup` looks for to propose this plugin.

## Shipped

**openspec** (`plugins/openspec`, slot specs): `openspec:plan` before step 1,
`openspec:spec-review` at step 1 (it takes the place of the design review),
`kit packet <change> <group>` as each group's brief at step 2,
`openspec:spec-conformance` as one more judge at step 4, `openspec:author`
for a Gap whose cause is the spec at step 5, `openspec:archive` after step 7.

## Writing a flow

1. `plugins/<name>/.claude-plugin/plugin.json`, `flow.json` (with its `slot`), and one skill
   per stage under `skills/<stage>/SKILL.md`. A stage skill says who runs
   (always a typed agent, never the main session), what it reads, what it
   writes, and what it tells the owner.
2. Add the plugin to `.claude-plugin/marketplace.json`.
3. `relay flows` lists it; a project binds a work flow with `[flow] kind` and a spec method with `[specs] method`.
4. A bench scenario for its first stage, so a change to the skill is
   measured.

Nothing in `lib/` or the hooks changes.
