# Secrets
> Never print a secret: no shell tracing, verbose authenticated requests or environment dumps; report any exposure at once.

- Never print a secret, including while debugging: no `set -x` / `bash -x`,
  no `curl -v` / `--trace` on authenticated requests, no `env` / `printenv`.
  API keys live in my shell environment, so a trace prints them. If one does
  reach output, tell me at once so I can rotate it.

