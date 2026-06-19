"""Tests for hash-chained provenance + policy-as-code consent."""

from __future__ import annotations

from parley.policy import evaluate_policy, final_decision, stricter_of
from parley.provenance import ProvenanceChain, verify_chain


# ---- provenance ----

def _chain():
    c = ProvenanceChain(deal_id="deal-1")
    c.append("request", {"capability": "cohort_aggregate"}, actor="@northwind/modeler")
    c.append("counter", {"terms": "aggregates only; k>=25"}, actor="@lumen/vault")
    c.append("human_approve", {"deal_id": "deal-1"}, actor="@lumen (human)")
    c.append("capability_run", {"rows_exported": 0}, actor="@lumen/vault")
    c.append("checker", {"verdict": "PASS"}, actor="@northwind/checker")
    return c


def test_intact_chain_verifies():
    c = _chain()
    res = verify_chain(c.receipts)
    assert res["ok"] is True and res["broken_at"] is None


def test_tampering_a_step_is_detected():
    c = _chain()
    c.receipts[2]["data"]["deal_id"] = "deal-EVIL"  # tamper the human-approve step
    res = verify_chain(c.receipts)
    assert res["ok"] is False and res["broken_at"] == 2


def test_reordering_is_detected():
    c = _chain()
    c.receipts[1], c.receipts[2] = c.receipts[2], c.receipts[1]  # swap order
    res = verify_chain(c.receipts)
    assert res["ok"] is False


# ---- policy-as-code ----

def test_stricter_of_precedence():
    assert stricter_of("accept", "decline") == "decline"
    assert stricter_of("counter", "accept") == "counter"
    assert stricter_of("accept", "accept") == "accept"


def test_policy_declines_raw_and_identifiers():
    pol = {"owner_org": "lumen", "forbidden_columns": ["email", "ssn"], "min_k": 25,
           "allowed_capabilities": ["cohort_aggregate"]}
    r = evaluate_policy({"raw": True, "columns": ["email"]}, pol)
    assert r["decision"] == "decline"


def test_policy_overrules_a_hijacked_llm_accept():
    # even if the LLM says accept (e.g. prompt-injected), policy forces decline
    pol = {"owner_org": "lumen", "forbidden_columns": ["ssn"], "min_k": 25,
           "allowed_capabilities": ["cohort_aggregate"], "allow_raw": False}
    fd = final_decision("accept", {"raw": True, "columns": ["ssn"]}, pol)
    assert fd["final"] == "decline"
    assert fd["policy_overruled_llm"] is True


def test_policy_can_only_tighten_not_loosen():
    pol = {"owner_org": "lumen", "forbidden_columns": [], "min_k": 25,
           "allowed_capabilities": ["cohort_aggregate"]}
    # clean request: policy says accept, llm says decline -> stays decline (can't loosen)
    fd = final_decision("decline", {"capability": "cohort_aggregate", "k": 25}, pol)
    assert fd["final"] == "decline"
