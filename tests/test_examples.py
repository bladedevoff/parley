"""Every shipped example deploys the SAME kernel to a different domain, and every
capability it exposes returns aggregates only (no raw data) — proving generality."""

from __future__ import annotations

from pathlib import Path

import pytest

from parley.capabilities import build_registry
from parley.scenario import load_scenario
from parley.security.guard import assert_aggregates_only

EXAMPLES = sorted((Path(__file__).resolve().parent.parent / "examples").glob("*.yaml"))


def test_three_examples_ship():
    names = [p.name for p in EXAMPLES]
    assert any("data_collaboration" in n for n in names)
    assert any("code_review" in n for n in names)
    assert any("productivity" in n for n in names)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_capabilities_never_release_raw(path):
    scn = load_scenario(path)
    reg = build_registry(scn)
    # the registry exposes exactly what the scenario declares
    assert set(reg.names()) == set(scn.policy["capabilities"])
    assert reg.names(), f"{path.name} exposes no capabilities"
    for cap_name in reg.names():
        out = reg.get(cap_name).run({"deal_id": scn.deal_id})
        assert out["rows_exported"] == 0, f"{path.name}/{cap_name} leaked rows"
        assert "raw" not in out
        assert assert_aggregates_only(out) == [], f"{path.name}/{cap_name} failed safety check"


def test_code_review_returns_findings_not_source():
    scn = load_scenario(next(p for p in EXAMPLES if "code_review" in p.name))
    out = build_registry(scn).get("code_scan").run({"deal_id": scn.deal_id})
    assert out["source_exported"] is False
    assert out["result"]["total_findings"] > 0


def test_productivity_suppresses_tiny_teams_and_hides_individuals():
    scn = load_scenario(next(p for p in EXAMPLES if "productivity" in p.name))
    out = build_registry(scn).get("productivity_metrics").run({"deal_id": scn.deal_id})
    assert out["per_employee_exported"] is False
    teams = out["result"]["teams"]
    assert "Exec" not in teams          # 3 employees < k_floor 5 -> suppressed
    assert "Engineering" in teams
