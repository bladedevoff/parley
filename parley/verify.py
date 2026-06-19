"""parley.verify — re-attest a Parley deal bundle from public artifacts alone.

Any third party (the other org, a judge, an auditor) can run this against a
sealed bundle with ZERO trust in Parley. It recomputes every guarantee and exits
0 only if ALL hold; otherwise it names the failing invariant and exits 1.

    uv run python -m parley.verify proof/bundle-deal-1.json

Invariants checked:
  1. provenance chain intact + correctly ordered (hash chain re-attested)
  2. provenance is Ed25519-SIGNED and every receipt's signature validates against
     the published owner public key (forging needs the owner's private key)
  3. a first-party owner-human APPROVE is present and was accepted
  4. consent is the STRICTER of LLM + policy (policy never loosened the LLM)
  5. rows_exported == 0 (no raw rows ever left the owner)
  6. every released cohort count >= required_k (post-DP k-anonymity holds)
  7. DP budget was not exceeded (if differential privacy was used)
  8. purpose limitation held (if policy constrained purposes): the consent's
     purpose was permitted and the capability ran for that same purpose (no drift)

Pass ``owner_pubkey`` to ``attest`` to PIN a trusted owner key (out-of-band);
otherwise the bundle's published key is used, which still defeats any tamper that
lacks the owner's private key.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from parley.policy import stricter_of
from parley.provenance import load_pinned_pubkey, verify_chain


def _ran(cap_res: dict) -> bool:
    """True if a capability actually produced a result (i.e. it ran)."""
    return cap_res.get("status") == "ok" or bool(cap_res.get("result"))


def attest(bundle: dict, *, owner_pubkey: str | None = None) -> dict:
    checks: list[dict] = []

    def add(name, ok, detail):
        checks.append({"invariant": name, "ok": bool(ok), "detail": detail})

    # 1+2) provenance chain re-attested AND every receipt's Ed25519 signature
    # validated against a PINNED owner key (out-of-band). A bundle's self-published
    # key is NOT trusted on its own — otherwise a full re-sign forgery (attacker's
    # keypair + attacker pubkey in the bundle) would pass. The pin comes from the
    # caller (owner_pubkey=) or the committed owner-pubkey file.
    prov = bundle.get("provenance", {})
    bundle_pub = prov.get("public_key")
    pinned = owner_pubkey or load_pinned_pubkey()
    verify_key = pinned or bundle_pub  # still detect naive tamper even without a pin
    chain = verify_chain(prov.get("receipts", []), owner_pubkey=verify_key)
    add("provenance_chain_intact", chain["ok"], chain["reason"])
    trusted = bool(pinned) and bundle_pub == pinned and chain["ok"]
    if trusted:
        detail = f"signatures validate against PINNED owner key {pinned[:16]}..."
    elif not pinned:
        detail = "self-published key only -- pin the owner key out-of-band to trust it"
    else:
        detail = "bundle key does NOT match the pinned owner key (possible forgery)"
    add("provenance_signed", trusted, detail)

    # injection guard (defense-in-depth): a request flagged by the scanner must NOT
    # have produced a capability result — the kernel refuses it fail-closed.
    flags = bundle.get("injection_flags", []) or []
    cap_res = bundle.get("capability_result", {}) or {}
    ran = _ran(cap_res)
    add("injection_clean", not (flags and ran),
        f"flags={flags}; capability_ran={ran}" if flags else "no injection flags on the request")

    # 2) human gate — there may be multiple human_approve receipts (e.g. an agent's
    # attempt that was REFUSED, then the real owner-human). Require that an
    # ACCEPTED one exists from a first-party owner human, and that no non-owner
    # approval was ever accepted.
    owner = str(bundle.get("owner_org", "")).lower()
    approvals = [r.get("data", {}) for r in prov.get("receipts", []) if r.get("kind") == "human_approve"]
    accepted = [d for d in approvals if d.get("accepted")]
    good = [d for d in accepted if d.get("is_human") and str(d.get("org", "")).lower() == owner]
    bad_accept = [d for d in accepted if not (d.get("is_human") and str(d.get("org", "")).lower() == owner)]
    human_ok = bool(good) and not bad_accept
    detail = (f"accepted by {good[0].get('by')} (owner human)" if good else "no owner-human approval")
    if bad_accept:
        detail += f"; ILLEGAL accepted approval by {bad_accept[0].get('by')}"
    add("first_party_human_approve", human_ok, detail)

    # 3) consent not loosened by policy
    c = bundle.get("consent", {})
    expected = stricter_of(c.get("llm_decision", "accept"), c.get("policy_decision", "accept"))
    add("consent_is_stricter_of", c.get("final") == expected,
        f"final={c.get('final')} expected={expected}")

    # 4) zero raw rows
    cap = bundle.get("capability_result", {})
    add("rows_exported_zero", cap.get("rows_exported", 0) == 0,
        f"rows_exported={cap.get('rows_exported', 0)}")

    # 5) post-DP k-anonymity
    req_k = int(bundle.get("required_k", 0))
    rows = bundle.get("released_rows", []) or []
    bad = [r for r in rows if r.get("count", 0) < req_k]
    add("post_dp_k_anonymity", not bad,
        f"required_k={req_k}; {len(bad)} cohorts below floor" if bad else f"all cohorts >= {req_k}")

    # 6) DP budget not exceeded. Sound semantics: a RELEASE requires an allowed,
    # in-budget charge; a REFUSED charge (no release happened) trivially respects the
    # budget — that is the budget doing its job, not a violation.
    dp = bundle.get("dp", {})
    if dp:
        cap_res = bundle.get("capability_result", {}) or {}
        released = _ran(cap_res)
        ok = dp.get("remaining", 0) >= 0 and (dp.get("allowed", False) or not released)
        add("dp_within_budget", ok,
            f"epsilon={dp.get('epsilon')} allowed={dp.get('allowed')} "
            f"remaining={dp.get('remaining')} released={released}")

    # 7) purpose limitation (only when the policy constrained purposes): the
    # consented purpose was permitted AND the capability ran for that same purpose.
    allowed_purposes = set(bundle.get("allowed_purposes", []) or [])
    if allowed_purposes:
        consent_purpose = bundle.get("purpose")
        run_receipts = [r.get("data", {}) for r in prov.get("receipts", [])
                        if r.get("kind") == "capability_run"]
        run_purpose = run_receipts[0].get("purpose") if run_receipts else None
        in_scope = consent_purpose in allowed_purposes
        no_drift = (run_purpose is None) or (run_purpose == consent_purpose)
        add("purpose_bound", in_scope and no_drift,
            f"purpose='{consent_purpose}' allowed={sorted(allowed_purposes)} run='{run_purpose}'")

    all_ok = all(c["ok"] for c in checks)
    return {"ok": all_ok, "deal_id": bundle.get("deal_id"), "checks": checks}


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m parley.verify <bundle.json>")
        return 2
    bundle = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    res = attest(bundle)
    print(f"=== Parley bundle verification: {res['deal_id']} ===")
    for c in res["checks"]:
        print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['invariant']}: {c['detail']}")
    print("=" * 52)
    print("RESULT:", "VERIFIED -- all invariants hold" if res["ok"] else "FAILED -- see invariant above")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
