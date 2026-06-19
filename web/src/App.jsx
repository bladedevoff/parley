import { useEffect, useState } from 'react'

/* ---- restrained line icons (monochrome, inherit currentColor) -------------- */
const P = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round', strokeLinejoin: 'round' }
const SVG = (c) => <span className="ic"><svg viewBox="0 0 24 24">{c}</svg></span>
const ICONS = {
  shield: SVG(<><path {...P} d="M12 3l7 2.5V11c0 4.2-3 7.2-7 8.5C8 18.2 5 15.2 5 11V5.5z" /><path {...P} d="M9 11.5l2 2 4-4.5" /></>),
  scale: SVG(<><path {...P} d="M12 4v15M7 19h10M5 8h14M5 8l-2 5h4zM19 8l-2 5h4z" /></>),
  gauge: SVG(<><path {...P} d="M4 15a8 8 0 0 1 16 0" /><path {...P} d="M12 15l4-3" /><path {...P} d="M4 18h16" /></>),
  swap: SVG(<><path {...P} d="M4 9h13l-3-3M20 15H7l3 3" /></>),
  target: SVG(<><circle {...P} cx="12" cy="12" r="7.5" /><circle {...P} cx="12" cy="12" r="3.5" /><circle cx="12" cy="12" r="1.3" fill="currentColor" /></>),
  vault: SVG(<><rect {...P} x="3.5" y="5" width="17" height="14" /><circle {...P} cx="12" cy="12" r="3.2" /><path {...P} d="M12 8.8v-1M12 16.2v1M15.2 12h1M7.8 12h-1" /></>),
  users: SVG(<><circle {...P} cx="8.5" cy="9" r="2.6" /><circle {...P} cx="16" cy="10" r="2.2" /><path {...P} d="M4 18c0-2.5 2-4 4.5-4s4.5 1.5 4.5 4M14 18c0-2 1.3-3.4 3.2-3.4 1.6 0 2.8 1 2.8 2.4" /></>),
  bot: SVG(<><rect {...P} x="5" y="8" width="14" height="10" rx="1.5" /><path {...P} d="M12 5v3M9 13h.01M15 13h.01M3 12v2M21 12v2" /></>),
  user: SVG(<><circle {...P} cx="12" cy="8.5" r="3" /><path {...P} d="M5.5 19c0-3.3 2.9-5.5 6.5-5.5s6.5 2.2 6.5 5.5" /></>),
  ban: SVG(<><circle {...P} cx="12" cy="12" r="8" /><path {...P} d="M6.5 6.5l11 11" /></>),
  doc: SVG(<><path {...P} d="M6 3h8l4 4v14H6z" /><path {...P} d="M14 3v4h4M9 12h6M9 15h6M9 9h2" /></>),
  chip: SVG(<><rect {...P} x="7" y="7" width="10" height="10" rx="1" /><path {...P} d="M10 3v2M14 3v2M10 19v2M14 19v2M3 10h2M3 14h2M19 10h2M19 14h2" /></>),
  key: SVG(<><circle {...P} cx="8" cy="12" r="3.3" /><path {...P} d="M11.2 11.5H20l-2 2.2M16.5 11.5v2.3" /></>),
  link: SVG(<><path {...P} d="M9.5 14.5l5-5M8 12l-1.6 1.6a3 3 0 0 0 4.2 4.2L12.4 16M16 12l1.6-1.6a3 3 0 0 0-4.2-4.2L11.6 8" /></>),
  flag: SVG(<><path {...P} d="M6 21V4M6 5h11l-2.5 3L17 11H6" /></>),
  check: SVG(<><circle {...P} cx="12" cy="12" r="8" /><path {...P} d="M8.5 12.2l2.4 2.3 4.6-5" /></>),
}
const I = ({ n }) => ICONS[n] || null

/* ---- Band logo: official mark (downloaded from band.ai) --------------------- */
const BandLogo = () => <img className="bandlogo" src="band-logo.svg" alt="Band" />


