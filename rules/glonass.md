# Glonass work sources
> No Claude attribution in anything that goes to a Glonass system (gitlab.aoglonass.ru, the Glonass Tracker, glonass_* tools).

- No Claude attribution in anything that goes to a Glonass system:
  repositories on `gitlab.aoglonass.ru`, the Glonass Yandex Tracker (issues,
  comments, wiki), and anything else reached through the `glonass_*` tools.
  This overrides the attribution Claude Code adds by default.
  - Commit messages: no `Co-Authored-By: Claude ...` trailer, no
    `Claude-Session:` trailer, no "Generated with Claude Code" line.
  - Merge request titles and descriptions, Tracker issues and comments: no
    "🤖 Generated with [Claude Code](...)" footer and no other Claude or
    Anthropic credit or link.
  - Pass this rule on to any subagent that commits or posts there.
  - Claude as subject matter is fine (a `CLAUDE.md` file named in a change
    list, for example); only authorship credit is banned.

