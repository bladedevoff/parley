"""Offline end-to-end scenarios driven by JSON fixtures. No band import.

Each fixture in ``fixtures/`` drives the SAME pure code paths the live agents
use (emit_consent / export_gate / validator / human_gate), so the safety
invariants are exercised without the SDK or any network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parley.tools.emit_consent import (
    TARGET_COORDINATOR,
    EmitConsentInput,
    handle_emit_consent,
)
from parley.tools.export_gate import (
    ConsentMissing,
    ExportTool,
    in_place_aggregate,
)
from parley.tools.human_gate import parse_human_ack
from parley.tools.validator import validate_aggregates
from parley.state import DealState

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _emit_input(emit: dict) -> EmitConsentInput:
    return EmitConsentInput(
        decision=emit["decision"],
        rationale=emit["rationale"],
        counter_terms=emit.get("counter_terms"),
        confidence=emit["confidence"],
    )


async def test_forced_decline_never_exports():
    fx = _load("forced_decline.json")
    deal_id = fx["deal_id"]
    state = DealState()

    result = await handle_emit_consent(
        _emit_input(fx["emit"]), deal_id=deal_id, post=None, state=state
    )

    assert result["status"] == fx["expected"]["emit_status"] == "ok"
    assert result["decision"] == "decline"
    assert result["target"] == fx["expected"]["target"] == TARGET_COORDINATOR

    # A decline never acks the deal, so any destructive export must be blocked.
    assert fx["expected"]["export_attempted"] is False
    assert state.is_acked(deal_id) is False

    export = ExportTool(name="raw_record_export", run=lambda **kw: kw, destructive=True)
    with pytest.raises(ConsentMissing):
        export.guarded_run(human_ack=state.is_acked(deal_id), table="customers")


async def test_forced_counter_then_accept_with_human_ack():
    fx = _load("forced_counter.json")
    deal_id = fx["deal_id"]
    state = DealState()

    # 1) Counter routes to the coordinator and records the counter terms.
    counter = await handle_emit_consent(
        _emit_input(fx["emit"]), deal_id=deal_id, post=None, state=state
    )
    assert counter["status"] == "ok"
    assert counter["decision"] == "counter"
    assert counter["target"] == fx["expected"]["counter_target"] == TARGET_COORDINATOR
    assert state.get(deal_id)["terms"] == fx["emit"]["counter_terms"]

    # The counter envelope round-trips.
    from parley.envelope import parse_consent_envelope

    parsed = parse_consent_envelope(counter["envelope"])
    assert parsed is not None
    assert parsed["decision"] == "counter"
    assert parsed["terms"] == fx["emit"]["counter_terms"]

    # 2) Before any accept + human ack, export is blocked.
    assert fx["expected"]["export_blocked_before_ack"] is True
    aggregate_fx = fx["aggregate"]

    def runner(**kwargs):
        return in_place_aggregate(
            kwargs.get("query"), kwargs.get("dataset"), kwargs.get("k_floor", 25)
        )

    export = ExportTool(name="aggregate_export", run=runner, destructive=True)
    assert state.is_acked(deal_id) is False
    with pytest.raises(ConsentMissing):
        export.guarded_run(
            human_ack=state.is_acked(deal_id),
            query=aggregate_fx["query"],
            dataset=aggregate_fx["dataset"],
            k_floor=aggregate_fx["k_floor"],
        )

    # 3) Accept reports to the coordinator/liaison.
    accept = await handle_emit_consent(
        _emit_input(fx["accept_after_counter"]), deal_id=deal_id, post=None, state=state
    )
    assert accept["status"] == "ok"
    assert accept["decision"] == "accept"
    assert accept["target"] == fx["expected"]["accept_target"] == TARGET_COORDINATOR

    # 4) A human APPROVE flips the ack flag.
    ack = parse_human_ack(
        f"{fx['human_ack']['action']} {fx['human_ack']['deal_id']}",
        sender_is_human=True,
    )
    assert ack == {"action": "APPROVE", "deal_id": deal_id}
    state.set_human_ack(deal_id, ack["action"] == "APPROVE")
    assert state.is_acked(deal_id) is True

    # 5) Now the (aggregate-only) export runs — and still exports zero rows.
    out = export.guarded_run(
        human_ack=state.is_acked(deal_id),
        query=aggregate_fx["query"],
        dataset=aggregate_fx["dataset"],
        k_floor=aggregate_fx["k_floor"],
    )
    assert out["rows_exported"] == fx["expected"]["rows_exported"] == 0
    for row in out["rows"]:
        assert set(row.keys()) == {"bucket", "count"}
        assert row["count"] >= aggregate_fx["k_floor"]


async def test_poison_raw_export_raises_consent_missing_and_validator_blocks():
    fx = _load("poison_raw_export.json")
    deal_id = fx["deal_id"]
    state = DealState()

    # An adversarial accept does NOT constitute human consent on its own.
    accept = await handle_emit_consent(
        _emit_input(fx["emit"]), deal_id=deal_id, post=None, state=state
    )
    assert accept["status"] == "ok"
    assert state.is_acked(deal_id) is False  # no human ever approved

    # The destructive raw export attempt is rejected by the gate.
    export_fx = fx["export"]
    export = ExportTool(
        name=export_fx["tool_name"],
        run=lambda **kw: kw,
        destructive=export_fx["destructive"],
    )
    with pytest.raises(ConsentMissing):
        export.guarded_run(human_ack=export_fx["human_ack"], **export_fx["kwargs"])

    # The poison payload also fails the validator.
    verdict = validate_aggregates(
        fx["poison_payload"], fx["expected_schema"], k_floor=25
    )
    assert verdict["verdict"] == fx["expected"]["validator_verdict"] == "BLOCKED"
    for expected_finding in fx["expected"]["validator_findings_include"]:
        assert expected_finding in verdict["findings"]