const MODES = [
  { key: 'normal', label: 'Normal deal', attack: false,
    cap: 'The happy path — Northwind asks for raw rows; Lumen’s vault refuses and counter-offers k-anonymous aggregates; a human approves; it runs in place; the checker passes.' },
  { key: 'inject', label: 'Injection attack', attack: true,
    cap: 'A prompt-injection hidden in the request. Even after the human approves, the kernel refuses it fail-closed — defense is in code, not the prompt.' },
  { key: 'purpose', label: 'Wrong purpose', attack: true,
    cap: 'An approved deal re-used for a different purpose (resale). Blocked at run time — consent is bound to its stated purpose (GDPR Art. 5(1)(b)).' },
  { key: 'budget', label: 'Exhaust DP budget', attack: true,
    cap: 'The per-counterparty differential-privacy budget is exhausted, so the vault is mechanically forced to decline — a math constraint, not an opinion.' },
]

const FEATURES = [
  { n: '01', ic: 'gauge', h: 'Composing DP budget', p: 'A per-counterparty privacy budget composes across deals and forces a decline when exhausted. Laplace + a real Rényi-DP accountant (Mironov 2017).', code: 'parley/dp.py' },
  { n: '02', ic: 'shield', h: 'Signed, verifiable provenance', p: 'Every step is hash-chained AND Ed25519-signed. A third party re-attests 9 invariants against the owner’s pinned public key — no shared secret.', code: 'parley/verify.py' },
  { n: '03', ic: 'scale', h: 'Policy that only tightens', p: 'final = stricter_of(LLM, policy). A prompt-injected “accept” is overruled; flagged requests are refused fail-closed in the kernel.', code: 'parley/policy.py' },
  { n: '04', ic: 'swap', h: 'Any agent, any org, any provider', p: 'Mix vendors freely — set each agent per role (VAULT_LLM_VENDOR, COORDINATOR_LLM_VENDOR, …) or the whole band globally (PARLEY_LLM_VENDOR). Claude, Groq, OpenRouter, OpenAI, or any /v1 endpoint; Claude is just the default, not required. Demonstrated live (Groq + OpenRouter).', code: 'parley/providers.py' },
  { n: '05', ic: 'target', h: 'Purpose-bound consent', p: 'Consent is bound to the stated purpose; re-using a deal for another purpose is blocked at run time and re-attestable. GDPR Art. 5(1)(b).', code: 'parley/session.py' },
  { n: '06', ic: 'vault', h: 'In-process clean room', p: 'Aggregates real row-level records (with PII) in place, exports zero rows; k-anonymity suppressed on the true count, re-checked after DP noise.', code: 'parley/cleanroom.py' },
]

const STEPS = [
  { ic: 'users', h: 'Recruit across the boundary', p: 'Northwind adds Lumen’s vault as a cross-org contact. The vault’s own LLM decides whether to accept being recruited — it can refuse.' },
  { ic: 'swap', h: 'Ask & counter-offer', p: 'The modeler asks for raw rows. The vault refuses and counter-offers in-place k-anonymous aggregates.' },
  { ic: 'key', h: 'First-party human gate', p: 'An agent’s APPROVE is rejected. Only a first-party Lumen human (the DPO) can authorize the export.' },
  { ic: 'check', h: 'Run in place, verify', p: 'The capability runs inside Lumen (rows_exported 0). The checker validates and the deal is sealed into a signed, re-attestable bundle.' },
]

const DEFENSE = [
  { ic: 'vault', h: 'Aggregates only, by construction', p: 'The in-place capability returns suppressed counts, never rows — a hijacked model still can’t emit raw data.' },
  { ic: 'key', h: 'Fail-closed human gate', p: 'Export runs only if a first-party owner human approves; an agent or a requester-side human is refused.' },
  { ic: 'flag', h: 'Hostile phrasing flagged & quarantined', p: 'A kernel tripwire flags common + paraphrased injection / exfil / bypass patterns. Best-effort by design — and even a phrase that slips it can’t extract a row or skip the human gate.' },
  { ic: 'scale', h: 'Policy can only tighten', p: 'stricter_of(LLM, policy): a prompt-injected “accept” is mechanically overruled by the owner’s policy.' },
]

const STACK = [
  { ic: 'link', t: 'Band', s: 'cross-org rooms' },
  { ic: 'bot', t: 'Claude Agent SDK', s: 'no API key' },
  { ic: 'swap', t: 'pydantic-ai', s: 'cross-vendor' },
  { ic: 'shield', t: 'Ed25519', s: 'signed provenance' },
  { ic: 'gauge', t: 'Rényi-DP', s: 'privacy budget' },
  { ic: 'chip', t: 'Python · uv', s: '124 tests' },
]

