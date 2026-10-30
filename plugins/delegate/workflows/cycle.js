export const meta = {
  name: 'cycle',
  description: 'The change cycle: build, gate, review, fix, gate, one check, close the queue item. Kinds: change, built, fix, plus a design track (recheck only where the project has no .relay/: `relay land` takes the base and gates in relay mode).',
  phases: [
    { title: 'Build' }, { title: 'Gate' }, { title: 'Review' }, { title: 'Fix' }, { title: 'Check' }, { title: 'Design' },
  ],
}

// Required args: base (the default branch), relay (true where the project has .relay/), scratch (reports, logs,
// briefs) and, when relay is false, gate (the project's own gate command). A missing one stops the run in one line
// before any agent starts: the script has no git and no shell, so it cannot compute a default.
// Units, in args.items, each with a kind (default 'change'):
//   change   {name, wt, check, branch*, item*}                       build, gate, review, fix, gate, check, close, show
//   built    {name, wt, check, built, branch*, item*}                the same without the build
//   fix      {name, wt, check, fix, fixes, findings, branch*, item*} fix, gate, check, close, show
//   recheck  {name, wt, check, findings, fixes}                                          take the base, gate, check (project mode only: in relay mode `relay land` takes the base and gates)
//   (* relay mode only; item is one fix-item slug)
// Designs, in args.designs: {name, brief, out, review (false: an analysis, one thinker)}.
// Optional args.settings: gate_turns 20-80 (40), gate_fixes 0-3 (1), gate_reruns 0-2 (1: how often a gate that stopped at its time limit is run again, with no fixer), retry_dead 0-2 (1), gate_args (a string, '--quick'; '' is the plain quick gate, '--paid' the full one with the paid evals),
// land (true: in relay mode a ready unit is landed by `relay land` as the last stage; false: the cycle ends at ready and the front lands; a unit's own `land` overrides it), land_fixes 0-2 (1: fix rounds for a red or conflicting landing), land_reruns 0-3 (1: how often an exit 4 is landed again).
// The land stage branches on the exit code of `relay land`: 0 landed, 1 red gate and 3 take conflict (a fixer, gate, check, land again), 4 land again, 5 stops at `owner` (a hold or an unanswered question), 6 stops at `paid` (waits for the paid run, no owner question), 2 stops at `land`.
// Every label is `<stage word>[ N]: <unit name>`; a stop names the stage word it stopped at (or `owner`).

const A = args || {}
const S = A.scratch
const RELAY = A.relay === true
const DEFAULTS = { gate_turns: 40, gate_fixes: 1, gate_reruns: 1, retry_dead: 1, gate_args: '--quick', land: true, land_fixes: 1, land_reruns: 1 }
const BOUNDS = { gate_turns: [20, 80], gate_fixes: [0, 3], gate_reruns: [0, 2], retry_dead: [0, 2], land_fixes: [0, 2], land_reruns: [0, 3] }
const SLUG = /^[a-z0-9][a-z0-9-]{0,63}$/
const TOP_KEYS = ['base', 'relay', 'scratch', 'gate', 'items', 'designs', 'settings']
const UNIT_KEYS = ['name', 'kind', 'wt', 'check', 'branch', 'item', 'built', 'fix', 'fixes', 'findings', 'land']
const DESIGN_KEYS = ['name', 'brief', 'out', 'review', 'item']
const KINDS = ['change', 'built', 'fix', 'recheck']
const CFG = Object.assign({}, DEFAULTS, A.settings || {})

const HANDBACK = { type: 'object', properties: {
  status: { type: 'string', enum: ['DONE', 'BLOCKED', 'BUDGET SPENT'] }, summary: { type: 'string' } },
  required: ['status', 'summary'] }
const GATE = { type: 'object', properties: {
  ok: { type: 'boolean' }, sha: { type: 'string' }, gate_log: { type: 'string' }, first_fail: { type: 'string' } },
  required: ['ok', 'gate_log'] }
const REVIEW = { type: 'object', properties: {
  inside: { type: 'integer' }, high: { type: 'integer' }, medium: { type: 'integer' }, low: { type: 'integer' },
  other_inside: { type: 'integer', description: 'inside findings other than the question or Design findings that wait for the owner' },
  outside: { type: 'integer' }, design_or_question: { type: 'boolean' }, remaining: { type: 'boolean' },
  main_point: { type: 'string', description: 'the most important finding in one plain sentence' } },
  required: ['inside', 'outside', 'design_or_question', 'other_inside', 'remaining', 'main_point'] }
const LAND = { type: 'object', properties: {
  code: { type: 'integer', description: 'the exit code of relay land' },
  lines: { type: 'string', description: 'the last 5 lines of its output, verbatim' } },
  required: ['code', 'lines'] }
