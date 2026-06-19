"""emit_consent tool — pure logic + pydantic, no top-level band import.

The agent calls this to emit a CONSENT envelope into the room and route it to
the right counterpart (coordinator for non-accept, checker for accept).
``make_band_tool`` wires it into a Band ClaudeSDKAdapter as a custom tool;
``band`` is imported lazily inside that function so this module loads offline.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, Field

from parley.envelope import build_consent_envelope
from parley.scenario import SCENARIO
from parley.state import DealState

# Routing targets (real Band handles) — sourced from scenario.yaml so a different
# deployment routes to its own agents without code changes.
TARGET_COORDINATOR = SCENARIO.agent("coordinator")
TARGET_CHECKER = SCENARIO.agent("checker")

# A post callable: post(text, mention_handle) -> awaitable.
PostFn = Callable[[str, str], Awaitable[Any]]


class EmitConsentInput(BaseModel):
    """Emit a CONSENT decision for the current deal."""

    decision: Literal["accept", "decline", "counter"]
    rationale: str
    counter_terms: Optional[str] = None
    confidence: float = Field(..., ge=0.0, le=1.0)


async def handle_emit_consent(
    args: EmitConsentInput,
    *,
    deal_id: Any,
    post: Optional[PostFn],
    state: DealState,
) -> dict:
    """Validate, build, route, and record a CONSENT decision.

    Args:
        args: Validated tool input.
        deal_id: The deal this decision belongs to.
        post: Optional ``post(text, mention_handle)`` coroutine; when None,
            nothing is sent (useful for offline tests).
        state: Deal state store to record the decision into.

    Returns:
        ``{"status": "INVALID", "reason": ...}`` on validation failure, else
        ``{"status": "ok", "decision", "envelope", "target"}``.
    """
    if args.decision == "counter" and not args.counter_terms:
        return {"status": "INVALID", "reason": "counter requires counter_terms"}

    body = build_consent_envelope(
        deal_id=deal_id,
        decision=args.decision,
        terms=args.counter_terms,
        rationale=args.rationale,
        confidence=args.confidence,
    )

    # Every consent decision is reported to the coordinator (the liaison who
    # surfaces it to the human and relays to the modeler). The checker validates
    # the ACTUAL aggregates later, via a separate message after export — not at
    # decision time.
    target = TARGET_COORDINATOR

    if post is not None:
        await post(body, target)

    state.record(deal_id, args.decision, args.counter_terms)

    return {
        "status": "ok",
        "decision": args.decision,
        "envelope": body,
        "target": target,
    }


def make_band_tool(deal_id: Any, room: Any, state: DealState):
    """Build a Band custom-tool tuple ``(EmitConsentInput, handler)``.

    The returned handler closes over ``deal_id`` / ``room`` / ``state`` and
    delegates to :func:`handle_emit_consent`, posting via ``room.send_message``.

    ``band`` is imported lazily here so importing this module never requires the
    SDK to be installed.
    """
    # Under ClaudeSDKAdapter, custom-tool handlers do NOT receive the room, so
    # ``room`` is None there: the handler records state + returns the envelope,
    # and the agent's LLM posts it via band_send_message (see VAULT_PROMPT).
    # When a ``room`` shim IS supplied (tests / other adapters), post directly.
    _post: Optional[PostFn] = None
    if room is not None:
        async def _post(text: str, mention_handle: str) -> Any:  # type: ignore[misc]
            # AgentTools.send_message(content, mentions=[handle]).
            return await room.send_message(text, mentions=[mention_handle])

    async def _handler(args: EmitConsentInput) -> dict:
        return await handle_emit_consent(
            args,
            deal_id=deal_id,
            post=_post,
            state=state,
        )

    return (EmitConsentInput, _handler)
