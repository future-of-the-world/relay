# Task flows

A flow is how a piece of work moves: for OpenSpec, propose → spec review →
apply → apply review → archive; for issues, pick → implement → review →
merge. Relay does not hard-code either. A flow is a plugin that ships a
manifest, and a project binds one.

## Binding

`.claude/kit.toml`:

```toml
[flow]
kind = "openspec"      # or "issues", or "none"
# plugin = "sdd"       # only when the plugin's name differs from the kind (openspec -> sdd is known)
```

The core plugin's stage hook reads it on every prompt. When a prompt starts
with a trigger of the bound flow, the hook adds one line: load this stage's
skill first. `relay doctor <dir>` checks the flow's required bindings and
plugins.

## The manifest: `plugins/<name>/flow.json`

```json
{
  "kind": "issues",
  "plugin": "issues",
  "description": "...",
  "detect": { "dirs": ["openspec"] } | { "any_bindings": ["issues.view"] },
  "requires_plugins": ["core", "issues", "delegate"],
  "bindings_required": ["project.default_branch", "gate.check", "issues.view", ...],
  "stages": [ { "name": "pick", "skill": "issues:pick", "triggers": ["/issue", "/issues:pick"] }, ... ],
  "roles": { "build": "delegate:worker", "fix": "delegate:fixer", "think": "delegate:thinker", "judge": "delegate:critic" }
}
```

- `stages[].triggers`: the first word of the prompt, exact or followed by
  `:` (`/opsx:apply` matches `/opsx:apply`; `/issue` matches `/issue`).
- `roles`: which agent plays each tier in this flow. The OpenSpec flow
  keeps its own agents (`sdd:worker` knows `kit packet`); the issue flow
  uses the delegate agents.
- `detect`: what `relay setup` looks for to propose this flow.

## Shipped flows

**openspec** (`plugins/sdd`): the stage skills and agents from principles,
unchanged, plus the manifest. The sdd plugin no longer carries its own stage
hook; core's does the job for every flow.

**issues** (`plugins/issues`), from Arsenal's executed flow: an issue is
`.issues/<slug>/description.md` committed on branch `<slug>` in
`.worktrees/<slug>`, plus a tracker issue, plus one pull request,
squash-merged with `Closes: #<n>` on the final commit; no status field (git
state is the truth); `decisions.md` beside discussion-born issues; the
reality review before implementing; every remaining worktree rebased after
a merge. Four skills: `issues:read` (a scout), `issues:create` (thinker
drafts, critic checks faithfulness and secrets, runner creates; report
after, never a question before), `issues:implement`, `issues:merge`.

Stages fire on slash triggers or on keywords in the prompt, as Arsenal's
hook did: `#123`, "do / continue / finish ... issue", "create an issue",
"which issues", "PR / merge / rebase".

The tracker and hosting are commands in `[issues]` (Forgejo's `tea` in the
template; GitHub `gh`, GitLab `glab`, Yandex Tracker through the
`glonass_*` tools, all run by a runner):

| key | placeholders | Forgejo example |
|---|---|---|
| `create` | `{title}` `{body_file}` | `tea issue create --title "{title}" --description "$(cat {body_file})"` |
| `view` | `{n}` | `tea issue view {n} --comments` |
| `list` | | `tea issue list --state open` |
| `pr_create` | `{branch}` `{title}` `{body_file}` | `tea pr create --head {branch} ...` |
| `pr_status` | `{pr}` | `tea pr view {pr}` |
| `pr_merge` | `{pr}` | `tea pr merge {pr} --style squash --delete-branch` |
| `commit_ref` | `{n}` | `Closes: #{n}` |
| `attribution` | | `none` where no Claude credit may appear |

What stays project-only, in `.claude/kit/<stage>.md` additions: Arsenal's
Hard Rules text, its preflight script path, its OpenSpec "born archived"
procedure for feature-sized issues.

## Writing a flow

1. `plugins/<name>/.claude-plugin/plugin.json`, `flow.json`, and one skill
   per stage under `skills/<stage>/SKILL.md`. A stage skill says who runs
   (always a typed agent, never the main session), what it reads, what it
   writes, and what it tells the owner.
2. Add the plugin to `.claude-plugin/marketplace.json`.
3. `relay flows` lists it; a project binds it with `[flow] kind`.
4. A bench scenario for its first stage, so a change to the skill is
   measured.

Nothing in `lib/` or the hooks changes.
