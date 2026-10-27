// A fake Workflow runtime for tests: runs a workflow script against scripted agent answers, with no model.
// Usage: bun fake-workflow.js meta <script>           -> prints the script's meta literal as JSON, or exits 3 if it is not a pure literal
//        bun fake-workflow.js run <script> <scenario>  -> prints {events, result, unscripted} as JSON
// A scenario is JSON: {"args": {...}, "answers": {...}}. An answer key is an exact label ("gate 2: x") or
// "stage:<word>" for every label of that stage word ("stage:gate"). A value is the agent's result, null (the user
// skipped the agent), {"$throw": "text"} (the agent died), or {"$seq": [value, ...]} (one per call, the last repeats).
// An agent with no scripted answer is recorded in "unscripted" and dies, so a test sees a stage it did not expect.
import { readFileSync } from 'node:fs'

const [mode, scriptPath, scenarioPath] = process.argv.slice(2)
const text = readFileSync(scriptPath, 'utf8')

function metaLiteral() {
  const start = text.indexOf('export const meta = ')
  if (start < 0) throw new Error('no meta block')
  const open = text.indexOf('{', start)
  let depth = 0, inStr = null
  for (let i = open; i < text.length; i++) {
    const c = text[i]
    if (inStr) { if (c === '\\') i++; else if (c === inStr) inStr = null; continue }
    if (c === "'" || c === '"' || c === '`') inStr = c
    else if (c === '{') depth++
    else if (c === '}' && --depth === 0) return text.slice(open, i + 1)
  }
  throw new Error('unterminated meta block')
}

if (mode === 'meta') {
  const lit = metaLiteral()
  // pure literal: once strings and `key:` are removed only brackets, commas and spaces may remain
  const rest = lit.replace(/'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"/g, '').replace(/\b\w+\s*:/g, '')
  if (!/^[\s{}\[\],]*$/.test(rest)) { console.error('meta is not a pure literal'); process.exit(3) }
  console.log(JSON.stringify(new Function('return (' + lit + ')')()))
} else {
  const scenario = JSON.parse(readFileSync(scenarioPath, 'utf8'))
  const events = [], unscripted = [], used = {}
  const stageOf = (label) => label.replace(/( \d+)?: .*$/, '')
  const fakeAgent = async (prompt, opts) => {
    const label = opts.label
    events.push({ event: 'start', label, phase: opts.phase, agentType: opts.agentType, prompt })
    await Promise.resolve()
    let key = label
    let v = scenario.answers[key]
    if (v === undefined) { key = 'stage:' + stageOf(label); v = scenario.answers[key] }
    if (v === undefined) { unscripted.push(label); events.push({ event: 'end', label }); throw new Error('no scripted answer for ' + label) }
    if (v && typeof v === 'object' && '$seq' in v) {
      const n = used[key] = (used[key] || 0) + 1
      v = v.$seq[Math.min(n, v.$seq.length) - 1]
    }
    events.push({ event: 'end', label })
    if (v && typeof v === 'object' && '$throw' in v) throw new Error(v.$throw)
    return v
  }
  const pipeline = (list, fn) => Promise.all(list.map((x, i) => fn(x, i)))
  const noClock = () => { throw new Error('Date.now and Math.random are refused in workflow scripts') }
  Date.now = noClock
  Math.random = noClock
  const body = text.replace('export const meta = ', 'const meta = ')
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
  const fn = new AsyncFunction('agent', 'pipeline', 'parallel', 'phase', 'log', 'args', body)
  const result = await fn(fakeAgent, pipeline, (l) => Promise.all(l), () => {}, () => {}, scenario.args)
  console.log(JSON.stringify({ events, result, unscripted }))
}
