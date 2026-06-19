"""Policy-as-code consent — a deterministic gate that can only make the LLM STRICTER.

Practitioners love policy-as-code but "no one wants to write Rego". Parley's
owner policy is a plain dict (authorable by compliance/legal, not engineers) and
is evaluated in pure Python — no Rego, no dependency. The final decision is
``stricter_of(llm_decision, policy_decision)``: the data owner's policy can veto
or downgrade the vault LLM's call but never loosen it. This is the enforcement
layer A2A explicitly lacks, and it makes consent immune to prompt injection — a
hijacked LLM that says "accept" is overruled by the policy that says "decline".

Pure: stdlib only, no band import.
"""

from __future__ import annotations

from typing import Any

# decision precedence: stricter wins (decline > counter > accept).
_RANK = {"decline": 2, "counter": 1, "accept": 0}


def stricter_of(a: str, b: str) -> str:
    """Return the stricter of two decisions (decline > counter > accept)."""
    return a if _RANK.get(a, 0) >= _RANK.get(b, 0) else b


def evaluate_policy(request: dict, policy: dict) -> dict:
    """Evaluate the owner's declarative policy against a data request.

    request: {capability, columns?, raw?, purpose?, k?}
    policy:  {owner_org, forbidden_columns, allowed_capabilities, allowed_purposes?,
              min_k, allow_raw=False}
    Returns {decision: accept|decline|counter, reasons: [...], required_k}.
    """
    reasons: list[str] = []
    decision = "accept"

    forbidden = {c.lower() for c in policy.get("forbidden_columns", [])}
    cols = [str(c).lower() for c in (request.get("columns") or [])]
    allowed_caps = set(policy.get("allowed_capabilities", []))
    min_k = int(policy.get("min_k", 0))

    # 1) raw / row-level export is never allowed unless policy explicitly opts in.
    if request.get("raw") and not policy.get("allow_raw", False):
        reasons.append("raw/row-level export is forbidden by policy")
        decision = stricter_of(decision, "decline")

    # 2) direct identifiers -> decline.
    leaked = [c for c in cols if any(f in c for f in forbidden)]
    if leaked:
        reasons.append(f"request names forbidden identifier columns: {leaked}")
        decision = stricter_of(decision, "decline")

    # 3) capability must be one the owner exposes; else counter toward an allowed one.
    cap = request.get("capability")
    if cap and allowed_caps and cap not in allowed_caps:
        reasons.append(f"capability '{cap}' not exposed; allowed: {sorted(allowed_caps)}")
        decision = stricter_of(decision, "counter")

    # 4) purpose limitation (if the policy constrains purposes).
    purposes = set(policy.get("allowed_purposes", []))
    if purposes and request.get("purpose") and request["purpose"] not in purposes:
        reasons.append(f"purpose '{request['purpose']}' not permitted")
        decision = stricter_of(decision, "decline")

    # 5) k-anonymity floor: if the request asks for a smaller k than policy, counter up.
    req_k = request.get("k")
    if req_k is not None and int(req_k) < min_k:
        reasons.append(f"requested k={req_k} below policy floor {min_k}")
        decision = stricter_of(decision, "counter")

    if not reasons:
        reasons.append("request satisfies all policy rules")
    return {"decision": decision, "reasons": reasons, "required_k": min_k}


def final_decision(llm_decision: str, request: dict, policy: dict) -> dict:
    """Combine the vault LLM's decision with policy — policy can only tighten it."""
    pol = evaluate_policy(request, policy)
    final = stricter_of(llm_decision, pol["decision"])
    overruled = final != llm_decision
    return {
        "final": final,
        "llm_decision": llm_decision,
        "policy_decision": pol["decision"],
        "policy_overruled_llm": overruled,
        "reasons": pol["reasons"],
        "required_k": pol["required_k"],
    }
