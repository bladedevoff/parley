"""Tests for the scenario.yaml config layer (deploy for any two orgs)."""

from __future__ import annotations

from parley.config import _derive_account
from parley.scenario import Scenario, load_scenario


def test_account_derivation_is_generic_no_hardcoded_orgs():
    # any org pair works — the account is just the handle's owner segment
    assert _derive_account("@acme/lead") == "acme"
    assert _derive_account("globex-hr/vault") == "globex-hr"
    assert _derive_account("@northwind-analytics/coordinator") == "northwind-analytics"
    assert _derive_account("@lumen-retail/vault") == "lumen-retail"


def test_default_scenario_matches_shipped_values():
    s = load_scenario()
    assert s.deal_id == "deal-1"
    assert s.k_floor == 25
    assert s.owner_org == "lumen"
    assert s.agent("coordinator") == "@northwind-analytics/coordinator"
    assert s.agent("vault") == "@lumen-retail/vault"
    # dataset has a sub-k_floor cohort to demonstrate suppression
    assert any(n < s.k_floor for n in s.cohorts.values())
    assert s.total_customers == sum(s.cohorts.values())


def test_dataset_is_buckets_only_no_identifiers():
    s = load_scenario()
    rec = s.dataset[0]
    assert set(rec.keys()) == {"bucket"}  # no raw identifiers in the data records


def test_scenario_drives_routing_and_policy():
    # the consumers read from the same scenario singleton
    from parley.tools.emit_consent import TARGET_CHECKER, TARGET_COORDINATOR
    from parley.common.prompts import VAULT_HANDLE, VAULT_PROMPT

    s = load_scenario()
    assert TARGET_COORDINATOR == s.agent("coordinator")
    assert TARGET_CHECKER == s.agent("checker")
    assert VAULT_HANDLE == s.agent("vault")
    # prompt is rendered from scenario (owner name + handle present)
    assert s.owner["name"] in VAULT_PROMPT
    assert s.agent("checker") in VAULT_PROMPT


def test_can_override_with_a_different_deployment(tmp_path):
    cfg = tmp_path / "other.yaml"
    cfg.write_text(
        "deal_id: deal-x\n"
        "buyer: {name: Acme, org: acme}\n"
        "owner: {name: Globex, org: globex}\n"
        "agents: {coordinator: '@acme/coord', modeler: '@acme/mod', checker: '@acme/chk', vault: '@globex/vault'}\n"
        "policy: {k_floor: 50, owner_org: globex, forbidden_columns: [name]}\n"
        "request: {raw_ask: x, aggregate_spec: y}\n"
        "cohorts: {'a': 60, 'b': 10}\n",
        encoding="utf-8",
    )
    s = load_scenario(cfg)
    assert s.agent("vault") == "@globex/vault"
    assert s.k_floor == 50
    assert s.owner_org == "globex"
    assert s.total_customers == 70