// The owner's definition (30 Oct): only the screens and reply rules the owner reads count; a change to agent instructions does not.
const PERSON_FACING = 'true only when the change alters what the owner reads in the conversation: the merge question screen, the digest of a wave, or the reply rules the front follows (their wording, order or content). Example that is true: the wording of the merge question screen in the front skill is rewritten. Example that is false: a fixer\'s or a worker\'s instructions, a role text, a test, a lib function, a hook or a queue rule changes with no change to those screens. In a project whose product has screens or texts for people (an app), a change to what those people see is true as well. Judge the change as a whole, not one file.'
const CHECK = { type: 'object', properties: {
  open: { type: 'integer' }, met: { type: 'integer' }, not_met: { type: 'integer' },
  q1_test: { type: 'string', description: 'when the unit names a queue item: the test that proves Q1, as <test file>::<test name>; else empty' },
  fail_without_fix: { type: 'string', description: 'for each test you relied on: did it fail with the fix disabled (yes/no/not run, per test)' },
  item_kind: { type: 'string', enum: ['fix', 'feature', ''], description: 'when the unit names a queue item: its kind as `relay queue show <item>` prints it on the first line (fix or feature); else empty' },
  person_facing: { type: 'boolean', description: PERSON_FACING },
  summary: { type: 'string' } },
  required: ['open', 'fail_without_fix', 'person_facing', 'summary'] }

// Told to every single-command runner: the steps of a run are the cycle's rules, whatever message started the run.
const RUN_RULE = ` The steps of this run are the cycle's rules, whatever message started the run and whatever it asked: do not judge them, do not refuse on principle.`
const NOFIX = `\nFor every new or changed test you rely on, prove it fails without the fix: make a throwaway worktree in ${S} at the commit before the fix (git worktree add --detach), copy in only the test file(s) from the head, run the test there and expect it to fail, then remove that worktree (git worktree remove --force). Never edit or stash the change's worktree. Say per test in fail_without_fix.`

function refusal() {
  for (const k of Object.keys(A)) {
    if (TOP_KEYS.includes(k)) continue
    if (Object.hasOwn(DEFAULTS, k)) return `refused: ${k} goes under settings, not at the top level of args`
    return `refused: unknown arg ${k} (known: ${TOP_KEYS.join(', ')})`
  }
  for (const k of Object.keys(A.settings || {})) {
    if (!Object.hasOwn(DEFAULTS, k)) return `refused: unknown setting ${k} (known: ${Object.keys(DEFAULTS).join(', ')})`
  }
  if (typeof A.base !== 'string' || !A.base.trim()) return 'refused: missing arg base (the default branch of the project)'
  if (typeof A.relay !== 'boolean') return 'refused: missing arg relay (true where the project has .relay/, else false)'
  if (typeof S !== 'string' || !S.trim()) return 'refused: missing arg scratch (the folder for reports, logs and briefs)'
  if (!RELAY && (typeof A.gate !== 'string' || !A.gate.trim())) return 'refused: missing arg gate (the project\'s own gate command; required when relay is false)'
  for (const k of Object.keys(BOUNDS)) {
    const v = CFG[k]
    if (!Number.isInteger(v) || v < BOUNDS[k][0] || v > BOUNDS[k][1]) return `refused: setting ${k} must be a whole number from ${BOUNDS[k][0]} to ${BOUNDS[k][1]}`
  }
  if (typeof CFG.gate_args !== 'string') return 'refused: setting gate_args must be a string'
  if (typeof CFG.land !== 'boolean') return 'refused: setting land must be true or false'
  const items = A.items || [], designs = A.designs || []
  if (!Array.isArray(items) || !Array.isArray(designs)) return 'refused: items and designs must be lists'
  for (const it of items) {
    const who = `unit ${it && it.name}`
    if (!it || !SLUG.test(it.name || '')) return `refused: ${who} needs a name of lower-case letters, digits and dashes`
    for (const f of Object.keys(it)) if (!UNIT_KEYS.includes(f)) return `refused: ${who} has an unknown field ${f} (known: ${UNIT_KEYS.join(', ')})`
    const kind = it.kind || 'change'
    if (it.land !== undefined && typeof it.land !== 'boolean') return `refused: ${who} has land ${JSON.stringify(it.land)}: the field land must be true or false`
    if (!KINDS.includes(kind)) return `refused: ${who} has an unknown kind ${kind}`
    for (const f of ['wt', 'check']) if (typeof it[f] !== 'string' || !it[f]) return `refused: ${who} needs ${f}`
    if (RELAY && (typeof it.branch !== 'string' || !it.branch)) return `refused: ${who} needs branch (relay mode)`
    if (!RELAY && it.item) return `refused: ${who} names a queue item, which exists only in relay mode`
    if (kind !== 'fix' && it.fix) return `refused: ${who} is kind ${kind}, which takes no fix prompt (use kind fix)`
    if (kind === 'built' && !it.built) return `refused: ${who} is kind built and needs built (what the build did)`
    if (kind !== 'built' && it.built) return `refused: ${who} gives built, which only kind built takes`
    if (kind === 'fix') for (const f of ['fix', 'fixes', 'findings']) if (typeof it[f] !== 'string' || !it[f]) return `refused: ${who} is kind fix and needs ${f}`
    if (kind === 'recheck') {
      if (RELAY) return `refused: unit ${it.name}: in relay mode relay land takes the base and gates; a take conflict is kind fix with fix 'take ${A.base} and resolve <files>', findings = the branch's last review JSON, fixes = the fixer's report, and no item`
      if (!it.findings) return `refused: ${who} is kind recheck and needs findings`
    }
  }
  for (const d of designs) {
    if (!d || !SLUG.test(d.name || '') || !d.brief || !d.out) return `refused: a design needs a name, a brief and an out`
    if (d.item !== undefined && !SLUG.test(d.item)) return `refused: design ${d.name} has an item that is not a queue slug`
    for (const f of Object.keys(d)) if (!DESIGN_KEYS.includes(f)) return `refused: design ${d.name} has an unknown field ${f} (known: ${DESIGN_KEYS.join(', ')})`
  }
  return ''
}

