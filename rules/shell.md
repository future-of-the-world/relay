# Shell
> zsh: never a variable named path; variables from ~/.zshrc need zsh -ic.

- My shell is zsh. Never name a variable `path` (it is tied to `$PATH`).
  Variables set only in `~/.zshrc` need `zsh -ic '...'` in non-interactive
  commands.

