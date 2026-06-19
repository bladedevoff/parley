"""Lumen VAULT agent (org B) — the data-owning "stranger".

This is a LIVE agent scaffold: it imports the Band SDK and the Claude Agent SDK
and will only run once real credentials + auth are available. It is NOT exercised
by the offline test suite (those cover the pure modules in ``parley.tools`` /
``parley.envelope`` / ``parley.state``).

Role recap: the VAULT owns Lumen Retail's sensitive customer data. It accepts
ONLY k-anonymous aggregate/cohort requests that keep raw PII inside Lumen, and
it only performs an actual export after BOTH (1) a consent ACCEPT and (2) an
explicit human ``APPROVE <deal_id>``. All consent replies go out as CONSENT
envelopes via the EmitConsent custom tool — never as prose.

Run:  python -m parley.agents.vault   (requires live VAULT_* creds + Claude auth)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

# NOTE: band / claude_agent_sdk are imported at module top *intentionally* —
# this is a live entrypoint, not an offline-importable helper. The offline
# modules (parley.tools.*) keep band out of their import path; this file does
# not, and that is expected.
from band import Agent
from band.runtime.types import ContactEventConfig, ContactEventStrategy

from parley.agents._adapters import build_agent_adapter
from parley.capabilities import REGISTRY
from parley.common.prompts import VAULT_PROMPT
from parley.config import load_creds
from parley.scenario import SCENARIO
from parley.state import DealState
from parley.tools.emit_consent import make_band_tool
from parley.tools.export_tool import make_capability_tool

logger = logging.getLogger(__name__)

# Primary model + fallback per the Parley spec. opus for the safety-critical
# vault, falling back to sonnet if opus is unavailable under the active auth.
VAULT_MODEL = "claude-opus-4-8"
VAULT_FALLBACK_MODEL = "claude-sonnet-4-6"

# Deal id for the single-room demo, taken from the active scenario.
DEFAULT_DEAL_ID = SCENARIO.deal_id


def build_adapter(state: DealState, deal_id: str) -> Any:
    """Construct the vault's adapter (Claude by default, or a cross-vendor model).

    The EmitConsent + RunCapability logic is reused unchanged on both paths: tuple
    tools for ClaudeSDKAdapter; the same handlers wrapped as pydantic-ai functions
    for an OpenAI-compatible vendor. Vendor is chosen by ``select_provider('vault')``
    (VAULT_LLM_VENDOR | PARLEY_LLM_VENDOR). The no-raw guarantees hold either way.

    NOTE: ``make_band_tool`` gets ``room=None`` (the ClaudeSDKAdapter exposes per-room
    tools only at message time), so the LLM reposts the returned envelope via
    band_send_message (see VAULT_PROMPT).
    """
    consent_tool = make_band_tool(deal_id=deal_id, room=None, state=state)
    capability_tool = make_capability_tool(REGISTRY)

    def _ptools():  # lazy: only imported/built on the cross-vendor path
        from parley.tools.pydantic_tools import build_pydantic_tools
        return build_pydantic_tools(deal_id=deal_id, state=state, registry=REGISTRY)

    return build_agent_adapter(
        "vault",
        custom_section=VAULT_PROMPT,
        claude_model=VAULT_MODEL,
        claude_fallback=VAULT_FALLBACK_MODEL,
        tuple_tools=[consent_tool, capability_tool],
        pydantic_tools=_ptools,
        contacts=True,  # the stranger consents to the cross-org contact
    )


async def main() -> None:
    """Live entrypoint: create and run the Lumen vault agent."""
    logging.basicConfig(level=logging.INFO)
    creds = load_creds("VAULT")  # @lumen-* -> account "lumen"

    state = DealState()
    deal_id = DEFAULT_DEAL_ID

    adapter = build_adapter(state, deal_id)

    # The vault thinks via the local Claude subscription (Claude Agent SDK /
    # Claude Code). Drop any ANTHROPIC_API_KEY so the SDK uses subscription auth
    # rather than a metered API key.
    os.environ.pop("ANTHROPIC_API_KEY", None)

    # Contact handling. HUB_ROOM creates a dedicated hub room at startup so the
    # vault's LLM can consent to NEW contact requests (the consent-to-join demo) —
    # but it spawns a fresh room on every restart. Once the cross-org contact is
    # established, set PARLEY_CONTACT=disabled for clean re-runs (no new rooms),
    # or =callback for programmatic handling.
    _mode = os.getenv("PARLEY_CONTACT", "disabled").lower()
    _strategy = {
        "hub_room": ContactEventStrategy.HUB_ROOM,
        "callback": ContactEventStrategy.CALLBACK,
        "disabled": ContactEventStrategy.DISABLED,
    }.get(_mode, ContactEventStrategy.DISABLED)
    if _strategy is ContactEventStrategy.CALLBACK:
        async def _approve_aggregate_contacts(event, tools):
            msg = (getattr(event, "payload", None) and (event.payload.message or "")).lower()
            decision = "approve" if ("aggregate" in msg or "cohort" in msg or "no raw" in msg) else "reject"
            await tools.respond_contact_request(decision, request_id=event.payload.id)
        contact_config = ContactEventConfig(strategy=_strategy, on_event=_approve_aggregate_contacts, broadcast_changes=True)
    else:
        contact_config = ContactEventConfig(strategy=_strategy, broadcast_changes=True)

    agent = Agent.create(
        adapter=adapter,
        agent_id=creds.agent_id,
        api_key=creds.api_key,
        contact_config=contact_config,
        # Endpoints default to app.band.ai; override via env if needed.
        ws_url=os.getenv("BAND_WS_URL")
        or "wss://app.band.ai/api/v1/socket/websocket",
        rest_url=os.getenv("BAND_REST_URL") or "https://app.band.ai",
    )

    logger.info("Lumen VAULT (%s) running — Ctrl+C to stop.", creds.handle)
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
