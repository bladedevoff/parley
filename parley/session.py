"""DealSession — the governance kernel as one orchestrated, verifiable flow.

Ties together every original feature into a single deal lifecycle that produces a
tamper-evident, third-party-verifiable proof bundle:

  request -> policy-gated consent (stricter_of LLM + policy) -> human gate
          -> DP-budget charge -> capability run -> checker -> sealed bundle

Every step is appended to a hash-chained provenance record; the bundle can be
re-attested offline by parley.verify with zero trust in Parley. Pure: no band
import — this is the deterministic core the live Band agents drive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from parley.dp import EpsilonBudget
from parley.policy import final_decision
from parley.provenance import ProvenanceChain, load_or_create_owner_key
from parley.security.guard import is_authorized_approver, scan_injection
from parley.tools.validator import validate_aggregates


@dataclass
class DealSession:
    deal_id: str
    counterparty: str
    owner_org: str
    policy: dict
    registry: Any
    budget: Optional[EpsilonBudget] = None
    chain: ProvenanceChain = field(init=False)

    def __post_init__(self):
        # The chain is signed with the data owner's PERSISTENT Ed25519 key (loaded
        # from a gitignored file; public half committed for out-of-band pinning), so
        # a third party re-attests every receipt against the PINNED owner key — a full
        # re-sign forgery with the attacker's own key cannot pass.
        self.chain = ProvenanceChain(self.deal_id, signing_key=load_or_create_owner_key())
        self._consent: dict = {}
        self._human_ok = False
        self._dp: dict = {}
        self._purpose: Optional[str] = None
        self._run_purpose: Optional[str] = None

    # 1) requester asks. Because the counterparty is from ANOTHER org, the request
    # is untrusted input: scan it for prompt-injection / exfiltration / gate-bypass
    # signals IN THE KERNEL (not just in a spike) and record the flags as evidence.
    def request(self, req: dict) -> None:
        import json
        flags = scan_injection(json.dumps(req, default=str, ensure_ascii=False))
        self._injection_flags = flags
        self.chain.append("request", {**req, "injection_flags": flags},
                          actor=f"@{self.counterparty} requester")

    # 2) consent = the STRICTER of the vault LLM's call and the owner policy.
    # The consent is BOUND to the request's stated purpose (purpose limitation).
    def decide_consent(self, llm_decision: str, req: dict) -> dict:
        fd = final_decision(llm_decision, req, self.policy)
        self._consent = fd
        if req.get("purpose"):
            self._purpose = req["purpose"]
        self.chain.append("consent", {**fd, "purpose": self._purpose},
                          actor=f"@{self.owner_org}/vault")
        return fd

    # 3) first-party owner human gate (an agent's APPROVE is refused)
    def human_approve(self, *, sender_is_human: bool, sender_org: str, by: str) -> bool:
        ok = is_authorized_approver(sender_is_human=sender_is_human,
                                    sender_org=sender_org, owner_org=self.owner_org)
        self._human_ok = ok
        self.chain.append("human_approve",
                          {"by": by, "is_human": sender_is_human, "org": sender_org, "accepted": ok},
                          actor=by)
        return ok

    # 4) run the capability (DP charge if applicable) — only if consent+human ok
    def run_capability(self, capability: str, *, epsilon: Optional[float] = None,
                       purpose: Optional[str] = None) -> dict:
        if self._consent.get("final") == "decline":
            return {"status": "BLOCKED", "reason": "consent declined by policy/LLM"}
        if not self._human_ok:
            return {"status": "BLOCKED", "reason": "no first-party owner-human approval"}
        # Fail-closed on a hostile request: if the request tripped the injection /
        # exfiltration / gate-bypass scanner, REFUSE regardless of consent or the
        # LLM — exactly what guard.scan_injection's contract promises. (Detection
        # alone is not enough; this makes it enforcement.)
        if getattr(self, "_injection_flags", []):
            self.chain.append("injection_block",
                              {"flags": self._injection_flags, "capability": capability},
                              actor=f"@{self.owner_org}/vault")
            return {"status": "BLOCKED", "reason": f"request flagged {self._injection_flags}; "
                    "refused fail-closed (prompt-injection / exfiltration guard)"}
        cap = self.registry.get(capability)
        if cap is None:
            return {"status": "BLOCKED", "reason": f"unknown capability {capability}"}

        # Purpose limitation (GDPR Art. 5(1)(b)): a consent is bound to its stated
        # purpose. Running it for an unpermitted purpose — or a DIFFERENT purpose
        # than was consented (purpose drift) — is blocked here, end-to-end, not
        # just flagged at policy time. Addresses the "overbroad access scopes"
        # weakness named for agent protocols (cf. arXiv:2505.12490).
        allowed_purposes = set(self.policy.get("allowed_purposes", []))
        run_purpose = purpose if purpose is not None else self._purpose
        if allowed_purposes:
            if not run_purpose:
                return {"status": "BLOCKED",
                        "reason": "policy requires a stated purpose (purpose limitation)"}
            if run_purpose not in allowed_purposes:
                return {"status": "BLOCKED",
                        "reason": f"purpose '{run_purpose}' not permitted; allowed {sorted(allowed_purposes)}"}
        if self._purpose and run_purpose and run_purpose != self._purpose:
            return {"status": "BLOCKED",
                    "reason": f"purpose drift: consented for '{self._purpose}', run for '{run_purpose}'"}
        self._run_purpose = run_purpose

        eps = epsilon if epsilon is not None else self.policy.get("dp_epsilon")
        if eps and self.budget is not None:
            charge = self.budget.charge(self.counterparty, float(eps))
            self._dp = {"epsilon": float(eps), **charge}
            self.chain.append("dp_charge", self._dp, actor=f"@{self.owner_org}/vault")
            if not charge["allowed"]:
                return {"status": "BLOCKED", "reason": charge["reason"], "dp": self._dp}

        out = cap.run({"deal_id": self.deal_id, "epsilon": eps})
        self.chain.append("capability_run",
                          {"capability": capability, "rows_exported": out.get("rows_exported", 0),
                           "purpose": run_purpose},
                          actor=f"@{self.owner_org}/vault")
        self._last = out
        return {"status": "ok", **out}

    # 5) checker validates the released aggregates
    def check(self, k_floor: int) -> dict:
        out = getattr(self, "_last", {})
        agg = out.get("result", {})
        rows = agg.get("rows") if isinstance(agg, dict) else None
        if rows is not None:
            verdict = validate_aggregates({"columns": agg.get("columns", ["bucket", "count"]), "rows": rows},
                                          ["bucket", "count"], k_floor=k_floor)
        else:
            # non-cohort capabilities (model/scan/metrics): pass if no rows exported
            verdict = {"verdict": "PASS" if out.get("rows_exported", 0) == 0 else "BLOCKED", "findings": []}
        self._checker = verdict
        self.chain.append("checker", verdict, actor=f"@{self.owner_org.replace('lumen','northwind')}/checker")
        return verdict

    # 6) seal a verifiable bundle
    def bundle(self) -> dict:
        out = getattr(self, "_last", {})
        agg = out.get("result", {}) if isinstance(out.get("result"), dict) else {}
        return {
            "deal_id": self.deal_id,
            "counterparty": self.counterparty,
            "owner_org": self.owner_org,
            "consent": self._consent,
            "human_gate": {"accepted": self._human_ok},
            "purpose": self._purpose,
            "allowed_purposes": list(self.policy.get("allowed_purposes", [])),
            "injection_flags": getattr(self, "_injection_flags", []),
            "dp": self._dp,
            "capability_result": out,
            "checker": getattr(self, "_checker", {}),
            "required_k": int(self.policy.get("min_k", self.policy.get("k_floor", 0))),
            "released_rows": agg.get("rows", []),
            "provenance": self.chain.to_dict(),
        }
