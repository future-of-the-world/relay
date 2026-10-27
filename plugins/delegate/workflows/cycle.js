export const meta = {
  name: 'cycle',
  description: 'The change cycle: build, gate, review, fix, gate, one check, close the queue item. Kinds: change, built, fix, recheck (a branch or a train), plus a design track.',
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
//   recheck  {name, wt, check, findings | items: [{slug, review}], branch*}   gate, then the check(s), show
//   (* relay mode only; item is one fix-item slug)
// Designs, in args.designs: {name, brief, out, review (false: an analysis, one thinker)}.
// Optional args.settings: gate_turns 20-80 (40), gate_fixes 0-3 (1), retry_dead 0-2 (1), gate_args (a string, '--quick'; '' is the plain quick gate, '--paid' the full one with the paid evals).
// Every label is `<stage word>[ N]: <unit name>`; a stop names the stage word it stopped at (or `owner`).

const A = args || {}
const S = A.scratch
const RELAY = A.relay === true
const DEFAULTS = { gate_turns: 40, gate_fixes: 1, retry_dead: 1, gate_args: '--quick' }
const BOUNDS = { gate_turns: [20, 80], gate_fixes: [0, 3], retry_dead: [0, 2] }
const SLUG = /^[a-z0-9][a-z0-9-]{0,63}$/
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
  outside: { type: 'integer' }, design_or_question: { type: 'boolean' }, remaining: { type: 'boolean' },
  main_point: { type: 'string', description: 'the most important finding in one plain sentence' } },
  required: ['inside', 'outside', 'design_or_question', 'remaining', 'main_point'] }
const CHECK = { type: 'object', properties: {
  open: { type: 'integer' }, met: { type: 'integer' }, not_met: { type: 'integer' },
  q1_test: { type: 'string', description: 'when the unit names a queue item: the test that proves Q1, as <test file>::<test name>; else empty' },
  fail_without_fix: { type: 'string', description: 'for each test you relied on: did it fail with the fix disabled (yes/no/not run, per test)' },
  summary: { type: 'string' } },
  required: ['open', 'fail_without_fix', 'summary'] }

const NOFIX = `\nFor every new or changed test you rely on, prove it fails without the fix: make a throwaway worktree in ${S} at the commit before the fix (git worktree add --detach), copy in only the test file(s) from the head, run the test there and expect it to fail, then remove that worktree (git worktree remove --force). Never edit or stash the change's worktree. Say per test in fail_without_fix.`

function refusal() {
  if (typeof A.base !== 'string' || !A.base.trim()) return 'refused: missing arg base (the default branch of the project)'
  if (typeof A.relay !== 'boolean') return 'refused: missing arg relay (true where the project has .relay/, else false)'
  if (typeof S !== 'string' || !S.trim()) return 'refused: missing arg scratch (the folder for reports, logs and briefs)'
  if (!RELAY && (typeof A.gate !== 'string' || !A.gate.trim())) return 'refused: missing arg gate (the project\'s own gate command; required when relay is false)'
  for (const k of Object.keys(BOUNDS)) {
    const v = CFG[k]
    if (!Number.isInteger(v) || v < BOUNDS[k][0] || v > BOUNDS[k][1]) return `refused: setting ${k} must be a whole number from ${BOUNDS[k][0]} to ${BOUNDS[k][1]}`
  }
  if (typeof CFG.gate_args !== 'string') return 'refused: setting gate_args must be a string'
  const items = A.items || [], designs = A.designs || []
  if (!Array.isArray(items) || !Array.isArray(designs)) return 'refused: items and designs must be lists'
  for (const it of items) {
    const who = `unit ${it && it.name}`
    if (!it || !SLUG.test(it.name || '')) return `refused: ${who} needs a name of lower-case letters, digits and dashes`
    const kind = it.kind || 'change'
    if (!KINDS.includes(kind)) return `refused: ${who} has an unknown kind ${kind}`
    for (const f of ['wt', 'check']) if (typeof it[f] !== 'string' || !it[f]) return `refused: ${who} needs ${f}`
    if (RELAY && (typeof it.branch !== 'string' || !it.branch)) return `refused: ${who} needs branch (relay mode)`
    if (!RELAY && it.item) return `refused: ${who} names a queue item, which exists only in relay mode`
    if (kind !== 'fix' && it.fix) return `refused: ${who} is kind ${kind}, which takes no fix prompt (use kind fix)`
    if (kind === 'built' && !it.built) return `refused: ${who} is kind built and needs built (what the build did)`
    if (kind !== 'built' && it.built) return `refused: ${who} gives built, which only kind built takes`
    if (kind === 'fix') for (const f of ['fix', 'fixes', 'findings']) if (typeof it[f] !== 'string' || !it[f]) return `refused: ${who} is kind fix and needs ${f}`
    if (kind === 'recheck') {
      const list = it.items || []
      if (!Array.isArray(list)) return `refused: ${who} items must be a list`
      if (list.length === 0 && !it.findings) return `refused: ${who} is kind recheck and needs findings or items`
      for (const r of list) if (!r || !SLUG.test(r.slug || '') || !r.review) return `refused: ${who} items need a slug and a review each`
    }
  }
  for (const d of designs) {
    if (!d || !SLUG.test(d.name || '') || !d.brief || !d.out) return `refused: a design needs a name, a brief and an out`
  }
  return ''
}

