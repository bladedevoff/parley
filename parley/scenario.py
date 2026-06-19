"""Deployment configuration — the single source of truth for which two orgs,
agents, data, and policy a Parley run uses.

Edit ``scenario.yaml`` (or point ``PARLEY_SCENARIO`` at another file) to deploy
Parley for a different pair of organizations — no code changes. A built-in
fallback mirrors the shipped scenario so the package still imports if the YAML
is missing. Pure module: no ``band`` import, safe to import in offline tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # pyyaml ships with band-sdk; fall back to the built-in if absent
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_REPO = Path(__file__).resolve().parent.parent
_DEFAULT_PATH = _REPO / "scenario.yaml"

# Built-in fallback (mirrors scenario.yaml) so imports never hard-fail.
_FALLBACK: dict[str, Any] = {
    "deal_id": "deal-1",
    "buyer": {"name": "Northwind Analytics", "org": "northwind", "goal": "build a lookalike audience model"},
    "owner": {"name": "Lumen Retail", "org": "lumen", "custodian_role": "data custodian for the customer database"},
    "agents": {
        "coordinator": "@northwind-analytics/coordinator",
        "modeler": "@northwind-analytics/modeler",
        "checker": "@northwind-analytics/checker",
        "vault": "@lumen-retail/vault",
    },
    "policy": {
        "k_floor": 25,
        "owner_org": "lumen",
        "forbidden_columns": ["name", "full_name", "email", "phone", "ssn", "customer_id"],
    },
    "request": {
        "raw_ask": "customer-level rows: age, income bracket, purchase frequency, category preferences, geo, browsing behavior",
        "aggregate_spec": "cohort counts by age band, income bracket, region; every cohort >= k_floor; no identifier columns; no raw rows",
    },
    "cohorts": {
        "age:18-24|region:west": 142,
        "age:25-34|region:west": 388,
        "age:25-34|region:east": 271,
        "age:35-44|region:central": 205,
        "age:45-54|region:east": 96,
        "age:55-64|region:west": 54,
        "age:65+|region:rural": 12,
    },
}


@dataclass(frozen=True)
class Scenario:
    deal_id: str
    buyer: dict
    owner: dict
    agents: dict
    policy: dict
    request: dict
    cohorts: dict

    def agent(self, role: str) -> str:
        """Band handle for a logical role (coordinator/modeler/checker/vault)."""
        return self.agents[role]

    @property
    def k_floor(self) -> int:
        return int(self.policy.get("k_floor", 25))

    @property
    def owner_org(self) -> str:
        return str(self.policy.get("owner_org", "lumen"))

    @property
    def forbidden_columns(self) -> list[str]:
        return list(self.policy.get("forbidden_columns", ["name", "email", "phone", "ssn"]))

    @property
    def dataset(self) -> list[dict]:
        """In-place owner data as one record per customer carrying only a cohort bucket."""
        return [{"bucket": c} for c, n in self.cohorts.items() for _ in range(int(n))]

    @property
    def total_customers(self) -> int:
        return sum(int(n) for n in self.cohorts.values())


def load_scenario(path: str | Path | None = None) -> Scenario:
    data: dict[str, Any] = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _FALLBACK.items()}
    p = Path(path or os.getenv("PARLEY_SCENARIO") or _DEFAULT_PATH)
    if yaml is not None and p.exists():
        loaded = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for k, v in loaded.items():
            data[k] = v
    return Scenario(
        deal_id=data["deal_id"],
        buyer=data["buyer"],
        owner=data["owner"],
        agents=data["agents"],
        policy=data["policy"],
        request=data["request"],
        cohorts=data["cohorts"],
    )


# Module-level singleton used across the package.
SCENARIO = load_scenario()
