"""Offline end-to-end governed deal — exercises EVERY original feature, no Band needed.

Runs the full kernel for each example scenario through DealSession (policy-gated
consent, owner-human gate, DP budget, real capability, checker, hash-chained
provenance) and writes a verifiable bundle to proof/bundle-<deal>.json. Then run:

    uv run python -m parley.verify proof/bundle-deal-1.json

This is the deterministic, VPN-safe, judge-runnable proof of the substance. The
live Band run (cross-org contacts/@mentions) is separate evidence in proof/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parley.capabilities import build_registry
from parley.dp import EpsilonBudget, RDPAccountant, RDPBudget
from parley.scenario import load_scenario
from parley.session import DealSession

SCENARIOS = [
    ("examples/01_data_collaboration.yaml", "cohort_aggregate"),
    ("examples/02_code_review.yaml", "code_scan"),
    ("examples/03_productivity_coaching.yaml", "productivity_metrics"),
    ("examples/04_clinical_cohorts.yaml", "cohort_aggregate"),  # flagship regulated vertical (HIPAA)
]


def policy_from(scn) -> dict:
    p = dict(scn.policy)
    p.setdefault("min_k", scn.k_floor)
    p["allowed_capabilities"] = scn.policy.get("capabilities", [])
    return p


def run_one(path: str, capability: str) -> dict:
    scn = load_scenario(path)
    reg = build_registry(scn)
    pol = policy_from(scn)
    budget = EpsilonBudget(total_epsilon=3.0)
    s = DealSession(deal_id=scn.deal_id, counterparty=scn.buyer["org"],
                    owner_org=scn.owner_org, policy=pol, registry=reg, budget=budget)

    # 1) requester asks for RAW (policy will force a counter/decline)
    s.request({"capability": capability, "raw": True,
               "columns": scn.policy.get("forbidden_columns", []), "purpose": "analysis"})
    # 2) vault LLM (simulated here as 'counter') + policy => stricter final
    s.decide_consent("counter", {"capability": capability, "raw": True,
                                 "columns": scn.policy.get("forbidden_columns", [])})
    # requester revises to a clean aggregate request; consent re-decided -> accept.
    # The consent is BOUND to a permitted purpose (purpose limitation), if the
    # policy constrains purposes; examples without allowed_purposes pass purpose=None.
    purpose = (scn.policy.get("allowed_purposes") or [None])[0]
    s.request({"capability": capability, "raw": False, "columns": ["bucket", "count"],
               "k": scn.k_floor, "purpose": purpose})
    s.decide_consent("accept", {"capability": capability, "raw": False,
                                "columns": ["bucket", "count"], "k": scn.k_floor, "purpose": purpose})
    # 3) an AGENT tries to approve (must be refused), then the owner human approves
    agent_try = s.human_approve(sender_is_human=False, sender_org=scn.buyer["org"], by=f"@{scn.buyer['org']}/coordinator")
    assert agent_try is False, "agent approval must be refused"
    human_ok = s.human_approve(sender_is_human=True, sender_org=scn.owner_org, by=f"@{scn.owner_org} DPO (human)")
    # 4) run capability (DP applies to cohort_aggregate via scenario dp_epsilon if set)
    s.run_capability(capability, purpose=purpose)
    # 5) checker
    s.check(scn.k_floor)
    bundle = s.bundle()

    Path("proof").mkdir(exist_ok=True)
    out = f"proof/bundle-{scn.deal_id}.json"
    Path(out).write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"deal": scn.deal_id, "capability": capability, "final_consent": bundle["consent"]["final"],
            "agent_approve_refused": agent_try is False, "human_ok": human_ok,
            "checker": bundle["checker"].get("verdict"), "bundle": out}


def dp_composition_demo() -> dict:
    """Show the DP epsilon-budget COMPOSING across repeated deals with the SAME
    counterparty until it is exhausted and the vault is mechanically forced to
    DECLINE — the flagship feature, lit up end-to-end and captured in a bundle."""
    scn = load_scenario("examples/01_data_collaboration.yaml")
    reg = build_registry(scn)
    pol = policy_from(scn)
    eps = float(scn.policy.get("dp_epsilon", 1.0))
    budget = EpsilonBudget(total_epsilon=float(scn.policy.get("dp_total_budget", 2.5)))
    runs = []
    last_session = None
    for i in range(1, 5):  # repeated queries by the same counterparty
        s = DealSession(deal_id=f"{scn.deal_id}-q{i}", counterparty=scn.buyer["org"],
                        owner_org=scn.owner_org, policy=pol, registry=reg, budget=budget)
        purpose = (scn.policy.get("allowed_purposes") or [None])[0]
        s.decide_consent("accept", {"capability": "cohort_aggregate", "raw": False,
                                    "columns": ["bucket", "count"], "k": scn.k_floor, "purpose": purpose})
        s.human_approve(sender_is_human=True, sender_org=scn.owner_org, by=f"@{scn.owner_org} DPO (human)")
        out = s.run_capability("cohort_aggregate", epsilon=eps, purpose=purpose)
        runs.append({"query": i, "status": out["status"],
                     "remaining": budget.state(scn.buyer["org"]).remaining,
                     "reason": out.get("reason")})
        last_session = s
    # capture the final (exhausted) session's bundle as proof
    bundle = last_session.bundle()
    Path("proof").mkdir(exist_ok=True)
    Path("proof/dp-composition.json").write_text(
        json.dumps({"runs": runs, "final_bundle": bundle}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"runs": runs}


def purpose_violation_demo() -> dict:
    """Purpose limitation in action: the SAME approved deal is re-used for a
    DIFFERENT purpose than was consented (e.g. resale/ad-targeting instead of the
    agreed audience_modeling). The kernel BLOCKS it — consent is bound to purpose."""
    scn = load_scenario("examples/01_data_collaboration.yaml")
    reg = build_registry(scn)
    pol = policy_from(scn)
    allowed = (scn.policy.get("allowed_purposes") or ["audience_modeling"])[0]
    budget = EpsilonBudget(total_epsilon=5.0)
    s = DealSession(deal_id=f"{scn.deal_id}-purpose", counterparty=scn.buyer["org"],
                    owner_org=scn.owner_org, policy=pol, registry=reg, budget=budget)
    s.decide_consent("accept", {"capability": "cohort_aggregate", "raw": False,
                                "columns": ["bucket", "count"], "k": scn.k_floor, "purpose": allowed})
    s.human_approve(sender_is_human=True, sender_org=scn.owner_org, by=f"@{scn.owner_org} DPO (human)")
    ok = s.run_capability("cohort_aggregate", purpose=allowed)               # consented purpose -> ok
    drift = s.run_capability("cohort_aggregate", purpose="resale_to_third_party")  # different -> BLOCKED
    out = {"allowed_purpose": allowed, "consented_run": ok["status"],
           "drifted_run": drift["status"], "drift_reason": drift.get("reason")}
    Path("proof").mkdir(exist_ok=True)
    Path("proof/purpose-violation.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def rdp_vs_linear_demo() -> dict:
    """Show ADVANCED (Rényi-DP) composition answers MORE queries than naive linear
    composition for the SAME (epsilon, delta) budget — the modern DP accountant."""
    budget_eps, delta, sigma = 3.0, 1e-5, 4.0
    # Like-for-like: the SAME Gaussian mechanism and the SAME delta on both sides.
    # per-query epsilon at this delta:
    one = RDPAccountant(); one.compose(noise_multiplier=sigma, count=1)
    eps1 = one.spent_epsilon(delta)
    # baseline = NAIVE LINEAR SUMMATION of that per-query epsilon (k * eps1):
    linear_fits = int(budget_eps // eps1)
    # RDP advanced composition: compose in Rényi space, convert at the same delta:
    rb = RDPBudget(epsilon=budget_eps, delta=delta)
    rdp_fits = 0
    while rb.charge("northwind", noise_multiplier=sigma)["allowed"]:
        rdp_fits += 1
    # actual RDP epsilon for the SAME number of queries the linear baseline allowed:
    same = RDPAccountant(); same.compose(noise_multiplier=sigma, count=max(linear_fits, 1))
    rdp_eps_for_linear_count = same.spent_epsilon(delta)
    out = {"mechanism": "Gaussian", "noise_multiplier": sigma,
           "budget_epsilon": budget_eps, "delta": delta,
           "per_query_epsilon_at_delta": round(eps1, 4),
           "baseline": "naive linear summation of per-query epsilon (k * eps1), same delta",
           "linear_summation_fits": linear_fits,
           "rdp_advanced_composition_fits": rdp_fits,
           "rdp_epsilon_for_the_linear_count": round(rdp_eps_for_linear_count, 4),
           "improvement_x": round(rdp_fits / max(linear_fits, 1), 2),
           "note": "Apples-to-apples: identical mechanism and delta on both sides; "
                   "RDP composes additively in Renyi space then converts, beating the linear sum."}
    Path("proof").mkdir(exist_ok=True)
    Path("proof/rdp-composition.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def cleanroom_demo() -> dict:
    """Aggregate ACTUAL row-level records in place and prove zero rows leave."""
    from parley.cleanroom import aggregate_in_place, synthesize_customers
    rows = synthesize_customers(1000, seed="lumen")
    out = aggregate_in_place(rows, k_floor=25, epsilon=1.0, seed="deal-1")
    summary = {"rows_scanned": out["rows_scanned"], "rows_exported": out["rows_exported"],
               "cohorts_released": out["cohorts_released"], "k_floor": out["k_floor"],
               "dp_applied": out["dp_applied"], "released": out["rows"]}
    Path("proof").mkdir(exist_ok=True)
    Path("proof/cleanroom.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    print("=== Parley governed end-to-end (offline, all original features) ===")
    for path, cap in SCENARIOS:
        r = run_one(path, cap)
        print(f"  {r['deal']:9} {cap:22} consent={r['final_consent']:7} "
              f"agentApproveRefused={r['agent_approve_refused']} human={r['human_ok']} "
              f"checker={r['checker']} -> {r['bundle']}")
    print("\n=== DP budget composition (same counterparty, repeated queries) ===")
    comp = dp_composition_demo()
    for r in comp["runs"]:
        print(f"  query {r['query']}: {r['status']:7} remaining_epsilon={r['remaining']}"
              + (f"  ({r['reason']})" if r.get("reason") else ""))
    print("  -> proof/bundle-dp-composition.json")

    print("\n=== Purpose limitation (consent bound to its stated purpose) ===")
    pv = purpose_violation_demo()
    print(f"  consented purpose '{pv['allowed_purpose']}': {pv['consented_run']}")
    print(f"  re-used for 'resale_to_third_party': {pv['drifted_run']}  ({pv['drift_reason']})")
    print("  -> proof/purpose-violation.json")

    print("\n=== DP composition: advanced (Renyi/RDP) vs linear, same (epsilon,delta) ===")
    rc = rdp_vs_linear_demo()
    print(f"  budget epsilon={rc['budget_epsilon']} delta={rc['delta']} sigma={rc['noise_multiplier']}: "
          f"linear-sum fits {rc['linear_summation_fits']} queries, "
          f"RDP fits {rc['rdp_advanced_composition_fits']} ({rc['improvement_x']}x more, same delta)")
    print("  -> proof/rdp-composition.json")

    print("\n=== In-process clean room (aggregate real rows, export zero) ===")
    cr = cleanroom_demo()
    print(f"  scanned {cr['rows_scanned']} row-level records -> {cr['cohorts_released']} "
          f"k-anon cohorts (k>={cr['k_floor']}, DP={cr['dp_applied']}); rows_exported={cr['rows_exported']}")
    print("  -> proof/cleanroom.json")
    print("\nVerify any bundle:  uv run python -m parley.verify proof/bundle-deal-1.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