// One agent call, retried under the same label when it throws; a null (the user skipped it) is not retried.
async function ask(prompt, opts) {
  let last = 'agent died'
  for (let t = 0; t <= CFG.retry_dead; t++) {
    try {
      const v = await agent(prompt, opts)
      if (v === null) return { dead: 'agent skipped' }
      return { v }
    } catch (e) {
      last = String(e && e.message ? e.message : e)
    }
  }
  return { dead: last }
}

function stop(it, at, detail, extra) {
  return Object.assign({ name: it.name, ready: false, stopped_at: at, detail }, extra || {})
}

const agentOpts = (type, schema, phase, label) => ({ agentType: `delegate:${type}`, schema, phase, label })

// File names carry the kind for a fix or recheck run, so it never overwrites what the change run wrote.
const tag = (it) => ((it.kind || 'change') === 'change' || it.kind === 'built') ? it.name : `${it.kind}-${it.name}`

function gatePrompt(it, n) {
  const log = `${S}/gate-${tag(it)}-${n}.log`
  const wait = `It takes minutes to an hour and may first wait for a free slot: wait in as few turns as possible (you have ${CFG.gate_turns}; if the gate is still running at your ${CFG.gate_turns - 5}th turn, report ok=false with first_fail "still running, pid <pid>, log <path>" instead of ending silently): each Bash call one bounded loop of at most 230 s (\`for i in \$(seq 1 11); do kill -0 <pid> 2>/dev/null || break; sleep 20; done\`), never a call per check.`
  if (RELAY) {
    const ga = CFG.gate_args.trim()
    const cmd = ga === '--paid' ? `relay gate -C ${it.wt} --paid` : ga ? `relay gate -C ${it.wt} -- ${ga}` : `relay gate -C ${it.wt}`
    return `Run \`${cmd}\` detached with the limits recipe, log in ${log}. ${wait} Report ok, the gate sha, the gate log path it prints (under the worktree's .relay/checks/), and the first failing line if any.`
  }
  return `Run the project's gate in ${it.wt} detached with the limits recipe, writing the log in the form: \`{ echo "head $(git -C ${it.wt} rev-parse HEAD)"; ${A.gate}; echo "exit $?"; } > ${log} 2>&1\` (run it with ${it.wt} as the current folder) and write its pid to ${log}.pid first. If ${log}.pid already exists and that pid is alive, a gate of an earlier attempt is still running: do not start another, wait on that pid and report its log. ${wait} Report ok (the exit code was 0), the head sha, the log path ${log}, and the first failing line if any.`
}

// A gate with up to gate_fixes rounds of "fix red gate, gate again". Counters run through the whole unit, so the
// labels are gate 1, fix red gate 1, gate 2, ..., and a later group goes on from the numbers before it.
async function gated(it, st) {
  while (true) {
    st.gn += 1
    const r = await ask(gatePrompt(it, st.gn), agentOpts('runner', GATE, 'Gate', `gate ${st.gn}: ${it.name}`))
    if (r.dead) return { stop: stop(it, 'gate', r.dead) }
    const g = r.v
    if (g.ok) return { g }
    if (/^still running/i.test(g.first_fail || '')) return { stop: stop(it, 'gate', g.first_fail) }
    if (st.rounds >= CFG.gate_fixes) return { stop: stop(it, 'gate', g.first_fail || 'gate red') }
    st.rounds += 1
    st.fn += 1
    const fx = `${S}/reports/fixgate-${tag(it)}-${st.fn}.md`
    const f = await ask(`Fix the red gate. Worktree: ${it.wt}. Gate log: ${g.gate_log}. First failing line: ${g.first_fail}. Brief of the change: ${S}/briefs/${it.name}.md. Check: ${it.check}. Never work around a relay guard or hook. Commit the fix. Report: ${fx}.`,
      agentOpts('fixer', HANDBACK, 'Fix', `fix red gate ${st.fn}: ${it.name}`))
    if (f.dead || f.v.status !== 'DONE') return { stop: stop(it, 'fix red gate', f.dead || f.v.summary) }
    st.fixReports.push(fx)
  }
}