const SKIPPED = 'agent skipped'

// One agent call, retried under the same label when it throws; a null (the user skipped it) is not retried.
// Each thrown attempt is written down before the retry (the journal keeps only "failed"): the script has no file access, so a runner does it.
async function ask(prompt, opts) {
  let last = 'agent died'
  for (let t = 0; t <= CFG.retry_dead; t++) {
    try {
      const v = await agent(prompt, opts)
      if (v === null) return { dead: SKIPPED }
      return { v }
    } catch (e) {
      last = String(e && e.message ? e.message : e)
      await deadNote(opts, t + 1, last)
    }
  }
  return { dead: last }
}

// Best effort: a note that cannot be written never hides the dead agent's own error, which ask() still returns.
async function deadNote(opts, n, message) {
  const slug = String(opts.label).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  // The note is work of the dead agent's change: its label carries that agent's unit (the part after the first ": "), so the metrics match it.
  const unit = String(opts.label).slice(String(opts.label).indexOf(': ') + 2)
  const file = `${S}/reports/dead-${slug}-${n}.txt`
  try {
    await agent(`Write the file ${file} (create the folder first) with three lines (if the file already exists, keep what it holds and append the three lines: an earlier run's note is never replaced): "label: ${opts.label}", "time: " followed by the output of \`date -u +%Y-%m-%dT%H:%M:%SZ\`, and "error: " followed by this text exactly: ${JSON.stringify(message)}. Report DONE.`,
      agentOpts('runner', HANDBACK, opts.phase, `other: ${unit}`))
  } catch (e) {
    // nothing more to do: the error text is still in the returned detail
  }
}

function stop(it, at, detail, extra) {
  return Object.assign({ name: it.name, ready: false, stopped_at: at, detail }, extra || {})
}

const agentOpts = (type, schema, phase, label) => ({ agentType: `delegate:${type}`, schema, phase, label })

// File names carry the kind for a fix or recheck run, so it never overwrites what the change run wrote.
// The unit a label names: the full queue item id when the unit has one (the metrics then match it exactly), else its name.
const lab = (it) => it.item || it.name
const tag = (it) => ((it.kind || 'change') === 'change' || it.kind === 'built') ? it.name : `${it.kind}-${it.name}`

// The quiet check every agent of a unit loops on: in relay mode `relay precheck` (the gate's quick steps, changed tests and the rules registry test included) comes in
// front of the unit's own check, so a brief or an item that names only a test line cannot leave it out.
const quiet = (it) => RELAY ? `relay precheck -C ${it.wt} && (${it.check})` : it.check
// The precheck's changed-tests step may take up to 10 minutes on a busy machine, past the 4-minute foreground command limit: say so up front.
const quietNote = () => RELAY ? ' The precheck can take more than 4 minutes on a busy machine: run this check detached with a log (the limits recipe) and wait in calls under 4 minutes, never as one foreground call.' : ''

// A recheck lands a branch on the newest base: the gate runner first takes the base with a merge commit (a no-op when the
// branch already holds the base's head); a conflict stops the unit, the script never resolves one.
function takePrompt(it) {
  return `First take the base: run \`git -C ${it.wt} merge --no-edit ${A.base}\` (the branch must hold ${A.base}'s head before the gate; "Already up to date" is fine). If the merge stops on a conflict, run \`git -C ${it.wt} merge --abort\` and report ok=false with first_fail starting "take conflict:" and the conflicting files; run no gate. `
}

