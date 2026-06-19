"""Functional tests for the cross-vendor (pydantic-ai) tool wrappers.

These prove the OpenAI-compatible stranger gets the SAME consent + capability
behavior as the Claude path. Skipped automatically when the optional
``cross-vendor`` extra (pydantic-ai) isn't installed, so default CI stays green.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic_ai")  # only meaningful with the cross-vendor extra

from parley.capabilities import build_registry
from parley.scenario import load_scenario
from parley.state import DealState
from parley.tools.pydantic_tools import (
    build_pydantic_tools,
    consent_system_prompt,
    run_consent_demo,
)


def _tools():
    scn = load_scenario("examples/01_data_collaboration.yaml")
    state = DealState()
    reg = build_registry(scn)
    emit_consent, run_capability = build_pydantic_tools(
        deal_id=scn.deal_id, state=state, registry=reg, owner_org=scn.owner_org
    )
    return emit_consent, run_capability, state, scn


async def test_emit_consent_counter_requires_terms():
    emit_consent, _run, _state, _scn = _tools()
    out = await emit_consent(None, decision="counter", rationale="need aggregate", confidence=0.9)
    assert out["status"] == "INVALID"


async def test_emit_consent_accept_records_state():
    emit_consent, _run, state, scn = _tools()
    out = await emit_consent(None, decision="accept", rationale="aggregate ok", confidence=0.8)
    assert out["status"] == "ok"
    assert out["decision"] == "accept"
    assert "envelope" in out
    # the decision was recorded into deal state, same as the Claude path
    assert state.get(scn.deal_id)["decision"] == "accept"


async def test_run_capability_blocked_without_human_approval():
    _emit, run_capability, _state, scn = _tools()
    out = await run_capability(None, capability="cohort_aggregate", deal_id=scn.deal_id)
    assert out["status"] == "BLOCKED"


async def test_run_capability_ok_with_owner_human_and_no_raw():
    _emit, run_capability, _state, scn = _tools()
    out = await run_capability(
        None, capability="cohort_aggregate", deal_id=scn.deal_id,
        approver_is_human=True, approver_org=scn.owner_org,
    )
    assert out["status"] == "ok"
    assert out["rows_exported"] == 0  # the no-raw guarantee holds on any vendor


def test_consent_system_prompt_carries_policy():
    scn = load_scenario("examples/01_data_collaboration.yaml")
    prompt = consent_system_prompt(scn)
    assert "emit_consent" in prompt
    assert str(scn.k_floor) in prompt
    # forbidden columns are surfaced so the model knows what to refuse
    assert "email" in prompt


async def test_run_consent_demo_counters_raw_ask_offline():
    # Drive the harness with a FunctionModel so the cross-vendor consent path is
    # proven end-to-end with NO network — exactly what run_cross_vendor_demo.py runs
    # against a real Groq/OpenRouter model when a key is present.
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    scn = load_scenario("examples/01_data_collaboration.yaml")
    reg = build_registry(scn)
    state = DealState()

    def fake_model(messages, info):
        returned = any(
            getattr(p, "part_kind", "") == "tool-return"
            for m in messages
            for p in getattr(m, "parts", [])
        )
        if returned:  # tool already ran -> finish the turn
            return ModelResponse(parts=[TextPart(content="counter sent")])
        return ModelResponse(parts=[ToolCallPart(
            tool_name="emit_consent",
            args={
                "decision": "counter",
                "rationale": "raw customer rows are not permitted",
                "confidence": 0.9,
                "counter_terms": "in-place k-anonymous cohort counts only",
            },
        )])

    cap = await run_consent_demo(
        FunctionModel(fake_model),
        deal_id=scn.deal_id,
        registry=reg,
        state=state,
        requester_ask="Send us the raw customer table with emails.",
        system_prompt=consent_system_prompt(scn),
    )
    assert cap["decision"] == "counter"
    assert any(tc["tool"] == "emit_consent" for tc in cap["tool_calls"])
    assert state.get(scn.deal_id)["decision"] == "counter"