function newState() { return { gn: 0, fn: 0, rounds: 0, fixReports: [] } }

// A new group (after the review fix) starts with a fresh allowance of gate_fixes rounds.
async function gateGroup(it, st) {
  st.rounds = 0
  return gated(it, st)
}

function fixesText(first, st) {
  const firsts = [].concat(first).filter((x) => x && x !== 'none')
  const all = firsts.concat(st.fixReports)
  return all.length ? all.join(' and ') : 'none'
}

async function checkStage(it, label, prompt, report, withItem) {
  const q1 = withItem ? `\nq1_test must name one test as <test file>::<test name>.` : ''
  return ask(`${prompt} Report: \`${report}\`.` + NOFIX + q1, agentOpts('checker', CHECK, 'Check', label))
}

// The closing stages after a gate: one check, the queue close, the check show.
async function finish(it, st, o) {
  const { findings, fixes, gateLog, review } = o
  const withItem = RELAY && !!it.item
  const c = await checkStage(it, `check: ${it.name}`,
    `Check: \`${findings}\`. Fixes: \`${fixes}\`. Worktree: \`${it.wt}\`. Check command: \`${it.check}\`. Gate: \`${gateLog}\`.`,
    `${S}/reports/check-${tag(it)}.json`, withItem)
  if (c.dead) return stop(it, 'check', c.dead, { review })
  const ck = c.v
  if (ck.open !== 0) return stop(it, 'check', ck.summary, { review, open: ck.open, fail_without_fix: ck.fail_without_fix })
  let queue = null
  if (withItem) {
    if (!ck.q1_test) return stop(it, 'check', 'the check closed with no test for the queue item (q1_test is empty)', { review })
    const d = await ask(`Run exactly: \`relay queue done ${it.item} -C ${it.wt} --test ${ck.q1_test}\`. Report DONE with the output line, or BLOCKED with the refusal text.`,
      agentOpts('runner', HANDBACK, 'Check', `close queue item: ${it.name}`))
    if (d.dead || d.v.status !== 'DONE') return stop(it, 'close queue item', d.dead || d.v.summary, { review, queue: { slug: it.item, test: ck.q1_test } })
    queue = { slug: it.item, test: ck.q1_test, fail_without_fix: ck.fail_without_fix, closed: `${d.v.status}: ${d.v.summary}` }
  }
  return showStage(it, { ready: true, open: 0, check: ck.summary, fail_without_fix: ck.fail_without_fix, review, queue, gateLog })
}

async function showStage(it, result) {
  if (!RELAY) return Object.assign({ name: it.name }, result)
  const s = await ask(`Run \`relay check show ${it.branch} -C ${it.wt}\` (if -C is refused, run it with the worktree as the current folder). Report DONE and the line with the open count, or BLOCKED and the error.`,
    agentOpts('runner', HANDBACK, 'Check', `check show: ${it.name}`))
  return Object.assign({ name: it.name }, result, { show: s.dead ? s.dead : s.v.summary })
}

async function changeUnit(it) {
  const st = newState()
  if (it.kind === 'built') {
    // the build was done by hand: nothing to run
  } else {
    const b = await ask(`Implement the brief. Brief: \`${S}/briefs/${it.name}.md\`. Report: \`${S}/reports/${it.name}.md\`.`,
      agentOpts('worker', HANDBACK, 'Build', `build: ${it.name}`))
    if (b.dead || b.v.status !== 'DONE') return stop(it, 'build', b.dead || b.v.summary)
  }
  let r1 = await gateGroup(it, st)
  if (r1.stop) return r1.stop
  let gateLog = r1.g.gate_log

  const reviewJson = `${S}/reports/review-${it.name}.json`
  const handover = RELAY ? ' docs/handover.md and .relay/queue/ commits are the front\'s record, not part of the change.' : ''
  const rv = await ask(`Review the change. Range: \`${A.base}...HEAD\` in \`${it.wt}\`. Report: \`${reviewJson}\`. Contract: the brief ${S}/briefs/${it.name}.md.${handover}`,
    agentOpts('critic', REVIEW, 'Review', `review: ${it.name}`))
  if (rv.dead) return stop(it, 'review', rv.dead)
  const r = rv.v
  if (r.remaining || r.design_or_question) return stop(it, 'owner', r.main_point, { review: r })
  let fixes = 'none'
  if (r.inside > 0) {
    fixes = `${S}/reports/fix-${it.name}.md`
    const f = await ask(`Fix the findings inside the change, each with its failing case and pass cases (read with \`relay check show ${reviewJson}\`). Worktree: ${it.wt}. Check: ${it.check}. New tests go in the change's own new test file (see the brief). For each new test show it fails without the fix. Findings outside the change: leave them, list them as Outside. Commit. Write your report (Fixed / Disputed / Gap / Outside per finding, with the test as file::function) to ${fixes}.`,
      agentOpts('fixer', HANDBACK, 'Fix', `fix: ${it.name}`))
    if (f.dead || f.v.status !== 'DONE') return stop(it, 'fix', f.dead || f.v.summary, { review: r })
    const r2 = await gateGroup(it, st)
    if (r2.stop) return Object.assign(r2.stop, { review: r })
    gateLog = r2.g.gate_log
  }
  return finish(it, st, { findings: reviewJson, fixes: fixesText([it.kind === 'built' ? 'none' : `${S}/reports/${it.name}.md`, fixes], st), gateLog, review: r })
}

