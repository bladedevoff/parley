"""Northwind COORDINATOR agent (org A) — orchestrator + human liaison.

LIVE agent scaffold: imports the Band SDK and only runs with real credentials.
Not part of the offline test suite.

Responsibilities:
- Discover the Lumen VAULT peer (band_lookup_peers), send a contact request
  (band_add_contact), and add it to the room (band_add_participant) once the
  contact is accepted.
- Wait a short SUBSCRIBE_GRACE after adding a participant so the new agent's
  WebSocket subscription is live before it is @mentioned.
- Relay CONSENT envelopes between the Northwind MODELER/CHECKER and the Lumen
  VAULT, always via @mention.
- Surface each consent decision to the human and thread their
  ``APPROVE <deal_id>`` / ``DENY <deal_id>`` back into deal state.

Run:  python -m parley.agents.coordinator
"""

from __future__ import annotations

import asyncio
import logging
import os

from band import Agent

from parley.agents._adapters import build_agent_adapter
from parley.common.prompts import COORDINATOR_PROMPT, VAULT_HANDLE
from parley.config import load_creds
from parley.envelope import parse_consent_envelope
from parley.state import DealState
from parley.tools.human_gate import parse_human_ack

logger = logging.getLogger(__name__)

COORDINATOR_MODEL = "claude-opus-4-8"
COORDINATOR_FALLBACK_MODEL = "claude-sonnet-4-6"

# Seconds to wait after add_participant so the newly added agent has subscribed
# to the room over WebSocket before we @mention it. Mentioning too early can
# drop the message because the recipient isn't yet listening.
SUBSCRIBE_GRACE = 5.0


async def discover_and_recruit_vault(tools, *, room_id: str) -> str | None:
    """Find the Lumen vault, ensure a contact, and add it to the room.

    Uses the live ``AgentTools`` surface (so handle->id resolution and room
    binding are handled by the SDK). Returns the vault's participant id if it
    was added, else ``None``.

    TODO(live): this helper is meant to be invoked from ``on_message`` (or a
    bootstrap hook) once ``tools`` for the room is available. The LLM can also
    drive these same band tools directly per the COORDINATOR_PROMPT; this
    Python path exists as a deterministic fallback for the demo.
    """
    # 1) Discover peers and locate the vault by handle.
    peers_resp = await tools.lookup_peers(page=1, page_size=50)
    peers = getattr(peers_resp, "data", None) or []
    vault = None
    target = VAULT_HANDLE.lstrip("@").lower()  # e.g. "lumen/vault"
    for p in peers:
        handle = (getattr(p, "handle", None) or "").lstrip("@").lower()
        if handle == target or handle.endswith("/vault"):
            vault = p
            break
    if vault is None:
        logger.warning("Vault peer %s not found among %d peers", VAULT_HANDLE, len(peers))
        return None

    # 2) Ensure a contact relationship (idempotent on the platform side; the
    #    vault must accept before it can be added cross-org).
    try:
        await tools.add_contact(VAULT_HANDLE, message="Northwind requests a data cohort.")
    except Exception as exc:  # already-contact / pending is fine
        logger.info("add_contact(%s): %s", VAULT_HANDLE, exc)

    # 3) Add the vault to the room, then give it time to subscribe.
    await tools.add_participant(VAULT_HANDLE, role="member")
    logger.info("Added %s; waiting %.1fs for subscription", VAULT_HANDLE, SUBSCRIBE_GRACE)
    await asyncio.sleep(SUBSCRIBE_GRACE)
    return getattr(vault, "id", None)


def handle_inbound_text(content: str, sender_is_human: bool, state: DealState) -> dict:
    """Classify an inbound message into a coordinator action.

    Pure routing logic (band-free) so it is unit-testable:
    - A human ``APPROVE/DENY <deal_id>`` flips the deal's human-ack flag and
      returns an ``ack`` action.
    - A CONSENT envelope returns a ``relay`` action with the parsed envelope.
    - Anything else returns ``{"action": "ignore"}``.
    """
    ack = parse_human_ack(content, sender_is_human)
    if ack is not None:
        state.set_human_ack(ack["deal_id"], ack["action"] == "APPROVE")
        return {"action": "ack", **ack}

    env = parse_consent_envelope(content)
    if env is not None:
        return {"action": "relay", "envelope": env}

    return {"action": "ignore"}


def build_adapter():
    """Construct the coordinator's adapter (Claude by default, or cross-vendor).

    Drives the standard band tools (lookup_peers, add_contact, add_participant,
    send_message) directly via the LLM — no custom tool. ``contacts=True`` so the
    cross-vendor (PydanticAIAdapter) path still gets the contact-management tools.
    Set COORDINATOR_LLM_VENDOR / PARLEY_LLM_VENDOR (+ a key) to run it off Claude.
    """
    return build_agent_adapter(
        "coordinator",
        custom_section=COORDINATOR_PROMPT,
        claude_model=COORDINATOR_MODEL,
        claude_fallback=COORDINATOR_FALLBACK_MODEL,
        contacts=True,
    )


async def main() -> None:
    """Live entrypoint: create and run the Northwind coordinator agent."""
    logging.basicConfig(level=logging.INFO)
    creds = load_creds("COORDINATOR")  # @northwind-* -> account "northwind"

    # Shared deal state for threading human APPROVE/DENY into the negotiation.
    # TODO(live): persist/share this with the checker as needed; for the single
    # process demo an in-memory store is sufficient.
    _state = DealState()

    adapter = build_adapter()

    # Coordinator also thinks via the local Claude subscription.
    os.environ.pop("ANTHROPIC_API_KEY", None)

    agent = Agent.create(
        adapter=adapter,
        agent_id=creds.agent_id,
        api_key=creds.api_key,
        ws_url=os.getenv("BAND_WS_URL")
        or "wss://app.band.ai/api/v1/socket/websocket",
        rest_url=os.getenv("BAND_REST_URL") or "https://app.band.ai",
    )

    logger.info("Northwind COORDINATOR (%s) running — Ctrl+C to stop.", creds.handle)
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
