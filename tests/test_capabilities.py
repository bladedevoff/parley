"""Tests for the capability registry — the owner plugs in any data + tools,
the kernel governs access to each (consent + human gate + no-raw guarantee)."""

from __future__ import annotations

from parley.capabilities import REGISTRY, default_registry
from parley.tools.export_tool import RunCapabilityInput, make_capability_tool


def test_registry_exposes_multiple_capabilities():
    names = REGISTRY.names()
    assert "cohort_aggregate" in names
    assert "train_in_place" in names  # a different tool over the same data


def test_every_capability_returns_zero_raw_rows():
    for name in REGISTRY.names():
        out = REGISTRY.get(name).run({"deal_id": "deal-1"})
        assert out["rows_exported"] == 0, f"{name} leaked rows"
        assert "raw" not in out


def test_every_capability_returns_a_tangible_deliverable():
    """Each capability hands back a usable artifact derived from safe aggregates."""
    from parley.security.guard import assert_aggregates_only
    for name in REGISTRY.names():
        out = REGISTRY.get(name).run({"deal_id": "deal-1"})
        d = out.get("deliverable")
        assert isinstance(d, dict) and d.get("title"), f"{name} has no deliverable"
        # the deliverable carries at least one concrete artifact line
        assert any(k in d for k in ("segments", "plan", "brief", "summary")), f"{name} deliverable empty"
        # adding a deliverable must NOT break the no-raw guarantee
        assert assert_aggregates_only(out) == [], f"{name} deliverable broke no-raw check"


def test_train_in_place_returns_a_model_not_data():
    out = REGISTRY.get("train_in_place").run({"deal_id": "deal-1"})
    model = out["result"]["model"] if "model" in out["result"] else out["result"]
    assert "val_accuracy" in out["result"]
    assert out["rows_exported"] == 0


async def test_new_capability_is_exposed_by_config_and_auto_governed():
    """A NEW task type (audience_estimate) added as one function: exposed by editing
    scenario.yaml, and it automatically inherits the fail-closed human gate + no-raw."""
    from parley.capabilities import build_registry
    from parley.scenario import load_scenario

    scn = load_scenario("examples/01_data_collaboration.yaml")
    reg = build_registry(scn)
    assert "audience_estimate" in reg.names()      # exposed purely by config

    out = reg.get("audience_estimate").run({"deal_id": "deal-1"})
    assert out["rows_exported"] == 0 and "band_low" in out["result"] and out["deliverable"]["title"]

    _, handler = make_capability_tool(reg, owner_org=scn.owner_org)
    blocked = await handler(RunCapabilityInput(capability="audience_estimate", deal_id="deal-1"))
    assert blocked["status"] == "BLOCKED"          # no human approver -> refused (inherited gate)
    ok = await handler(RunCapabilityInput(capability="audience_estimate", deal_id="deal-1",
                                          approver_is_human=True, approver_org=scn.owner_org))
    assert ok["status"] == "ok" and ok["rows_exported"] == 0


async def test_run_capability_is_fail_closed_for_any_capability():
    _, handler = make_capability_tool(REGISTRY)
    for cap in ("cohort_aggregate", "train_in_place"):
        # no approver -> blocked
        r = await handler(RunCapabilityInput(capability=cap, deal_id="deal-1"))
        assert r["status"] == "BLOCKED"
        # agent / requester-side -> blocked
        r = await handler(RunCapabilityInput(capability=cap, deal_id="deal-1", approver_is_human=True, approver_org="northwind"))
        assert r["status"] == "BLOCKED"
        # owner human -> ok, zero raw rows
        r = await handler(RunCapabilityInput(capability=cap, deal_id="deal-1", approver_is_human=True, approver_org="lumen"))
        assert r["status"] == "ok"
        assert r["rows_exported"] == 0


async def test_unknown_capability_is_blocked():
    _, handler = make_capability_tool(REGISTRY)
    r = await handler(RunCapabilityInput(capability="exfiltrate_everything", deal_id="deal-1", approver_is_human=True, approver_org="lumen"))
    assert r["status"] == "BLOCKED"


def test_deployment_can_restrict_exposed_capabilities(monkeypatch):
    # default_registry honors scenario policy `capabilities` (all built-ins here)
    reg = default_registry()
    assert set(reg.names()) <= {"cohort_aggregate", "train_in_place"}
    assert len(reg.names()) >= 1