async function fixUnit(it) {
  const st = newState()
  const f = await ask(it.fix, agentOpts('fixer', HANDBACK, 'Fix', `fix: ${it.name}`))
  if (f.dead || f.v.status !== 'DONE') return stop(it, 'fix', f.dead || f.v.summary)
  const r = await gateGroup(it, st)
  if (r.stop) return r.stop
  return finish(it, st, { findings: it.findings, fixes: fixesText(it.fixes, st), gateLog: r.g.gate_log, review: undefined })
}

async function recheckUnit(it) {
  const st = newState()
  const r = await gateGroup(it, st)
  if (r.stop) return r.stop
  const list = it.items || []
  if (list.length === 0) return finish(it, st, { findings: it.findings, fixes: fixesText('none', st), gateLog: r.g.gate_log, review: undefined })
  // A train: one check per rider's item, in order, each started after the one before it came back with open 0.
  const checks = []
  for (let k = 0; k < list.length; k++) {
    const q = list[k]
    const c = await checkStage(it, `check item ${k + 1}: ${it.name}`,
      `Merge check of a rider's item: \`${it.wt}\`. Item: \`${q.slug}\`. Review: \`${q.review}\`. Findings: \`relay check findings -C ${it.wt} --item ${q.slug} --review ${q.review}\`. Gate: \`${r.g.gate_log}\`.`,
      `${S}/reports/check-${tag(it)}-item-${k + 1}.json`, false)
    if (c.dead) return stop(it, 'check item', c.dead, { checks })
    checks.push({ slug: q.slug, open: c.v.open, summary: c.v.summary, fail_without_fix: c.v.fail_without_fix })
    if (c.v.open !== 0) return stop(it, 'check item', c.v.summary, { checks, open: c.v.open })
  }
  return showStage(it, { ready: true, open: 0, checks, gateLog: r.g.gate_log })
}

async function unit(it) {
  const kind = it.kind || 'change'
  if (kind === 'fix') return fixUnit(it)
  if (kind === 'recheck') return recheckUnit(it)
  return changeUnit(Object.assign({}, it, { kind }))
}

async function design(d) {
  const stem = d.out.replace(/\.[A-Za-z0-9]+$/, '')
  const reviewPath = `${stem}-review.json`
  const t = await ask(`Brief: \`${d.brief}\`. Output: \`${d.out}\`.`, agentOpts('thinker', HANDBACK, 'Design', `design: ${d.name}`))
  if (t.dead || t.v.status !== 'DONE') return { name: d.name, design: 'failed', detail: t.dead || t.v.summary }
  if (d.review === false) return { name: d.name, design: d.out }
  const rv = await ask(`Review the design ${d.out} adversarially (design review before a risky build; the brief is ${d.brief}). Each finding names file:line where it names code and a concrete failing case. Reply with the count by severity and the main point. Report: \`${reviewPath}\`.`,
    agentOpts('critic', HANDBACK, 'Design', `design review: ${d.name}`))
  if (rv.dead) return { name: d.name, design: d.out, review: rv.dead }
  const t2 = await ask(`Brief: \`${d.brief}\`. Output: \`${d.out}\`. Revise the design against the review ${reviewPath} (read it with \`relay check show ${reviewPath}\`): fix what holds, answer what does not with the reason, and end with an "Open for the owner" list (only real trade-offs).`,
    agentOpts('thinker', HANDBACK, 'Design', `design revise: ${d.name}`))
  return { name: d.name, design: d.out, review: rv.v.summary, revised: t2.dead ? t2.dead : t2.v.summary }
}

const refused = refusal()
if (refused) return { refused }
const items = A.items || []
const [changes, designs] = await Promise.all([
  pipeline(items, unit),
  pipeline(A.designs || [], design),
])
return { changes: changes.map((r, i) => r || { name: items[i].name, ready: false, stopped_at: 'crash' }), designs }
