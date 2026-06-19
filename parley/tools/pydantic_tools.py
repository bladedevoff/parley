"""Parley's custom tools as pydantic-ai tool functions (cross-vendor path only).

The ClaudeSDKAdapter consumes ``(InputModel, handler)`` tuples; the
PydanticAIAdapter consumes plain context-aware functions registered via
``agent.tool``. These two wrappers expose the SAME EmitConsent / RunCapability
behavior to an OpenAI-compatible stranger (Groq / OpenRouter / OpenAI / custom)
by delegating to the identical underlying handlers — no logic is duplicated or
weakened, so the no-raw guarantees and the human gate hold on any vendor.

Unlike the rest of ``parley.tools`` (which stays import-safe offline), this module
imports pydantic-ai + band on purpose: it is only ever imported from the vault's
cross-vendor branch, which already requires the ``cross-vendor`` extra.

NOTE: no ``from __future__ import annotations`` here — pydantic-ai introspects the
concrete ``RunContext`` annotation to inject deps, so annotations must be real
objects, not strings.
"""

from pydantic_ai import RunContext
from band.core.protocols import AgentToolsProtocol

from parley.state import DealState
from parley.tools.emit_consent import EmitConsentInput, handle_emit_consent
from parley.tools.export_tool import RunCapabilityInput, make_capability_tool


def build_pydantic_tools(*, deal_id, state: DealState, registry, owner_org=None):
    """Return ``[emit_consent, run_capability]`` as pydantic-ai tool functions.

    They close over the same deal/state/registry the Claude path uses and call the
    exact same handlers, so consent + capability semantics are vendor-agnostic.
    """
    _input_model, _cap_handler = make_capability_tool(registry, owner_org=owner_org)

    async def emit_consent(
        ctx: RunContext[AgentToolsProtocol],
        decision: str,
        rationale: str,
        confidence: float,
        counter_terms: str = "",
    ) -> dict:
        """Emit a CONSENT decision for the current deal.

        decision must be one of: accept | decline | counter. A 'counter' requires
        counter_terms. confidence is 0.0-1.0. Returns the CONSENT envelope; post it
        into the room with band_send_message, mentioning the coordinator.
        """
        args = EmitConsentInput(
            decision=decision,
            rationale=rationale,
            confidence=confidence,
            counter_terms=counter_terms or None,
        )
        # post=None: return the envelope and let the LLM repost it via
        # band_send_message — identical to the Claude path (VAULT_PROMPT drives it).
        return await handle_emit_consent(args, deal_id=deal_id, post=None, state=state)

    async def run_capability(
        ctx: RunContext[AgentToolsProtocol],
        capability: str,
        deal_id: str,
        approver_is_human: bool = False,
        approver_org: str = "",
    ) -> dict:
        """Run one of the owner's approved capabilities over its own data/tools.

        Gated capabilities run ONLY after a first-party owner human issued
        APPROVE <deal_id>. Fill approver_is_human / approver_org from that message.
        Never returns raw rows.
        """
        args = RunCapabilityInput(
            capability=capability,
            deal_id=deal_id,
            approver_is_human=approver_is_human,
            approver_org=approver_org,
        )
        return await _cap_handler(args)

    return [emit_consent, run_capability]


def consent_system_prompt(scenario) -> str:
    """A self-contained vault prompt for the standalone cross-vendor demo.

    Unlike VAULT_PROMPT (which assumes a live Band room + band_send_message), this
    drives a single emit_consent call so the stranger's consent REASONING can be
    exercised on a non-Claude model with no Band room attached.
    """
    forbidden = ", ".join(scenario.policy.get("forbidden_columns", [])) or "any direct identifiers"
    return (
        f"You are {scenario.owner['name']}'s data custodian (the \"vault\"), recruited by "
        f"{scenario.buyer['name']} from another organization. POLICY (non-negotiable): never "
        f"release raw or row-level records, and never these columns: {forbidden}. You may only "
        f"offer in-place, k-anonymous aggregates with every cohort >= {scenario.k_floor}.\n\n"
        "You have EXACTLY ONE tool: `emit_consent`. There is NO messaging tool and NO "
        "`band_send_message` — do not call anything except `emit_consent`. Respond to the "
        "requester by calling `emit_consent` exactly once and nothing else:\n"
        "  - decision='counter' if they ask for raw/forbidden data (put the safe aggregate "
        "alternative in counter_terms),\n"
        "  - decision='accept' only for an already-safe aggregate request,\n"
        "  - decision='decline' if it cannot be made safe.\n"
        "Always include a short rationale and a confidence between 0 and 1."
    )


async def run_consent_demo(model, *, deal_id, registry, state, requester_ask, system_prompt):
    """Run the vault's consent decision on an arbitrary pydantic-ai ``model``.

    Builds a standalone pydantic-ai Agent with the SAME EmitConsent / RunCapability
    tools (no Band room), runs the requester's ask through it, and returns a capture
    of what the model decided. With a real OpenAI-compatible model this is a genuine
    non-Claude execution of the consent kernel; with a test model it is offline.
    """
    from pydantic_ai import Agent

    emit_consent, run_capability = build_pydantic_tools(
        deal_id=deal_id, state=state, registry=registry
    )
    agent = Agent(model, system_prompt=system_prompt, output_type=str)
    agent.tool(emit_consent)
    agent.tool(run_capability)

    result = await agent.run(requester_ask)

    tool_calls = []
    for message in result.all_messages():
        for part in getattr(message, "parts", []):
            if getattr(part, "part_kind", "") == "tool-call" and getattr(part, "tool_name", "") in (
                "emit_consent",
                "run_capability",
            ):
                tool_calls.append({"tool": part.tool_name, "args": _coerce_args(part.args)})

    entry = state.get(deal_id)
    return {
        "deal_id": str(deal_id),
        "decision": entry["decision"],
        "terms": entry["terms"],
        "tool_calls": tool_calls,
        "final_text": str(getattr(result, "output", "")),
    }


def _coerce_args(args):
    """ToolCallPart.args may be a dict or a JSON string; return a dict either way."""
    if isinstance(args, str):
        import json

        try:
            return json.loads(args)
        except (ValueError, TypeError):
            return {"_raw": args}
    return args or {}