function tagFor(dec) {
  const d = (dec || '').toLowerCase()
  if (d === 'counter') return ['t-counter', 'COUNTER-OFFER']
  if (d === 'accept') return ['t-accept', 'ACCEPT']
  return ['t-decline', 'DECLINE']
}
function reqText(d) {
  if (d.note) return `“${d.note}”`
  if (d.raw) return `Send the raw customer rows: ${(d.columns || []).join(', ')}`
  return `Aggregate only — columns ${(d.columns || ['bucket', 'count']).join(', ')}, k≥${d.k || ''}${d.purpose ? `, purpose=${d.purpose}` : ''}`
}
function Msg({ side, from, children, delay }) {
  return <div className={`msg ${side}`} style={{ animationDelay: `${delay}ms` }}><div className="from">{from}</div><div>{children}</div></div>
}

function Console() {
  const [mode, setMode] = useState('normal')
  const [data, setData] = useState(null)
  const [approved, setApproved] = useState(false)
  const [gateMsg, setGateMsg] = useState('')
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    setData(null); setApproved(false); setGateMsg('')
    fetch(`demo/${mode}.json`).then(r => r.json()).then(setData).catch(() => setData({ error: 'failed to load demo data' }))
  }, [mode, nonce])

  const meta = MODES.find(m => m.key === mode)
  const buy = data?.buyer?.org || 'northwind'
  const own = data?.owner?.org || 'lumen'
  const nego = (data?.receipts || []).filter(r => ['request', 'consent'].includes(r.kind))
  const exec = (data?.receipts || []).filter(r => ['dp_charge', 'injection_block', 'capability_run', 'checker'].includes(r.kind))
  const blocked = data && data.capability && data.capability.status !== 'ok'
  const deliv = data?.deliverable && (data.deliverable.segments || data.deliverable.plan || data.deliverable.brief)

  return (
    <div>
      <div className="tabs">
        {MODES.map(m => <button key={m.key} className={`tab ${m.attack ? 'attack' : ''} ${mode === m.key ? 'active' : ''}`} onClick={() => setMode(m.key)}>{m.label}</button>)}
      </div>
      <p className="scenario-cap">{meta.cap}</p>

      <div className="console">
        <div className="card stage">
          <div className="hd"><span>Negotiation · deal {data?.deal_id || '—'}</span><a className="mono" style={{ cursor: 'pointer', color: 'var(--accent)' }} onClick={() => setNonce(n => n + 1)}>↻ replay</a></div>
          <div className="body">
            <div className="orgs">
              <div className="org buy"><h4 style={{ color: 'var(--buy)' }}>Northwind Analytics</h4><div className="who">requester — wants the data</div><div className="ags"><span className="ag">@coordinator</span><span className="ag">@modeler</span><span className="ag">@checker</span></div></div>
              <div className="org own"><h4 style={{ color: 'var(--own)' }}>Lumen Retail</h4><div className="who">owner — the recruited stranger</div><div className="ags"><span className="ag">@vault</span><span className="ag">DPO (human)</span></div></div>
            </div>
            <div className="timeline">
              {!data && <div className="note">loading real kernel output…</div>}
              {data?.error && <div className="note">error: {data.error}</div>}
              {nego.map((r, i) => r.kind === 'request'
                ? <Msg key={i} side="left" from={`@${buy}/modeler`} delay={i * 240}>{reqText(r.data)}</Msg>
                : (() => {
                    const [c, t] = tagFor(r.data.final || r.data.decision)
                    const txt = t === 'COUNTER-OFFER' ? 'No raw rows — I’ll run it in place and return only k-anonymous aggregates (k≥25).'
                      : t === 'ACCEPT' ? 'Safe aggregate request — accepted under policy.'
                      : (r.data.reasons && r.data.reasons[0]) || 'Refused by policy.'
                    return <Msg key={i} side="right" from={`@${own}/vault`} delay={i * 240}><span className={`tag ${c}`}>{t}</span>{txt}</Msg>
                  })()
              )}
              {approved && exec.map((r, i) => {
                if (r.kind === 'injection_block') return <Msg key={'e' + i} side="right" from={`@${own}/vault`} delay={i * 240}><span className="tag t-blocked">REFUSED · FAIL-CLOSED</span>request flagged {JSON.stringify(r.data.flags)}</Msg>
                if (r.kind === 'dp_charge') return <Msg key={'e' + i} side="right" from={`@${own}/vault`} delay={i * 240}>{r.data.allowed ? <><span className="tag t-run">DP CHARGE</span>ε={r.data.epsilon} · remaining={r.data.remaining}</> : <><span className="tag t-blocked">DP BUDGET EXHAUSTED</span>{r.data.reason}</>}</Msg>
                if (r.kind === 'capability_run') return <Msg key={'e' + i} side="right" from={`@${own}/vault`} delay={i * 240}><span className="tag t-run">RAN {r.data.capability}</span>rows_exported={r.data.rows_exported} · purpose={r.data.purpose}</Msg>
                const v = (r.data.verdict || '').toUpperCase()
                return <Msg key={'e' + i} side="left" from={`@${buy}/checker`} delay={i * 240}><span className={`tag ${v === 'PASS' ? 't-pass' : 't-blocked'}`}>{v}</span>{(r.data.findings || []).join(', ') || 'aggregates valid'}</Msg>
              })}
              {approved && blocked && <Msg side="right" from={`@${own}/vault`} delay={exec.length * 240}><span className="tag t-blocked">BLOCKED</span>{data.capability.reason}</Msg>}
            </div>
            {data && !data.error && (
              <div className="gate">
                <h5>Export gate — only a first-party Lumen human may approve</h5>
                <div className="row">
                  <button className="btn ghost" onClick={() => setGateMsg('reject')}>Agent sends “APPROVE”</button>
                  <button className="btn primary" disabled={approved} onClick={() => { setApproved(true); setGateMsg('approve') }}>Lumen DPO · APPROVE {data.deal_id}</button>
                </div>
                {gateMsg === 'reject' && <div className="note">✕ Rejected. An agent (or a requester-side human) cannot authorize an export — first-party Lumen human only.</div>}
                {gateMsg === 'approve' && <div className="note">✓ Approved by the Lumen DPO. Releasing to the in-place capability…</div>}
                {!gateMsg && <div className="note">Try both buttons — the agent is refused; the human releases.</div>}
              </div>
            )}
          </div>
        </div>

        <div className="card">
          <div className="hd"><span>Outcome &amp; attestation</span>{approved && <span className={`badge ${!blocked && data.verify_ok ? 'ok' : 'bad'}`}>{!blocked ? 'COMPLETED' : 'REFUSED'}</span>}</div>
          <div className="panel-body">
            <div className="note" style={{ marginTop: 0 }}>{!approved ? 'Approve in the gate to release & verify →' : (!blocked ? 'Counter-offered, human-approved, ran in place (rows_exported 0), checker passed.' : `Kernel refused: ${data.capability.reason}. No data left Lumen.`)}</div>
            {approved && !blocked && deliv && (<>
              <h4 style={{ marginTop: 16 }}>Deliverable <span className="badge zero">rows_exported 0</span></h4>
              {data.deliverable.title && <div style={{ fontSize: 13, marginBottom: 6 }}>{data.deliverable.title}</div>}
              <ul style={{ margin: 0, paddingLeft: 18 }}>{deliv.map((s, i) => <li className="deliv" key={i}>{s}</li>)}</ul>
            </>)}
            <h4 style={{ marginTop: 16 }}>verify <span className={`badge ${approved ? (data.verify_ok ? 'ok' : 'bad') : ''}`}>{approved ? (data.verify_ok ? 'exit 0' : 'exit 1') : ''}</span></h4>
            {(data?.verify_checks || []).map((c, i) => (
              <div className="inv" key={i}><span className={`mk ${!approved ? 'pending' : c.ok ? 'ok' : 'bad'}`}>{!approved ? '·' : c.ok ? '✓' : '✕'}</span><div><div className="nm">{c.invariant}</div><div className="d">{c.detail}</div></div></div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <>
      <div className="statusbar"><div className="wrap"><span>PARLEY</span><span>STATUS: <b>OPERATIONAL</b></span><span>9 INVARIANTS</span><span>124 TESTS</span><span>ROWS EXPORTED: <b>0</b></span></div></div>

      <nav><div className="wrap">
        <div className="brand"><span className="mk" /> Parley</div>
        <div className="links"><a href="#demo">Demo</a><a href="#why">Why Parley</a><a href="#problem">Business</a><a href="#verify">Verify</a></div>
        <a className="btn primary" href="#demo" style={{ marginLeft: 12 }}>Watch a deal ▸</a>
      </div></nav>

      <header className="hero"><div className="wrap">
        <span className="tagpill">Track 3 · Regulated &amp; high-stakes workflows · built on <b>Band</b></span>
        <h1 className="title">The agent that can <span className="mark">say no</span>.</h1>
        <p className="sub">Recruit an agent from <b>another organization</b>. Its own model decides whether to take the job, refuses raw data, counter-offers a safe alternative, and proceeds only after a <b>first-party human</b> approves — with signed, independently verifiable provenance.</p>
        <div className="cta"><a className="btn primary" href="#demo">Watch a live deal ▸</a><a className="btn ghost" href="#verify">Verify it yourself</a></div>
        <div className="metrics">
          <div><I n="check" /><b>9</b><span>re-attestable invariants</span></div>
          <div><I n="doc" /><b>124</b><span>tests, no stubs</span></div>
          <div><I n="vault" /><b>0</b><span>raw rows exported</span></div>
          <div><I n="swap" /><b>2×2</b><span>orgs × vendors</span></div>
        </div>
        <a className="powered" href="https://band.ai" target="_blank" rel="noreferrer"><span className="plbl">Powered by</span><BandLogo /></a>
      </div></header>

      <section className="block" id="demo"><div className="wrap">
        <span className="eyebrow"><I n="doc" /> Live · on the real kernel</span>
        <h2>Watch a cross-org deal get governed</h2>
        <p className="lead">Every message, signature and check below is genuine output from Parley’s offline kernel — not a mock. Switch the attack tabs to watch it refuse, fail-closed.</p>
        <Console />
      </div></section>

      <section className="block" id="why"><div className="wrap">
        <span className="eyebrow"><I n="scale" /> vs. the field</span>
        <h2>Most entries add agents. Parley recruits one that can refuse.</h2>
        <table>
          <thead><tr><th>&nbsp;</th><th>Typical multi-agent entry</th><th>Parley</th></tr></thead>
          <tbody>
            <tr><td>Agents</td><td>your own, switched on</td><td className="yes">a recruited stranger that can refuse</td></tr>
            <tr><td>If the agent disagrees</td><td>complies anyway</td><td className="yes">counter-offers safe terms</td></tr>
            <tr><td>Human approval</td><td>a prompt instruction</td><td className="yes">fail-closed in code (agent APPROVE rejected)</td></tr>
            <tr><td>Raw data</td><td>often shared</td><td className="yes">never leaves · rows_exported 0</td></tr>
            <tr><td>Trust</td><td>take their word</td><td className="yes">re-attest 9 signed invariants yourself</td></tr>
            <tr><td>Vendors</td><td>single, fixed</td><td className="yes">any provider per agent &amp; org — Claude, Groq, OpenRouter, OpenAI, any /v1 — mix freely</td></tr>
            <tr><td>Privacy</td><td>exact aggregates</td><td className="yes">composing DP budget forces decline</td></tr>
          </tbody>
        </table>
        <p className="lead" style={{ marginTop: 24 }}>We code-reviewed the closest governance rivals (consent-gated meshes, compliance boards, audit orchestrators). None combined these six controls — most have none:</p>
        <table>
          <thead><tr><th>Control</th><th>Parley</th><th>Governance rivals reviewed</th></tr></thead>
          <tbody>
            <tr><td>Consent-to-join (agent can refuse)</td><td className="yes">yes</td><td className="no">none</td></tr>
            <tr><td>Counter-offer (safe alternative)</td><td className="yes">yes</td><td className="no">none</td></tr>
            <tr><td>Human gate in code, fail-closed</td><td className="yes">yes</td><td className="no">rare; some fail-open</td></tr>
            <tr><td>Ed25519-signed provenance + verify</td><td className="yes">yes</td><td className="no">unsigned seals / mutable logs</td></tr>
            <tr><td>Differential privacy (budget + RDP)</td><td className="yes">yes</td><td className="no">none</td></tr>
            <tr><td>Purpose-binding at runtime (GDPR)</td><td className="yes">yes</td><td className="no">none</td></tr>
          </tbody>
        </table>
      </div></section>

      <section className="block" id="problem"><div className="wrap">
        <span className="eyebrow"><I n="users" /> The problem</span>
        <h2>Two companies, data that can’t move</h2>
        <div className="cols2">
          <div><div className="icrow"><I n="ban" /><h4 style={{ margin: 0 }}>The deadlock</h4></div><p style={{ color: 'var(--dim)', marginBottom: 0 }}>A hospital network and a research partner could save lives by combining data — but under <b>HIPAA the provider legally cannot hand over patient records</b>. Today it runs through Data Use Agreements + IRB review: <b>weeks-to-months</b> of legal/DPO email threads, with penalties up to <b>~$1.9M</b> per violation category/year (illustrative; HIPAA annual cap per tier, 45 CFR §160.404). Same deadlock for bank↔fintech KYC/AML, cross-org audits, partner analytics. So the deal stalls — or someone over-shares and creates liability.</p></div>
          <div><div className="icrow"><I n="key" /><h4 style={{ margin: 0 }}>The missing primitive</h4></div><p style={{ color: 'var(--dim)', marginBottom: 0 }}>You cannot safely put a partner’s agent to work on your data unless it can <b>refuse</b>, negotiate safe terms, gate on a human, and <b>prove</b> it never leaked. That primitive did not exist for cross-org agents. Parley is it.</p></div>
        </div>
      </div></section>

      <section className="block"><div className="wrap">
        <span className="eyebrow"><I n="vault" /> One kernel, any domain</span>
        <h2>Same two orgs, same four agents — only the data changes</h2>
        <table>
          <thead><tr><th>Example</th><th>The counter-offer</th><th>Capability</th></tr></thead>
          <tbody>
            <tr><td><b>Clinical cohorts (HIPAA)</b> ★</td><td className="yes">no patient records → in-place k-anon + DP cohort counts</td><td><code>cohort_aggregate</code></td></tr>
            <tr><td>Customer-data collaboration</td><td>no raw rows → in-place k-anon cohorts / model training</td><td><code>cohort_aggregate</code></td></tr>
            <tr><td>Cross-org code review</td><td>no source → in-place scan, return only findings</td><td><code>code_scan</code></td></tr>
            <tr><td>Productivity coaching (HR)</td><td>no per-employee records → team-level metrics only</td><td><code>productivity_metrics</code></td></tr>
          </tbody>
        </table>
        <p className="note">Deploy for your own two orgs by editing one file — <code className="mono">scenario.yaml</code>. The governance kernel is untouched.</p>
      </div></section>

      <section className="block" id="how"><div className="wrap">
        <span className="eyebrow"><I n="swap" /> How it works</span>
        <h2>Two orgs, four agents, one human gate</h2>
        <p className="lead">The requester recruits the owner’s agent across the org boundary. Nothing raw ever leaves; the owner’s human has the final say; every step is sealed and signed.</p>
        <table style={{ marginBottom: 22 }}>
          <thead><tr><th>Agent</th><th>Org</th><th>Role</th></tr></thead>
          <tbody>
            <tr><td><code>@…/coordinator</code></td><td>Northwind (buyer)</td><td>recruiter + human liaison</td></tr>
            <tr><td><code>@…/modeler</code></td><td>Northwind</td><td>needs the data</td></tr>
            <tr><td><code>@…/checker</code></td><td>Northwind</td><td>validates returned aggregates</td></tr>
            <tr><td><code>@…/vault</code></td><td><b>Lumen (owner)</b></td><td>the recruited stranger / data custodian</td></tr>
            <tr><td>DPO (human)</td><td>Lumen</td><td>approves the export in-room</td></tr>
          </tbody>
        </table>
        <div className="steps">
          {STEPS.map((s, i) => <div className="step" key={i}><div className="top"><I n={s.ic} /><span className="n">{String(i + 1).padStart(2, '0')}</span></div><h4>{s.h}</h4><p>{s.p}</p></div>)}
        </div>
      </div></section>

      <section className="block" id="moat"><div className="wrap">
        <span className="eyebrow"><I n="shield" /> The substance moat</span>
        <h2>Six things the field doesn’t have</h2>
        <p className="lead">Cross-org recruitment and human gates exist elsewhere. The combination below — refusal, a privacy budget that forces decline, a fail-closed first-party human gate, purpose-binding, cross-vendor, and signed verifiable provenance — does not.</p>
        <div className="grid">
          {FEATURES.map((f) => <div className="feat" key={f.n}><div className="top"><I n={f.ic} /><span className="n">{f.n}</span></div><h3>{f.h}</h3><p>{f.p} <br /><code>{f.code}</code></p></div>)}
        </div>
      </div></section>

      <section className="block"><div className="wrap">
        <span className="eyebrow"><I n="shield" /> Defense in depth</span>
        <h2>Cross-org means untrusted — so defense is in code, not prompts</h2>
        <p className="lead">Because the requester is another company, every message is treated as hostile input. Even a fully hijacked model cannot exfiltrate raw data.</p>
        <div className="grid">
          {DEFENSE.map((d, i) => <div className="feat" key={i}><div className="top"><I n={d.ic} /></div><h3>{d.h}</h3><p>{d.p}</p></div>)}
          <div className="feat"><div className="top"><I n="gauge" /></div><h3>Sound post-DP k-anonymity</h3><p>Cohorts are suppressed on the true count before noise, so a real sub-k cohort is never released — even under noise.</p></div>
          <div className="feat"><div className="top"><I n="doc" /></div><h3>Glass-box, then sealed</h3><p>Every thought, tool-call and result is emitted live, then hash-chained and signed into a bundle anyone can re-attest.</p></div>
        </div>
      </div></section>

      <section className="block" id="verify"><div className="wrap">
        <span className="eyebrow"><I n="shield" /> Zero trust</span>
        <h2>Don’t trust us — re-attest it</h2>
        <p className="lead">Every deal seals into a signed bundle. A third party re-checks all nine guarantees against the owner’s pinned public key and exits 0 only if they all hold.</p>
        <div className="verifybox">
          <pre>$ uv run python -m parley.verify bundle-deal-1.json{'\n'}  [<span className="ok">PASS</span>] provenance_chain_intact{'\n'}  [<span className="ok">PASS</span>] provenance_signed  (pinned owner key){'\n'}  [<span className="ok">PASS</span>] injection_clean{'\n'}  [<span className="ok">PASS</span>] first_party_human_approve{'\n'}  [<span className="ok">PASS</span>] consent_is_stricter_of{'\n'}  [<span className="ok">PASS</span>] rows_exported_zero{'\n'}  [<span className="ok">PASS</span>] post_dp_k_anonymity{'\n'}  [<span className="ok">PASS</span>] dp_within_budget{'\n'}  [<span className="ok">PASS</span>] purpose_bound{'\n'}RESULT: <span className="ok">VERIFIED — all invariants hold</span></pre>
          <div className="acts"><a className="btn primary" href="demo/bundle-deal-1.json" download>Download signed bundle</a><a className="btn ghost" href="demo/owner_pubkey.hex" download>Owner public key (pin)</a></div>
        </div>
      </div></section>

      <section className="block"><div className="wrap">
        <span className="eyebrow"><I n="flag" /> No theatre</span>
        <h2>What’s real vs. demo-scoped</h2>
        <div className="cols2">
          <div><div className="icrow"><I n="check" /><h4 style={{ margin: 0, color: 'var(--accent)' }}>Real</h4></div><p style={{ color: 'var(--dim)', marginBottom: 0 }}>Consent, counter-offer, refusal and the human gate are genuine LLM/Band events. The export gate, k-anonymity, differential privacy and Ed25519 signing are deterministic code under <b>124 tests</b>. Cross-vendor was demonstrated live on Groq and OpenRouter.</p></div>
          <div><div className="icrow"><I n="ban" /><h4 style={{ margin: 0, color: 'var(--bad)' }}>Demo-scoped</h4></div><p style={{ color: 'var(--dim)', marginBottom: 0 }}>The owner’s dataset is synthetic (the clean room aggregates real generated rows). For the demo the two orgs are two accounts of one operator. Band’s Memory API is Enterprise-gated, so cross-deal persistence falls back to a local store.</p></div>
        </div>
      </div></section>

      <section className="block"><div className="wrap">
        <span className="eyebrow"><I n="chip" /> Built with</span>
        <h2>Heterogeneous agents, real cryptography</h2>
        <div className="stack">{STACK.map((s, i) => <div className="chip" key={i}><I n={s.ic} /><b>{s.t}</b> · {s.s}</div>)}</div>
      </div></section>

      <footer><div className="wrap footrow"><span>PARLEY — recruitment you can be turned down for.</span><span className="builton">Built on <BandLogo /> for the Band of Agents Hackathon.</span></div></footer>
    </>
  )
}
