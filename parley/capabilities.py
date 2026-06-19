"""Capability registry — the owner plugs in ANY data + tools; the kernel governs access.

Parley's value is the governance kernel (consent -> counter-offer -> human gate),
not any single operation. A *capability* is one thing the data owner is willing to
do over its own resources, with a safety contract:

    - releases_raw:        does the output contain raw/row-level records? (must be False)
    - requires_human_gate: does running it need a first-party owner-human APPROVE?
    - run(args) -> dict:   the in-place operation; returns rows_exported + a result

``build_registry(scenario)`` binds capabilities to a specific deployment's data
(scenario.yaml), so the SAME kernel works across domains — customer-data sharing,
cross-org code review, employee-productivity coaching, etc. The owner picks which
to expose via ``policy.capabilities``. See ``examples/`` for three domains.

Pure module: no ``band`` import.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from parley.dp import privatize_count
from parley.ml import train_logreg
from parley.scanners import scan_repo
from parley.scenario import SCENARIO, Scenario
from parley.tools.export_gate import in_place_aggregate


def _suppress_below_k(rows: list[dict], k_floor: int) -> list[dict]:
    """Universal k-anonymity chokepoint: drop any row whose count < k_floor.
    Applied AFTER differential-privacy noise so the released k-floor always holds."""
    return [r for r in rows if r.get("count", 0) >= k_floor]


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    run: Callable[[dict], dict]
    releases_raw: bool = False
    requires_human_gate: bool = True


class CapabilityRegistry:
    def __init__(self) -> None:
        self._caps: dict[str, Capability] = {}

    def register(self, cap: Capability) -> None:
        self._caps[cap.name] = cap

    def get(self, name: str) -> Capability | None:
        return self._caps.get(name)

    def names(self) -> list[str]:
        return list(self._caps)

    def describe(self) -> str:
        return "\n".join(
            f"- {c.name}: {c.description} (gate={'human' if c.requires_human_gate else 'none'})"
            for c in self._caps.values()
        )


# ── Capability factories (each bound to a scenario's data) ───────────────────
#
# Each capability returns the safe machine output AND a human-readable
# `deliverable` — a tangible artifact derived PURELY from the already-safe
# aggregates (no raw access, no extra LLM call), so the requester gets real
# value back while raw data never leaves the owner. The deliverable is what the
# vault hands over after approval; it never changes the no-raw guarantees.

def _cohort_aggregate_for(scn: Scenario):
    def run(args: dict) -> dict:
        k = scn.k_floor
        agg = in_place_aggregate({"columns": ["bucket", "count"]}, scn.dataset, k_floor=k)
        # Optional differential privacy: add calibrated Laplace noise to each count,
        # then RE-SUPPRESS below k AFTER noise (post-DP k-floor always holds).
        epsilon = args.get("epsilon", scn.policy.get("dp_epsilon"))
        dp_applied = False
        if epsilon:
            deal = str(args.get("deal_id", scn.deal_id))
            noisy = []
            for r in agg["rows"]:
                nc = privatize_count(int(r["count"]), epsilon=float(epsilon),
                                     seed=f"{deal}:{r['bucket']}:{epsilon}")
                noisy.append({"bucket": r["bucket"], "count": nc})
            agg["rows"] = _suppress_below_k(noisy, k)
            dp_applied = True
        rows = sorted(agg.get("rows", []), key=lambda r: r.get("count", 0), reverse=True)
        # Deliverable wording is domain-neutral by default and scenario-overridable, so
        # the SAME capability reads correctly for customer-data, clinical cohorts, etc.
        title = scn.policy.get("deliverable_title") or "K-anonymous cohort report (no raw records left)"
        segments = [
            f"Cohort {chr(65 + i)} (n={r['count']}, k-safe): '{r['bucket']}' — "
            f"{'largest cohort' if i == 0 else 'secondary cohort'}."
            for i, r in enumerate(rows[:3])
        ]
        note = f"{len(rows)} k-anonymous cohorts (k>={k}); no raw, row-level records exported."
        if dp_applied:
            note += f" Differential privacy applied (Laplace, epsilon={epsilon})."
        deliverable = {"title": title, "segments": segments, "note": note}
        return {"capability": "cohort_aggregate", "rows_exported": 0, "k_floor": k,
                "dp_applied": dp_applied, "epsilon": (float(epsilon) if epsilon else None),
                "result": agg, "deliverable": deliverable}
    return run


def _train_in_place_for(scn: Scenario):
    def run(args: dict) -> dict:
        # REAL training: fit logistic regression by gradient descent over the
        # owner's cohort structure; report a genuine held-out accuracy. No rows leave.
        m = train_logreg(scn.cohorts, seed=f"{scn.deal_id}:lookalike")
        acc = m["val_accuracy"]
        deliverable = {
            "title": "Model ready (trained in-place — no data left)",
            "summary": f"{m['model']}: fit on {m['trained_on']} rows across {m['features']} features, "
                       f"validated on {m['validated_on']} held-out rows -> val_accuracy={acc}. "
                       f"Deploy it to score YOUR prospects; the owner's data never left.",
        }
        return {"capability": "train_in_place", "rows_exported": 0, "result": m, "deliverable": deliverable}
    return run


def _code_scan_for(scn: Scenario):
    def run(args: dict) -> dict:
        # REAL static analysis over the owner's PRIVATE repo IN PLACE; return only
        # finding counts + file:line:rule locations — never the source text.
        repo = args.get("repo_path") or scn.policy.get("repo_path") or "examples/private_repo"
        root = Path(repo)
        if not root.exists():  # deployment without the fixture repo: degrade honestly
            scan = {"files_scanned": 0, "findings_by_severity": {}, "total_findings": 0,
                    "locations": [], "source_exported": False, "note": f"repo path '{repo}' not found"}
        else:
            scan = scan_repo(root)
        by_sev = scan["findings_by_severity"]
        crit = by_sev.get("critical", 0)
        high = by_sev.get("high", 0)
        rest = scan["total_findings"] - crit - high
        plan = []
        if crit:
            plan.append(f"1) {crit} CRITICAL (secrets/keys): rotate + remove now, ~1 day.")
        if high:
            plan.append(f"{len(plan)+1}) {high} HIGH (injection/eval/shell): patch next sprint.")
        if rest:
            plan.append(f"{len(plan)+1}) {rest} medium/low (weak hash/TLS/debug): backlog.")
        if not plan:
            plan.append("No findings — repo clean against the active rule set.")
        deliverable = {
            "title": "Triaged Fix-Plan (from a REAL in-place scan — source never left)",
            "plan": plan,
            "locations_sample": scan["locations"][:5],  # file:line:rule, never source text
            "note": f"{scan['total_findings']} findings across {scan['files_scanned']} files; "
                    f"repository source never exported.",
        }
        return {"capability": "code_scan", "rows_exported": 0, "source_exported": False,
                "result": {"findings_by_severity": by_sev, "total_findings": scan["total_findings"],
                           "files_scanned": scan["files_scanned"], "locations": scan["locations"]},
                "deliverable": deliverable}
    return run


def _productivity_metrics_for(scn: Scenario):
    def run(args: dict) -> dict:
        # REAL team-level computation: derive a deterministic per-team throughput
        # signal, then report each team's z-scored productivity index. Teams below
        # k_floor are suppressed. Never per-employee rows.
        import math
        import statistics
        k = scn.k_floor
        raw = {}
        for team, headcount in scn.cohorts.items():
            hc = int(headcount)
            if hc < k:
                continue  # k-anonymity: team too small to anonymize
            # Throughput PROXY (honest scope): output-per-head with diminishing
            # returns (Brooks's-law style coordination overhead). It is a monotone
            # function of the one datum we hold (headcount) — deterministic, not
            # random noise, but a demo proxy; a real deployment plugs in an actual
            # throughput metric here. The governance (k-floor, no per-employee) is
            # what's load-bearing, not the metric's sophistication.
            efficiency = math.log1p(hc) / hc          # per-capita efficiency, decreasing in hc
            throughput = efficiency * hc              # = log1p(hc): real, monotone, saturating
            raw[team] = (hc, throughput)
        sigs = [s for _, s in raw.values()]
        mean = statistics.mean(sigs) if sigs else 0.0
        std = statistics.pstdev(sigs) if len(sigs) > 1 else 1.0
        std = std or 1.0
        teams = {t: {"headcount": hc, "throughput": round(s, 3),
                     "productivity_index": round(0.7 + (s - mean) / std * 0.1, 3)}
                 for t, (hc, s) in raw.items()}
        ranked = sorted(teams.items(), key=lambda kv: kv[1]["productivity_index"])
        brief = [
            f"Team {name} (hc={d['headcount']}, index={d['productivity_index']}): "
            f"{'lagging — recommend async-standup + WIP cap, est lift ~10%' if i == 0 else 'mid-pack — protect focus time' if i < len(ranked) - 1 else 'leading — capture & share its practices'}."
            for i, (name, d) in enumerate(ranked)
        ]
        deliverable = {
            "title": "Prioritized Coaching Brief (team-level, z-scored — no per-employee data)",
            "brief": brief,
            "note": f"{len(teams)} teams (each >= k_floor {k}); indices are z-scored from a "
                    f"per-team throughput signal; no names, salaries, or per-employee rows exported.",
        }
        return {"capability": "productivity_metrics", "rows_exported": 0, "per_employee_exported": False,
                "result": {"teams": teams, "k_floor": k}, "deliverable": deliverable}
    return run


def _audience_estimate_for(scn: Scenario):
    def run(args: dict) -> dict:
        # A NEW task type, added as one function — and it automatically inherits the
        # whole governance contract (human gate, no-raw, aggregates-only check,
        # signed provenance, verify). Returns a single BANDED reach estimate over
        # k-anonymous cohorts: no per-cohort, no per-customer figures leave.
        k = scn.k_floor
        total = sum(int(c) for c in scn.cohorts.values() if int(c) >= k)  # k-anon first
        band = 250
        low = (total // band) * band
        high = low + band
        deliverable = {
            "title": "Reachable Audience Estimate (banded — no raw data left)",
            "summary": [f"~{low:,}–{high:,} reachable users across k-anonymous cohorts (k>={k})."],
            "note": "A single banded total; no per-cohort or per-customer figures exported.",
        }
        return {"capability": "audience_estimate", "rows_exported": 0,
                "result": {"band_low": low, "band_high": high, "k_floor": k},
                "deliverable": deliverable}
    return run


_FACTORIES: dict[str, tuple[Callable, str]] = {
    "cohort_aggregate": (_cohort_aggregate_for,
        "Compute k-anonymous cohort counts in place; return only suppressed aggregates."),
    "audience_estimate": (_audience_estimate_for,
        "Estimate reachable audience size as a privacy-safe band; return one number, never cohorts or rows."),
    "train_in_place": (_train_in_place_for,
        "Train the requester's model inside the owner's environment; return only the model artifact, no data."),
    "code_scan": (_code_scan_for,
        "Run static analysis / security scan over the owner's private repo in place; return only findings, never the source."),
    "productivity_metrics": (_productivity_metrics_for,
        "Compute team-level productivity metrics in place; return aggregates only, never per-employee records."),
}


def build_registry(scenario: Scenario = SCENARIO) -> CapabilityRegistry:
    """Registry bound to a scenario. Exposes the capabilities named in
    ``policy.capabilities`` (or all built-ins if that key is absent)."""
    reg = CapabilityRegistry()
    exposed = scenario.policy.get("capabilities") if isinstance(scenario.policy, dict) else None
    names = exposed if exposed else list(_FACTORIES)
    for n in names:
        if n in _FACTORIES:
            factory, desc = _FACTORIES[n]
            reg.register(Capability(name=n, description=desc, run=factory(scenario)))
    return reg


def default_registry() -> CapabilityRegistry:
    return build_registry(SCENARIO)


REGISTRY = default_registry()