function gatePrompt(it, n) {
  const log = `${S}/gate-${tag(it)}-${n}.log`
  const wait = `It takes minutes to an hour and may first wait for a free slot: wait in as few turns as possible (you have ${CFG.gate_turns}; if the gate is still running at your ${CFG.gate_turns - 5}th turn, report ok=false with first_fail "still running, pid <pid>, log <path>" instead of ending silently): each Bash call one bounded loop of at most 230 s (\`for i in \$(seq 1 11); do kill -0 <pid> 2>/dev/null || break; sleep 20; done\`), never a call per check.`
  if (RELAY) {
    const ga = CFG.gate_args.trim()
    const cmd = ga === '--paid' ? `relay gate -C ${it.wt} --paid` : ga ? `relay gate -C ${it.wt} -- ${ga}` : `relay gate -C ${it.wt}`
    return `${it.kind === 'recheck' ? takePrompt(it) : ''}Run \`${cmd}\` detached with the limits recipe, log in ${log}. ${wait} Report ok, the gate sha, the gate log path it prints (under the worktree's .relay/checks/), and the first failing line if any, copied verbatim.`
  }
  return `${it.kind === 'recheck' ? takePrompt(it) : ''}Run the project's gate in ${it.wt} detached with the limits recipe, writing the log in the form: \`{ echo "head $(git -C ${it.wt} rev-parse HEAD)"; ${A.gate}; echo "exit $?"; } > ${log} 2>&1\` (run it with ${it.wt} as the current folder) and write its pid to ${log}.pid first. If ${log}.pid already exists and that pid is alive, a gate of an earlier attempt is still running: do not start another, wait on that pid and report its log. ${wait} Report ok (the exit code was 0), the head sha, the log path ${log}, and the first failing line if any.`
}

// The step after a gate agent that ended with no result: the committed gate log of the head decides before anything runs.
function recoveryPrompt(it, n, prev) {
  const head = `$(git -C ${it.wt} rev-parse HEAD)`
  const intro = 'An earlier gate agent for this worktree ended without a result, so the gate may have run. Do in this order. '
  if (!RELAY) {
    // Project mode: nothing below the agent reuses or locks, so the dead attempt's own log and pid file decide.
    const old = `${S}/gate-${tag(it)}-${prev}.log`
    return `${intro}1. Read ${old}.pid: if that pid is alive, the earlier gate still runs, so start none: wait on it, then report ${old}. 2. Else, if ${old} ends with a line \`exit <code>\` and its first line \`head <sha>\` names the worktree's HEAD (${head}), run no gate: report ok from that exit, the sha, ${old} and the first failing line. 3. Only otherwise run the gate once as follows. ${gatePrompt(it, n)}`
  }
  const logs = `${it.wt}/.relay/checks/<head>*.gate.log`
  const read = `${intro}1. Take the head (${head}) and look for its gate log ${logs}; a finished relay gate commits its log, so when HEAD's subject is "relay: gate of <sha>" or "relay: remote gate of <sha>" the log is ${it.wt}/.relay/checks/<sha>*.gate.log. If one exists, run no gate: report ok from the exit it records, its sha, that log's path and the first failing line. 2. Else, if a gate is already running on ${it.wt} (look at the processes with \`ps\` for a relay gate on that folder), do not start another: wait on its pid, then read its log as in 1. 3. Only when there is no log and no running gate, run the gate once as follows. `
  return `${read}${gatePrompt(it, n)}`
}

// A gate with up to gate_fixes rounds of "fix red gate, gate again". Counters run through the whole unit, so the
// labels are gate 1, fix red gate 1, gate 2, ..., and a later group goes on from the numbers before it.
async function gated(it, st) {
  while (true) {
    st.gn += 1
    let r = await ask(gatePrompt(it, st.gn) + RUN_RULE, agentOpts('runner', GATE, 'Gate', `gate ${st.gn}: ${lab(it)}`))
    if (r.dead && r.dead !== SKIPPED) {
      // The gate agent ended with no result: the gate may have run, so one recovery agent reads the head's gate log first.
      const prev = st.gn
      st.gn += 1
      r = await ask(recoveryPrompt(it, st.gn, prev) + RUN_RULE, agentOpts('runner', GATE, 'Gate', `gate ${st.gn}: ${lab(it)}`))
    }
    if (r.dead) return { stop: stop(it, 'gate', r.dead) }
    const g = r.v
    if (g.ok) return { g }
    if (/^(still running|take conflict)/i.test(g.first_fail || '')) return { stop: stop(it, 'gate', g.first_fail) }
    // a gate stopped at its time limit (relay gate prints "gate: stopped at the N-minute limit, step <name> was running") is not a
    // failing test: no fixer, the gate runs again; when the reruns are used up the unit stops with that line
    if (/^gate: stopped at/i.test(g.first_fail || '')) {
      if (st.reruns >= CFG.gate_reruns) return { stop: stop(it, 'gate', g.first_fail) }
      st.reruns += 1
      continue
    }
    if (st.rounds >= CFG.gate_fixes) return { stop: stop(it, 'gate', g.first_fail || 'gate red') }
    st.rounds += 1
    st.fn += 1
    const fx = `${S}/reports/fixgate-${tag(it)}-${st.fn}.md`
    const f = await ask(`Fix the red gate. Worktree: ${it.wt}. Gate log: ${g.gate_log}. First failing line: ${g.first_fail}. Brief of the change: ${S}/briefs/${it.name}.md. Check: ${quiet(it)}.${quietNote()} Never work around a relay guard or hook. Commit the fix. Report: ${fx}.`,
      agentOpts('fixer', HANDBACK, 'Fix', `fix red gate ${st.fn}: ${lab(it)}`))
    if (f.dead || f.v.status !== 'DONE') return { stop: stop(it, 'fix red gate', f.dead || f.v.summary) }
    st.fixReports.push(fx)
  }
}

