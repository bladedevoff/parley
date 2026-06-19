"""Northwind CHECKER agent (org A) — the compliance gate.

LIVE agent scaffold: imports the Band SDK; runs only with real credentials.
Not part of the offline test suite.

Behavior: when aggregate results arrive from the Lumen VAULT, the checker runs
``validate_aggregates`` (k-floor 25, schema check, PII check) and posts a clear
PASS or FAIL/BLOCKED verdict with the specific findings. It never approves a
payload it has not actually validated.

Uses haiku — validation is mechanical (delegated to the pure validator), so the
LLM only needs to extract the payload + schema and relay the verdict.

Run:  python -m parley.agents.checker
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from band import Agent

from parley.agents._adapters import build_agent_adapter
from parley.common.prompts import CHECKER_PROMPT
from parley.config import load_creds
from parley.tools.validator import DEFAULT_K_FLOOR, validate_aggregates

logger = logging.getLogger(__name__)

# Sonnet for the checker — haiku loops on the band tool-search step. Sonnet
# reliably reasons over the aggregate payload and posts a verdict in one pass.
CHECKER_MODEL = "claude-sonnet-4-6"
CHECKER_FALLBACK_MODEL = "claude-sonnet-4-6"


def check_payload(
    payload: Any,
    expected_schema: Any,
    *,
    k_floor: int = DEFAULT_K_FLOOR,
) -> dict:
    """Validate an aggregate *payload* and format a room-ready verdict.

    Pure (band-free) so it is unit-testable. Returns the raw validator result
    plus a human-readable ``message`` the agent can post via send_message.
    """
    result = validate_aggregates(payload, expected_schema, k_floor=k_floor)
    if result["verdict"] == "PASS":
        message = "PASS: aggregates clear the k-floor, schema-conformant, no PII."
    else:
        findings = ", ".join(result["findings"]) or "unspecified"
        message = f"FAIL (BLOCKED): {findings}."
    return {**result, "message": message}


def build_adapter():
    """Construct the checker's adapter (Claude by default, or cross-vendor).

    No custom tool — validation is deterministic (``validate_aggregates``) and the
    LLM only relays the verdict via send_message. Set CHECKER_LLM_VENDOR /
    PARLEY_LLM_VENDOR (+ a key) to run it off Claude.
    """
    return build_agent_adapter(
        "checker",
        custom_section=CHECKER_PROMPT,
        claude_model=CHECKER_MODEL,
        claude_fallback=CHECKER_FALLBACK_MODEL,
    )


async def main() -> None:
    """Live entrypoint: create and run the Northwind checker agent."""
    logging.basicConfig(level=logging.INFO)
    creds = load_creds("CHECKER")  # @northwind-* -> account "northwind"

    adapter = build_adapter()

    os.environ.pop("ANTHROPIC_API_KEY", None)

    agent = Agent.create(
        adapter=adapter,
        agent_id=creds.agent_id,
        api_key=creds.api_key,
        ws_url=os.getenv("BAND_WS_URL")
        or "wss://app.band.ai/api/v1/socket/websocket",
        rest_url=os.getenv("BAND_REST_URL") or "https://app.band.ai",
    )

    logger.info("Northwind CHECKER (%s) running — Ctrl+C to stop.", creds.handle)
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
