"""Tests for the emit_consent tool (pure logic + pydantic). No band import."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parley.envelope import parse_consent_envelope
from parley.state import DealState
from parley.tools.emit_consent import (
    TARGET_COORDINATOR,
    EmitConsentInput,
    handle_emit_consent,
)


def test_schema_valid_accepts_well_formed_input():
    args = EmitConsentInput(
        decision="accept",
        rationale="terms are safe",
        confidence=0.75,
    )
    assert args.decision == "accept"
    assert args.counter_terms is None
    assert args.confidence == 0.75


def test_schema_rejects_bad_decision():
    with pytest.raises(ValidationError):
        EmitConsentInput(decision="maybe", rationale="x", confidence=0.5)


@pytest.mark.parametrize("confidence", [-0.1, 1.5])
def test_schema_rejects_confidence_out_of_range(confidence):
    with pytest.raises(ValidationError):
        EmitConsentInput(decision="accept", rationale="x", confidence=confidence)


async def test_counter_without_counter_terms_is_invalid():
    state = DealState()
    args = EmitConsentInput(decision="counter", rationale="need safer terms", confidence=0.6)

    result = await handle_emit_consent(args, deal_id="d1", post=None, state=state)

    assert result["status"] == "INVALID"
    assert result["reason"] == "counter requires counter_terms"
    # Nothing recorded on an invalid emit.
    assert state.get("d1")["decision"] is None


async def test_accept_targets_coordinator():
    state = DealState()
    args = EmitConsentInput(decision="accept", rationale="all good", confidence=0.9)

    result = await handle_emit_consent(args, deal_id="d2", post=None, state=state)

    assert result["status"] == "ok"
    assert result["decision"] == "accept"
    # All consent decisions report to the coordinator/liaison.
    assert result["target"] == TARGET_COORDINATOR == "@northwind-analytics/coordinator"
    assert state.get("d2")["decision"] == "accept"


async def test_counter_targets_coordinator():
    state = DealState()
    args = EmitConsentInput(
        decision="counter",
        rationale="propose k-suppressed aggregates",
        counter_terms="k_floor=25; aggregates only",
        confidence=0.7,
    )

    result = await handle_emit_consent(args, deal_id="d3", post=None, state=state)

    assert result["status"] == "ok"
    assert result["target"] == TARGET_COORDINATOR == "@northwind-analytics/coordinator"
    assert state.get("d3")["terms"] == "k_floor=25; aggregates only"


async def test_decline_targets_coordinator():
    state = DealState()
    args = EmitConsentInput(decision="decline", rationale="too risky", confidence=0.95)

    result = await handle_emit_consent(args, deal_id="d4", post=None, state=state)

    assert result["status"] == "ok"
    assert result["target"] == TARGET_COORDINATOR


async def test_envelope_round_trips_via_parse():
    state = DealState()
    args = EmitConsentInput(
        decision="counter",
        rationale="propose safer terms",
        counter_terms="aggregates only",
        confidence=0.66,
    )

    result = await handle_emit_consent(args, deal_id="deal-xyz", post=None, state=state)

    parsed = parse_consent_envelope(result["envelope"])
    assert parsed is not None
    assert parsed["type"] == "CONSENT"
    assert parsed["deal_id"] == "deal-xyz"
    assert parsed["decision"] == "counter"
    assert parsed["terms"] == "aggregates only"
    assert parsed["rationale"] == "propose safer terms"
    assert parsed["confidence"] == 0.66


async def test_post_is_called_with_body_and_target():
    state = DealState()
    sent: list[tuple[str, str]] = []

    async def fake_post(text, mention_handle):
        sent.append((text, mention_handle))

    args = EmitConsentInput(decision="accept", rationale="ok", confidence=0.8)
    result = await handle_emit_consent(args, deal_id="d5", post=fake_post, state=state)

    assert len(sent) == 1
    body, target = sent[0]
    assert body == result["envelope"]
    assert target == TARGET_COORDINATOR