function newState() { return { gn: 0, fn: 0, ln: 0, cn: 1, rounds: 0, reruns: 0, fixReports: [] } }

// A new group (after the review fix) starts with a fresh allowance of gate_fixes rounds.
async function gateGroup(it, st) {
  st.rounds = 0
  st.reruns = 0
  return gated(it, st)
}

function fixesText(first, st) {
  const firsts = [].concat(first).filter((x) => x && x !== 'none')
  const all = firsts.concat(st.fixReports)
  return all.length ? all.join(' and ') : 'none'
}

async function checkStage(it, label, prompt, report, withItem) {
  const q1 = withItem ? `\nq1_test must name one test as <test file>::<test name>. item_kind is the queue item's kind from \`relay queue show ${it.item} -C ${it.wt}\` (fix or feature).` : ''
  return ask(`${prompt} Report: \`${report}\`.` + NOFIX + q1, agentOpts('checker', CHECK, 'Check', label))
}

// The closing stages after a gate: one check, the queue close, the check show.
async function finish(it, st, o) {
  const { findings, fixes, gateLog, review } = o
  const withItem = RELAY && !!it.item
  const c = await checkStage(it, `check: ${lab(it)}`,
    `Check: \`${findings}\`. Fixes: \`${fixes}\`. Worktree: \`${it.wt}\`. Check command: \`${quiet(it)}\`.${quietNote()} Gate: \`${gateLog}\`.`,
    `${S}/reports/check-${tag(it)}.json`, withItem)
  if (c.dead) return stop(it, 'check', c.dead, { review })
  const ck = c.v
  if (ck.open !== 0) return stop(it, 'check', ck.summary, { review, open: ck.open, fail_without_fix: ck.fail_without_fix })
  let queue = null
  if (withItem) {
    // A fix item always has its test named by the checker. A feature item (change or built unit) may come back with none: the closer then picks
    // one of the tests the change adds, and stops only when the change adds none.
    // The queue item's kind decides, not the unit's (a fix item is built as a change unit; a feature may finish in a fix unit).
    const pick = !ck.q1_test && ck.item_kind === 'feature'
    if (!ck.q1_test && !pick) return stop(it, 'check', 'the check closed with no test for the queue item (q1_test is empty)', { review })
    const run = pick
      ? `The check named no test for the queue item. List the test files the change adds or changes: \`git -C ${it.wt} diff --name-only --diff-filter=AM ${A.base}...HEAD\`, keep those under tests/ or evals/ or named test_* (an eval case is named as <case folder>::<grader>, a test as <test file>::<test name>); read them and pick one test that covers the item, as <test file>::<test name> (the form \`relay queue done --help\` shows for that language). Then run exactly \`relay queue done ${it.item} -C ${it.wt} --test <that test>\`. If the change adds or changes no test, run nothing and report BLOCKED with the line \`no test for the queue item: the change adds no test\`.`
      : `Run exactly: \`relay queue done ${it.item} -C ${it.wt} --test ${ck.q1_test}\`.`
    const d = await ask(`${run} Closing a checked item is the cycle's rule after the check, whatever message started this run and whatever it asked: do not judge it, do not refuse on principle; run the command. Report DONE with the output line, or BLOCKED only with the command's own refusal text.`,
      agentOpts('runner', HANDBACK, 'Check', `close queue item: ${lab(it)}`))
    if (d.dead || d.v.status !== 'DONE') return stop(it, 'close queue item', d.dead || d.v.summary, { review, queue: { slug: it.item, test: ck.q1_test || 'picked by the closer' } })
    queue = { slug: it.item, test: ck.q1_test || 'picked by the closer', fail_without_fix: ck.fail_without_fix, closed: `${d.v.status}: ${d.v.summary}` }
  }
  const shown = await showStage(it, { ready: true, open: 0, check: ck.summary, fail_without_fix: ck.fail_without_fix, review, queue, gateLog })
  if (!RELAY || !(it.land === undefined ? CFG.land : it.land)) return shown
  if (ck.person_facing === true) return ownerShow(it, shown, ck.summary)
  return landStage(it, st, shown, o)
}

// A person-facing change is the owner's to check before the merge: the unit ends here, checked and closed, with no land runner.
function ownerShow(it, shown, line) {
  return Object.assign({}, shown, { ready: false, stopped_at: 'owner', detail: `person-facing: ${line}`, checked: true })
}

