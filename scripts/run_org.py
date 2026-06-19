"""Run ONE organization's agents — so two REAL operators can do a genuine cross-org deal.

The single-operator demo (one person holding both orgs' accounts) is fine for a
walkthrough, but the real trust story needs two independent operators. This makes
that turnkey: each operator runs only THEIR side, with only THEIR org's creds in
.env and their own Claude/vendor auth.

    Operator A — Northwind (buyer/requester):
        uv run python scripts/run_org.py buyer
        # then drive the deal:  uv run python scripts/run_demo.py

    Operator B — Lumen (owner / the recruited stranger):
        uv run python scripts/run_org.py owner
        # approve the export in-room when prompted: APPROVE <deal_id>

Aliases: buyer=northwind=a ; owner=lumen=b. See JOIN.md for the full second-operator
onboarding (create the account, register the agent, fill .env). Cross-vendor works
per side too — e.g. PARLEY_LLM_VENDOR=groq on the owner's machine only.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WS = os.getenv("BAND_WS_URL") or "wss://app.band.ai/api/v1/socket/websocket"
REST = os.getenv("BAND_REST_URL") or "https://app.band.ai"

BUYER = {"buyer", "northwind", "a", "requester"}
OWNER = {"owner", "lumen", "b", "vault"}


async def run_buyer() -> None:
    """Northwind side: coordinator + modeler + checker, concurrently, one operator."""
    from band import Agent

    from parley.agents import checker, coordinator, modeler
    from parley.agents.modeler import DEFAULT_DEAL_ID
    from parley.config import load_creds
    from parley.state import DealState

    os.environ.pop("ANTHROPIC_API_KEY", None)  # use the Claude subscription
    state = DealState()
    specs = [
        ("COORDINATOR", coordinator.build_adapter()),
        ("MODELER", modeler.build_adapter(state, DEFAULT_DEAL_ID)),
        ("CHECKER", checker.build_adapter()),
    ]
    agents = []
    for name, adapter in specs:
        creds = load_creds(name)
        agents.append(Agent.create(adapter=adapter, agent_id=creds.agent_id,
                                   api_key=creds.api_key, ws_url=WS, rest_url=REST))
        print(f"  started {creds.handle}")
    print("Northwind side running (coordinator + modeler + checker) — Ctrl+C to stop.")
    await asyncio.gather(*(a.run() for a in agents))


async def run_owner() -> None:
    """Lumen side: just the recruited vault (it handles its own contact consent)."""
    from parley.agents import vault
    await vault.main()


def main(argv: list[str]) -> int:
    side = (argv[0].lower() if argv else "").strip()
    if side in BUYER:
        asyncio.run(run_buyer())
    elif side in OWNER:
        asyncio.run(run_owner())
    else:
        print("usage: python scripts/run_org.py <buyer|owner>\n"
              "  buyer  = Northwind (coordinator+modeler+checker)\n"
              "  owner  = Lumen (vault) — the recruited stranger\n"
              "Each operator runs only their side, with only their org's creds in .env.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
