# Parley — the agent that can say no

![tests](https://img.shields.io/badge/tests-124%20passing-brightgreen?style=flat)
![python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat&logo=python&logoColor=white)
![license](https://img.shields.io/badge/license-MIT-green?style=flat)
![built on Band](https://img.shields.io/badge/built%20on-Band-6f42c1?style=flat)
![runs on Claude Agent SDK](https://img.shields.io/badge/runs%20on-Claude%20Agent%20SDK-d97757?style=flat)
![Band of Agents 2026](https://img.shields.io/badge/Band%20of%20Agents-Hackathon%202026-orange?style=flat)

> **Live demo:** https://parley-vert-ten.vercel.app · **Repo:** https://github.com/bladedevoff/parley · **Verify it yourself (offline, no keys):** `uv run python -m parley.verify proof/bundle-deal-1.json`

**A recruited agent from another organization consents, counter-offers, and a human
gates the data — across two real orgs on [Band](https://www.band.ai).** Its own model
can refuse a raw-data request, counter-offer a safe alternative, and proceed only after
a first-party human from the data-owner side approves. *Recruitment you can be turned
down for.*

> Track 3 — Regulated & High-Stakes Workflows. Built on Band; runs on the Claude Agent
> SDK by default (no API key required) — but any agent can run on any provider.

---

## Quickstart — see it work in a minute

No Band, no Claude, no API keys needed for the offline proof:

```bash
uv sync --dev
uv run pytest -q                                          # 124 passing
uv run python -m parley.verify proof/bundle-deal-1.json   # re-attest a sealed deal → exit 0
uv run python scripts/tamper_test.py                      # PASS, then flip one byte → FAIL (exit 1)
```

**Visual demo — the Parley Console** (the negotiation + the verify invariants turning
green, driven by the SAME offline kernel):

```bash
uv run python ui/server.py        # open http://127.0.0.1:8765
```

Two orgs, the live counter-offer, the refused agent-APPROVE vs the human gate, the
in-place run (`rows_exported: 0`), and the nine `verify` invariants. Toggle the attack
tabs (injection / wrong purpose / DP-budget exhaustion) to watch the kernel refuse,
fail-closed.

## What it is, and why it matters

Regulated cross-org collaborations stall when the raw data legally **cannot move** —
two hospitals sharing cohort analytics under HIPAA without exchanging a single patient
record, or a bank and a fintech exchanging KYC/AML aggregates under a data-sharing
agreement. Today those deals take weeks of DPO/legal email threads, or die. Parley
collapses them into a **governed, signed, same-room decision** — and a third party can
re-verify it without trusting either side.

## The kernel (what's new)

Cross-org recruitment, cross-framework rooms, and human gates exist already. The two
things Parley adds are:

1. **Consent-to-join** — the recruited stranger's own LLM decides whether to accept
   being recruited (not a switched-on endpoint; it can refuse).
2. **Counter-offer** — it negotiates terms ("no raw rows; I'll run the analysis in
   place and return only k-anonymous aggregates").

This is the missing trust primitive for cross-org agent collaboration: you cannot
safely put a partner's agent to work on your data unless it can say no.

## How it works

Two organizations, four agents, one Band room:

| Agent | Org | Role |
|---|---|---|
| `@…/coordinator` | buyer (Northwind) | recruiter + human liaison |
| `@…/modeler` | buyer | needs the data |
| `@…/checker` | buyer | validates returned aggregates |
| `@…/vault` | **owner (Lumen)** | the recruited stranger / data custodian |
| DPO (human) | owner | approves the export in-room |

**Flow:** coordinator recruits the owner's vault across the org boundary → modeler
asks for raw data → **vault counters** (refuse raw, offer in-place k-anonymous
aggregates) → modeler revises → **vault accepts** → an *agent's* APPROVE is
**rejected** (only a first-party owner human may approve) → the **owner's human DPO
approves** → vault runs the in-place export (`rows_exported: 0`, sub-k cohorts
suppressed) → checker validates → **PASS**. Every step is real traffic on
app.band.ai (see `proof/`).

## What's inside — six enforced controls

Each control is a structural code path under test, not prompt wording — so a hijacked
or swapped model cannot disable it.

1. **Differential-privacy budget that composes across deals — with a real RDP
   accountant.** Released counts get calibrated noise and a per-counterparty budget
   *composes* across negotiations; when exhausted the vault is **mechanically forced to
   decline**. Two accountants ship: Laplace with linear composition, and the Gaussian
   mechanism with Rényi-DP advanced composition — which fits **2.5× more queries** under
   the same `(ε, δ)` budget (`proof/rdp-composition.json`). The consent kernel is a
   quantitative privacy accountant, not an LLM yes/no. (`parley/dp.py`)
2. **Ed25519-signed, hash-chained provenance + a `verify` CLI anyone can run.** Every
   step (request, consent, human-approve, DP-charge, capability-run, checker) is a link
   in a hash chain **AND signed with the data owner's Ed25519 key**. A bare hash chain
   is only tamper-*evident*; the signature closes that — forging a receipt needs the
   owner's private key, and a third party re-attests all nine guarantees against the
   owner's **pinned** public key (committed out-of-band, so a full re-sign forgery fails
   too): `uv run python -m parley.verify proof/bundle-deal-1.json` → exit 0/1.
   (`parley/provenance.py`, `parley/verify.py`)
3. **Policy-as-code consent that can only make the LLM stricter.** The owner's policy
   (authorable by compliance, not engineers — a plain dict, no Rego) is evaluated
   separately; the final decision is `stricter_of(llm, policy)`, so a prompt-injected
   "accept" is overruled. (`parley/policy.py`)
4. **Any agent can run any provider.** Not just a different org — set
   `PARLEY_LLM_VENDOR=groq` (or `openrouter`, `openai`, a `custom` `/v1` endpoint) to
   run the whole band off-Claude, or pick per role (`VAULT_LLM_VENDOR`,
   `COORDINATOR_LLM_VENDOR`, …). **Claude is the default, not a requirement;** every
   agent in either org can run on a different provider, and the same consent / no-raw
   guarantees hold because they live in code, not the model. Demonstrated live on Groq
   and OpenRouter. (`parley/providers.py`, `parley/agents/_adapters.py`)
5. **Purpose-bound consent (purpose limitation, GDPR Art. 5(1)(b)).** Consent is tied
   to the *purpose* the requester stated; re-using an approved deal for a different
   purpose (e.g. resale instead of the agreed audience modelling) is **blocked at run
   time, not just flagged** — and a `purpose_bound` invariant lets a third party
   re-attest there was no purpose drift. (`parley/session.py`, `parley/policy.py`)
6. **First-party human gate, fail-closed.** `is_authorized_approver` is a boolean, not
   text-matched — only a first-party owner human may approve; an agent or a
   requester-side human is refused. (`parley/security/guard.py`)

**Real computation, not stubs.** An in-process clean room aggregates actual row-level
records (with PII) in place and exports **zero rows** — only k-anonymous counts
(`parley/cleanroom.py`, `proof/cleanroom.json`: 1000 rows → 24 cohorts, 0 exported);
`code_scan` runs a genuine in-place regex/AST secret+injection scan and returns only
`file:line:rule` locations (never source); `train_in_place` fits a real logistic
regression and reports a true held-out accuracy. Every capability routes through one
k-anonymity chokepoint, re-checked **after** DP noise.

## Deploy it for *your* two organizations

No code changes — edit one file.

1. **`scenario.yaml`** — set the buyer/owner org names, the four agent handles, the
   policy (`k_floor`, `owner_org`, `forbidden_columns`), and the owner's in-place
   dataset (`cohorts`). Everything org-specific lives here.
2. **`agent_config.yaml` / `.env`** — the Band Agent UUIDs + API keys for your four
   agents (register them at app.band.ai → Agents → New Agent → External Agent).
3. **Auth** — `claude login` (the agents think via your Claude subscription through the
   Claude Agent SDK; `ANTHROPIC_API_KEY` is unset per process).
4. Run by side — **two real operators, one command each** (see `JOIN.md`):
   - Operator A (Northwind/buyer): `uv run python scripts/run_org.py buyer` then `… run_demo.py`
   - Operator B (Lumen/owner): `uv run python scripts/run_org.py owner` (they are the human gate)

   Each operator runs only their org's agents, with only their org's creds — a genuine
   cross-org trust boundary. (Solo demo: run both sides yourself.) Point
   `PARLEY_SCENARIO=other.yaml` for several deployments.

## One kernel, any domain — see `examples/`

The same governance kernel (consent → counter-offer → owner-human gate → no-raw) works
for any data and any tools — **the same two orgs and the same four agents**, only the
domain/data/tool change (no new accounts):

| Example | Domain | The counter-offer | Capability |
|---|---|---|---|
| **`04_clinical_cohorts`** ⭐ | **Meridian (research) ↔ Lakeside Health — HIPAA** | **no patient records → in-place k-anon + DP cohort counts** | `cohort_aggregate` |
| `01_data_collaboration` | Northwind wants Lumen's customer data | no raw rows → in-place k-anon cohorts / in-place model training | `cohort_aggregate`, `train_in_place` |
| `02_code_review` | Northwind audits Lumen's private repo | no source → in-place static scan, return only findings | `code_scan` |
| `03_productivity_coaching` | Northwind (as a coach) reviews Lumen's HR data | no per-employee records → team-level metrics only | `productivity_metrics` |

Run any of them with `PARLEY_SCENARIO=examples/02_code_review.yaml …`. Add your own data
+ tools in `parley/capabilities.py`; the kernel is untouched.

## Proof — real runs, not simulated

All Band traffic is live against app.band.ai (no simulator). Re-run any of it:

```bash
bash scripts/demo.sh      # full suite + governed 3-domain run + third-party verify of every bundle
```

- `proof/spike-cross-org.json` — cross-org contact handshake + recruit
- `proof/spike-vault-counter.json` — the stranger's LLM declines + counter-offers
- `proof/live-proof.json` — full end-to-end negotiation + human gate + checker PASS
- `proof/spike-injection.json` — a prompt-injection attack refused
- `proof/cross-vendor-{groq,openrouter}.json` — the stranger reasons on a non-Claude model
- `proof/bundle-*.json` — Ed25519-signed bundles for every domain (re-attestable)

**Prove it cross-vendor** (the stranger reasons on a non-Claude model — one real
network call, no Band room needed):

```bash
uv sync --extra cross-vendor
export VAULT_LLM_VENDOR=groq GROQ_API_KEY=...   # free key: https://console.groq.com/keys
uv run python scripts/run_cross_vendor_demo.py  # → proof/cross-vendor-decision.json
```

**What's real vs. demo.** Real: two **separate Band organizations**
(@northwind-analytics ↔ @lumen-retail) with a genuine cross-org boundary — the owner
must accept the contact — and two independent operators run it out of the box
(`run_org.py buyer|owner` + `JOIN.md`); live Band traffic; the consent, counter-offer,
refusal and human gate are genuine LLM/Band events; the export gate, k-anonymity, DP/RDP
accountant and all signing/verify invariants are deterministic code under **124 tests**
(6 gated behind the `cross-vendor` extra). Demo-scoped: the owner's dataset is a seeded
cohort table in `scenario.yaml` aggregated by an in-process clean room (pluggable
real-clean-room backend on the roadmap); the *recorded* walkthrough was driven by one
operator holding both org accounts — the code runs two real operators unchanged.

## Safety — cross-org means untrusted input

Defense is **structural, not prompt-based** — the guarantee does not depend on
detecting the attack:

- **No row-emitting path**: every capability returns aggregates with `rows_exported: 0`
  by construction, so even a fully hijacked model cannot emit a row.
- **Hard human gate**: `is_authorized_approver` is a boolean, not text-matched.
- **Policy can only tighten**: `final = stricter_of(llm, policy)` overrules an injected
  "accept".

A **secondary tripwire** (`scan_injection`) flags/quarantines common and paraphrased
override/exfil/gate-bypass phrasing. It is best-effort by nature, which is exactly why
the structural guarantees above are the real defense: a phrase that slips the tripwire
still cannot extract a row or skip the human gate. (`parley/security/guard.py`,
`proof/spike-injection.json`)

## Agents remember and evolve agreements (Band Memory)

When the same counterparty returns, the vault recalls the terms it already agreed and
short-circuits the negotiation; `supersede` keeps a versioned audit chain when terms
change, via Band's cross-agent **Memory** API (`/agent/memories`). Band gates that API
to Enterprise plans, so Parley attempts the real API and **degrades gracefully to a
local JSONL store** when the plan blocks it (`parley/memory.py`, `proof/spike-memory.json`).

---

Licensed under MIT (see `LICENSE`).