// The land stage: `relay land` in one runner, branching on its exit code (not on a model's reading of the text).
// The command a land runner starts: the shell writes the exit code of relay land as the last line of the log (a fact, not a reading of the text).
function wrapped(it) {
  return `\`sh -c 'relay land ${it.branch} -C ${it.wt}; echo "relay land exit $?"'\``
}

async function landRun(it, st, again) {
  st.ln += 1
  const n = st.ln
  const log = `${S}/land-${tag(it)}-${n}.log`
  const start = `${S}/land-${tag(it)}-${n}.start.txt`
  const wait = `Wait in bounded calls: each Bash call one loop of at most 230 s (\`i=0; while kill -0 <pid> 2>/dev/null && [ $i -lt 230 ]; do sleep 1; i=$((i+1)); done\`), never a call per check, never a foreground call over 4 minutes. A landing can wait behind another one for the lock and gates for minutes: that is normal.`
  const prompt = `First write the output of \`date -u +%Y-%m-%dT%H:%M:%SZ\` to ${start} (create the folder first). Then run ${wrapped(it)} detached with the limits recipe, log ${log}. ${wait} When it ends, report code (the number n on the last line of the log, \`relay land exit <n>\`: a detached process's exit status cannot be read any other way; never take it from another "exit" in the text) and lines (the 5 lines of the log before that last line, verbatim; when one of the log's lines starts with \`landed \`, put it first).`
  let r = await ask(prompt + RUN_RULE, agentOpts('runner', LAND, 'Check', `land ${n}: ${lab(it)}`))
  if (r.dead && r.dead !== SKIPPED) {
    // The runner died: the landing may have run or may still run. One recovery runner decides, in this order, and starts relay land at most once (step 4).
    st.ln += 1
    const rec = `${S}/land-${tag(it)}-${st.ln}.log`
    r = await ask(`The runner of \`relay land ${it.branch}\` ended without a result, so the landing may be running or done. Do in this order and stop at the first that applies. 1. A live \`relay land ${it.branch}\` process (look with ps): wait on its pid in bounded calls (each at most 230 s), then report the number n of the last line \`relay land exit <n>\` of its log ${log} as code (if the log has no such line, go to step 2). 2. Read the start time of that try in ${start} (if the file is missing, the runner never began: go to step 4). Find the newest \`done\` event of ${it.branch} in the file \`$(git -C ${it.wt} rev-parse --path-format=absolute --git-common-dir)/relay-land/events.jsonl\` whose \`asked\` event of the same pid is after that start time, and report its outcome as code: landed 0, red 1, refused or dirty 2, conflict 3, handed_back 4, waits_owner 5, waits_paid 6. 3. If the branch ${it.branch} no longer exists and the reflog of ${A.base} shows \`merge ${it.branch}: Fast-forward\`, report code 0 and the line \`landed ${it.branch}\`. 4. Otherwise run ${wrapped(it)} once, detached, log ${rec}, and report its code (the last line \`relay land exit <n>\` of that log) and the 5 lines before it. Never start a second relay land.${RUN_RULE}`,
      agentOpts('runner', LAND, 'Check', `land ${st.ln}: ${lab(it)}`))
  }
  if (r.dead) return { dead: r.dead }
  return { code: r.v.code, lines: String(r.v.lines || '') }
}

async function landStage(it, st, shown, o) {
  let fixed = 0, reran = 0
  let fixes = o.fixes
  while (true) {
    const L = await landRun(it, st)
    if (L.dead) return Object.assign({}, shown, { ready: false, stopped_at: 'land', detail: L.dead, checked: true })
    const rows = L.lines.split('\n')
    const first = rows.find((x) => x.startsWith('landed ')) || rows.find((x) => x.trim()) || ''
    const at = (where) => Object.assign({}, shown, { ready: false, stopped_at: where, detail: L.lines.trim() || `relay land exited ${L.code}`, checked: true })
    if (L.code === 0) return Object.assign({}, shown, { landed: first })
    if (L.code === 5) return at('owner')
    if (L.code === 6) return at('paid')
    if (L.code === 4) {
      if (reran >= CFG.land_reruns) return at('land')
      reran += 1
      continue
    }
    if (L.code !== 1 && L.code !== 3) return at('land')
    if (fixed >= CFG.land_fixes) return at('land')
    fixed += 1
    st.fn += 1
    const fx = `${S}/reports/fixland-${tag(it)}-${fixed}.md`
    const what = L.code === 1
      ? `Fix the red landing gate (the gate of the branch after it took ${A.base}). Landing output: ${L.lines}. The gate log is the path in that output.`
      : `Take ${A.base} into ${it.branch} and resolve the conflict: run \`git -C ${it.wt} merge --no-edit ${A.base}\`, resolve the conflicting files named in this landing output, commit the merge. Landing output: ${L.lines}.`
    const f = await ask(`${what} Worktree: ${it.wt}. Brief of the change: ${S}/briefs/${it.name}.md. Check: ${quiet(it)}.${quietNote()} Never work around a relay guard or hook. Commit. Report: ${fx}. Report BLOCKED when you cannot resolve it.`,
      agentOpts('fixer', HANDBACK, 'Fix', L.code === 1 ? `fix red gate ${st.fn}: ${lab(it)}` : `fix ${st.fn}: ${lab(it)}`))
    if (f.dead || f.v.status !== 'DONE') return Object.assign({}, shown, { ready: false, stopped_at: 'land', detail: f.dead || f.v.summary, checked: true })
    const g = await gateGroup(it, st)
    if (g.stop) return Object.assign({}, shown, g.stop, { checked: true })
    fixes = [].concat(fixes, fx).filter((x) => x && x !== 'none').join(' and ')
    st.cn += 1
    // The check after a land fixer: no second close of the item; it answers person_facing again.
    const c = await checkStage(it, `check ${st.cn}: ${lab(it)}`,
      `Check: \`${o.findings}\`. Fixes: \`${fixes}\`. Worktree: \`${it.wt}\`. Check command: \`${quiet(it)}\`.${quietNote()} Gate: \`${g.g.gate_log}\`. The fixer resolved a landing that was red or in conflict: check the resolved files.`,
      `${S}/reports/check-${tag(it)}-land${fixed}.json`, false)
    if (c.dead) return Object.assign({}, shown, { ready: false, stopped_at: 'land', detail: c.dead, checked: true })
    if (c.v.open !== 0) return Object.assign({}, shown, { ready: false, stopped_at: 'land', detail: c.v.summary, open: c.v.open, checked: true })
    if (c.v.person_facing === true) return ownerShow(it, shown, c.v.summary)
  }
}

