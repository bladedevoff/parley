"""Northwind MODELER agent (org A) — the data requester.

LIVE agent scaffold: imports the Band SDK; runs only with real credentials.
Not part of the offline test suite.

Behavior: the modeler initially wants raw customer data, but when the Lumen
VAULT declines or counters, it reformulates its need as a k-anonymous AGGREGATE
specification (bucket counts, k>=25, no raw rows, no identifier columns) and
emits an ACCEPT. All decisions go out as CONSENT envelopes via EmitConsent.

Uses the cheaper haiku model: the modeler's job (reshape a request into an
aggregate spec, then accept) is light reasoning compared to the vault's
safety-critical gatekeeping.

Run:  python -m parley.agents.modeler
"""

from __future__ import annotations

import asyncio
import logging
import os

from band import Agent

from parley.agents._adapters import build_agent_adapter
from parley.common.prompts import MODELER_PROMPT
from parley.config import load_creds
from parley.scenario import SCENARIO
from parley.state import DealState

logger = logging.getLogger(__name__)

# Haiku for the modeler — cheap reformulation + accept loop.
MODELER_MODEL = "claude-haiku-4-5"
MODELER_FALLBACK_MODEL = "claude-sonnet-4-6"

# Deal id from the active scenario.
DEFAULT_DEAL_ID = SCENARIO.deal_id


def build_adapter(state: DealState, deal_id: str):
    """Construct the modeler's adapter (Claude by default, or cross-vendor).

    The modeler is a data REQUESTER: it asks the vault for data and reformulates to
    an aggregate spec via plain band_send_message — no custom tool. Set
    MODELER_LLM_VENDOR / PARLEY_LLM_VENDOR (+ a key) to run it off Claude.
    """
    return build_agent_adapter(
        "modeler",
        custom_section=MODELER_PROMPT,
        claude_model=MODELER_MODEL,
        claude_fallback=MODELER_FALLBACK_MODEL,
    )


async def main() -> None:
    """Live entrypoint: create and run the Northwind modeler agent."""
    logging.basicConfig(level=logging.INFO)
    creds = load_creds("MODELER")  # @northwind-* -> account "northwind"

    state = DealState()
    deal_id = DEFAULT_DEAL_ID
    adapter = build_adapter(state, deal_id)

    os.environ.pop("ANTHROPIC_API_KEY", None)

    agent = Agent.create(
        adapter=adapter,
        agent_id=creds.agent_id,
        api_key=creds.api_key,
        ws_url=os.getenv("BAND_WS_URL")
        or "wss://app.band.ai/api/v1/socket/websocket",
        rest_url=os.getenv("BAND_REST_URL") or "https://app.band.ai",
    )

    logger.info("Northwind MODELER (%s) running — Ctrl+C to stop.", creds.handle)
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
