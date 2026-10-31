/** Offline compatibility probe, not a Pi extension. No model calls or live hooks.
 * Usage: bun evals/compat/pi-code.ts /path/to/unpacked/pi-code/package
 * Only import reviewed pi-code sources: importing third-party code executes it.
 */
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";

const source = path.resolve(process.argv[2] ?? "");
if (!process.argv[2]) throw new Error("Pass the unpacked, reviewed pi-code package directory.");
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "relay-pi-compat-"));
const home = path.join(scratch, "home");
const config = path.join(home, ".claude");
const project = path.join(scratch, "project");
const results: Array<{ check: string; result: string }> = [];

function fixture(file: string, value: unknown): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(value));
}

function run(program: string, args: string[], input?: unknown): string {
  const result = spawnSync(program, args, {
    cwd: project,
    env: process.env,
    encoding: "utf8",
    input: input === undefined ? undefined : JSON.stringify(input),
    timeout: 10_000,
  });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, `${program}: ${result.stderr}`);
  return result.stdout;
}

try {
  fs.mkdirSync(project, { recursive: true });
  process.env.HOME = home;
  process.env.CLAUDE_CONFIG_DIR = config;
  process.env.PI_CODING_AGENT_DIR = path.join(home, ".pi", "agent");
  process.env.CLAUDE_PROJECT_DIR = project;
  process.env.RELAY_ROOT = repo;
  process.env.RELAY_HOME = path.join(home, ".relay");
  // The probe must not inherit the owner's routing or registry overrides.
  for (const key of Object.keys(process.env)) {
    if (key.startsWith("RELAY_DELEGATE_") || ["RELAY_PROJECTS", "RELAY_CLAUDE_JSON"].includes(key)) delete process.env[key];
  }
  run("git", ["init", "--quiet", "--initial-branch=master"]);

  const importSource = (file: string): Promise<any> => import(pathToFileURL(path.join(source, file)).href);
  const { setManagedSettingsPath } = await importSource("extensions/internal/managed-settings.ts");
  setManagedSettingsPath(path.join(home, "managed-settings.json"));
  const { installedPlugins, resetInstalledPluginsCache } = await importSource("extensions/internal/plugins.ts");
  const { loadPluginHooks } = await importSource("extensions/hooks/config.ts");
  const { claudeToolInput } = await importSource("extensions/hooks/claude-tools.ts");
  const { findModel } = await importSource("extensions/internal/model-lookup.ts");

  fixture(path.join(config, "settings.json"), { enabledPlugins: { "relay@relay": true } });
  fixture(path.join(config, "plugins", "known_marketplaces.json"), {
    relay: { source: { source: "directory", path: repo }, installLocation: repo },
  });
  fixture(path.join(config, "plugins", "installed_plugins.json"), {
    version: 2,
    plugins: { "relay@relay": [{ scope: "user", installPath: path.join(repo, "plugins", "relay") }] },
  });
  assert.equal(installedPlugins(home).length, 0);
  results.push({ check: "directory marketplace", result: "Not discovered: pi-code scans its Claude cache layout, not Relay's source folders." });

  // A synthetic cache entry, not a change to the owner's actual Claude cache.
  const cached = path.join(config, "plugins", "cache", "relay", "relay", "probe");
  fs.mkdirSync(path.join(cached, "hooks"), { recursive: true });
  fs.mkdirSync(path.join(cached, ".claude-plugin"), { recursive: true });
  fs.copyFileSync(path.join(repo, "plugins/relay/.claude-plugin/plugin.json"), path.join(cached, ".claude-plugin/plugin.json"));
  fs.copyFileSync(path.join(repo, "plugins/relay/hooks/hooks.json"), path.join(cached, "hooks/hooks.json"));
  fixture(path.join(config, "plugins", "installed_plugins.json"), {
    version: 2, plugins: { "relay@relay": [{ scope: "user", installPath: cached }] },
  });
  resetInstalledPluginsCache();
  const plugins = installedPlugins(home);
  assert.equal(plugins.length, 1);
  const hooks: Record<string, Array<{ hooks: Array<{ command: string; args?: string[] }> }>> = {};
  loadPluginHooks(hooks, plugins);
  const start = hooks.SessionStart[0].hooks[0];
  assert.equal(start.command, "python3");
  assert.deepEqual(start.args, ["-I", path.join(cached, "hooks/merge.py"), "sweep"]);
  results.push({ check: "plugin hooks and exec args", result: "Cache fixture loads; CLAUDE_PLUGIN_ROOT and command/args are preserved. No lifecycle hook was executed." });

  const translated = claudeToolInput("edit", { path: "tracked.py", edits: [{ oldText: "before", newText: "after" }] }, project);
  assert.equal(translated.file_path, path.join(project, "tracked.py"));
  const guard = spawnSync("python3", [path.join(repo, "plugins/relay/hooks/guard_main.py")], {
    cwd: project, env: process.env, encoding: "utf8", timeout: 10_000,
    input: JSON.stringify({ cwd: project, tool_name: "Edit", tool_input: translated }),
  });
  if (guard.error) throw guard.error;
  assert.equal(guard.status, 2, guard.stderr);
  results.push({ check: "main-checkout file guard", result: "Translated built-in Edit is denied by Relay's real guard in a temporary Git repository." });

  const route = JSON.parse(run("python3", [path.join(repo, "plugins/delegate/hooks/route-guard.py")], {
    cwd: project, tool_name: "Agent", tool_input: { agent: "delegate:worker", task: "Brief: /tmp/probe.md" },
  }));
  assert.equal(route.hookSpecificOutput.permissionDecision, "deny");
  assert.match(route.hookSpecificOutput.permissionDecisionReason, /general-purpose/);
  results.push({ check: "agent input contract", result: "Blocked: pi-code's agent/task fields do not satisfy Relay's subagent_type/prompt routing contract." });

  const selected = findModel("opus", [
    { id: "gpt-6.1-sol", provider: "openai" },
    { id: "claude-opus-example", provider: "anthropic" },
  ]);
  assert.equal(selected.provider, "anthropic");
  results.push({ check: "Claude model aliases", result: "An opus alias selects an available Claude model even when an OpenAI model is available. Concrete provider/model overrides are required." });

  const transcript = path.join(scratch, "pi-session.jsonl");
  fixture(transcript, { type: "message", id: "example", timestamp: "2026-10-31T00:00:00Z", message: {
    role: "assistant", provider: "openai", model: "gpt-6.1-sol", content: [{ type: "text", text: "answer" }],
    usage: { input: 100, output: 10, cacheRead: 20, cacheWrite: 0, totalTokens: 130, cost: { total: 0.01 } },
  } });
  const observed = JSON.parse(run("python3", ["-c", [
    "import json,sys",
    "sys.path.insert(0,sys.argv[1])",
    "import relay_transcripts",
    "t=relay_transcripts.read_trace(sys.argv[2])",
    "print(json.dumps({'requests':t.total.requests,'cost':t.total.cost,'reply_chars':t.reply_chars}))",
  ].join(";"), path.join(repo, "lib"), transcript]));
  assert.deepEqual(observed, { requests: 0, cost: 0, reply_chars: 0 });
  results.push({ check: "Pi transcript accounting", result: "Relay records zero requests, cost, and reply characters for the Pi-format fixture. Native Pi accounting needs an adapter." });

  const version = JSON.parse(fs.readFileSync(path.join(source, "package.json"), "utf8")).version;
  console.log(JSON.stringify({ package: `pi-code@${version}`, modelCalls: 0, checks: results }, null, 2));
} finally {
  fs.rmSync(scratch, { recursive: true, force: true });
}