async function showStage(it, result) {
  if (!RELAY) return Object.assign({ name: it.name }, result)
  const s = await ask(`Run \`relay check show ${it.branch} -C ${it.wt}\` (if -C is refused, run it with the worktree as the current folder). Report DONE and the line with the open count, or BLOCKED and the error.${RUN_RULE}`,
    agentOpts('runner', HANDBACK, 'Check', `check show: ${lab(it)}`))
  return Object.assign({ name: it.name }, result, { show: s.dead ? s.dead : s.v.summary })
}

async function changeUnit(it) {
  const st = newState()
  if (it.kind === 'built') {
    // the build was done by hand: nothing to run
  } else {
    const b = await ask(`Implement the brief. Brief: \`${S}/briefs/${it.name}.md\`. Report: \`${S}/reports/${it.name}.md\`. Loop on this quiet check: \`${quiet(it)}\`.${quietNote()}`,
      agentOpts('worker', HANDBACK, 'Build', `build: ${lab(it)}`))
    if (b.dead || b.v.status !== 'DONE') return stop(it, 'build', b.dead || b.v.summary)
  }
  let r1 = await gateGroup(it, st)
  if (r1.stop) return r1.stop
  let gateLog = r1.g.gate_log

  const reviewJson = `${S}/reports/review-${it.name}.json`
  const handover = RELAY ? ' docs/handover.md and .relay/queue/ commits are the front\'s record, not part of the change.' : ''
  const rv = await ask(`Review the change. Range: \`${A.base}...HEAD\` in \`${it.wt}\`. Report: \`${reviewJson}\`. Contract: the brief ${S}/briefs/${it.name}.md.${handover}`,
    agentOpts('critic', REVIEW, 'Review', `review: ${lab(it)}`))
  if (rv.dead) return stop(it, 'review', rv.dead)
  const r = rv.v
  if (r.remaining) return stop(it, 'owner', r.main_point, { review: r })
  // A question or Design finding waits for the owner; every other inside finding is fixed first, gated and checked.
  const waits = r.design_or_question
  const toFix = waits ? (Number.isInteger(r.other_inside) ? r.other_inside : r.inside) : r.inside
  if (waits && toFix <= 0) return stop(it, 'owner', r.main_point, { review: r })
  let fixes = 'none'
  if (toFix > 0) {
    fixes = `${S}/reports/fix-${it.name}.md`
    const wait = waits ? ' Every finding of kind question or Design (relay check show prints the kind) waits for the owner: do not fix it, leave it open.' : ''
    const f = await ask(`Fix the findings inside the change, each with its failing case and pass cases (read with \`relay check show ${reviewJson}\`).${wait} Worktree: ${it.wt}. Check: ${quiet(it)}.${quietNote()} New tests go in the change's own new test file (see the brief). For each new test show it fails without the fix. Findings outside the change: leave them, list them as Outside. Commit. Write your report (Fixed / Disputed / Gap / Outside per finding, with the test as file::function) to ${fixes}.`,
      agentOpts('fixer', HANDBACK, 'Fix', `fix: ${lab(it)}`))
    if (f.dead || f.v.status !== 'DONE') return stop(it, 'fix', f.dead || f.v.summary, { review: r })
    const r2 = await gateGroup(it, st)
    if (r2.stop) return Object.assign(r2.stop, { review: r })
    gateLog = r2.g.gate_log
  }
  const given = fixesText([it.kind === 'built' ? 'none' : `${S}/reports/${it.name}.md`, fixes], st)
  if (waits) {
    const c = await checkStage(it, `check: ${lab(it)}`,
      `Check: \`${reviewJson}\`. Fixes: \`${given}\`. Worktree: \`${it.wt}\`. Check command: \`${quiet(it)}\`.${quietNote()} Gate: \`${gateLog}\`. Every question or Design finding waits for the owner.`,
      `${S}/reports/check-${tag(it)}.json`, false)
    if (c.dead) return stop(it, 'check', c.dead, { review: r })
    return stop(it, 'owner', r.main_point, { review: r, open: c.v.open, check: c.v.summary, fail_without_fix: c.v.fail_without_fix, gateLog })
  }
  return finish(it, st, { findings: reviewJson, fixes: given, gateLog, review: r })
}

async function fixUnit(it) {
  const st = newState()
  const f = await ask(`${it.fix} Check: ${quiet(it)}.${quietNote()}`, agentOpts('fixer', HANDBACK, 'Fix', `fix: ${lab(it)}`))
  if (f.dead || f.v.status !== 'DONE') return stop(it, 'fix', f.dead || f.v.summary)
  const r = await gateGroup(it, st)
  if (r.stop) return r.stop
  return finish(it, st, { findings: it.findings, fixes: fixesText(it.fixes, st), gateLog: r.g.gate_log, review: undefined })
}

async function recheckUnit(it) {
  const st = newState()
  const r = await gateGroup(it, st)
  if (r.stop) return r.stop
  // The fixes already made: the given fix report, else the earlier check records this script wrote for this worktree, whose
  // MET verdicts carry over. 'none' would make the checker judge every fixed finding again with no fix named.
  const given = it.fixes || `the earlier check records ${S}/reports/check-*.json whose worktree is ${it.wt} (read each with relay check show <file>); carry each MET verdict whose files did not change since its head`
  return finish(it, st, { findings: it.findings, fixes: fixesText(given, st), gateLog: r.g.gate_log, review: undefined })
}

async function unit(it) {
  const kind = it.kind || 'change'
  if (kind === 'fix') return fixUnit(it)
  if (kind === 'recheck') return recheckUnit(it)
  return changeUnit(Object.assign({}, it, { kind }))
}

// Whether a thinker's hand-back carries the last line of `relay queue plan` (landed or unchanged). A design with no queue item is not kept.
function planKept(d, answer) {
  if (!d.item) return 'not kept: this design has no queue item, so no plan is written beside one'
  const said = answer && !answer.dead && answer.v ? String(answer.v.summary || '') : ''
  if (said.includes(`plan ${d.item}: landed`) || said.includes(`plan ${d.item}: unchanged`)) return 'kept'
  return `plan not kept: run relay queue plan ${d.item} --input ${d.out}`
}

async function design(d) {
  const stem = d.out.replace(/\.[A-Za-z0-9]+$/, '')
  const reviewPath = `${stem}-review.json`
  const t = await ask(`Brief: \`${d.brief}\`. Output: \`${d.out}\`.`, agentOpts('thinker', HANDBACK, 'Design', `design: ${d.name}`))
  if (t.dead || t.v.status !== 'DONE') return { name: d.name, design: 'failed', detail: t.dead || t.v.summary }
  if (d.review === false) return { name: d.name, design: d.out, plan: planKept(d, t) }
  const rv = await ask(`Review the design ${d.out} adversarially (design review before a risky build; the brief is ${d.brief}). Each finding names file:line where it names code and a concrete failing case. Reply with the count by severity and the main point. Report: \`${reviewPath}\`.`,
    agentOpts('critic', HANDBACK, 'Design', `design review: ${d.name}`))
  if (rv.dead) return { name: d.name, design: d.out, review: rv.dead, plan: planKept(d, t) }
  const t2 = await ask(`Brief: \`${d.brief}\`. Output: \`${d.out}\`. Revise the design against the review ${reviewPath} (read it with \`relay check show ${reviewPath}\`): fix what holds, answer what does not with the reason, and end with an "Open for the owner" list (only real trade-offs). Put the section "what changed after the review" in the plan: each finding, whether it held, the fix. The review itself is not kept anywhere else.${d.item ? ` Last step: run \`relay queue plan ${d.item} --input ${d.out}\` and put its last line in your hand-back.` : ''}`,
    agentOpts('thinker', HANDBACK, 'Design', `design revise: ${d.name}`))
  return { name: d.name, design: d.out, review: rv.v.summary, revised: t2.dead ? t2.dead : t2.v.summary, plan: planKept(d, t2) }
}

const refused = refusal()
if (refused) return { refused }
const items = A.items || []
const [changes, designs] = await Promise.all([
  pipeline(items, unit),
  pipeline(A.designs || [], design),
])
return { changes: changes.map((r, i) => r || { name: items[i].name, ready: false, stopped_at: 'crash' }), designs }
