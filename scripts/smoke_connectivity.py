"""Live connectivity smoke test — verifies all 4 Band agent keys authenticate.

Pure REST, ZERO LLM/Claude cost. Run before lighting up the agents:

    uv run python scripts/smoke_connectivity.py

Reads creds from .env via parley.config.load_creds and calls GET /agent/me for
each agent, confirming the key is valid and the platform is reachable.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parley.config import load_creds
from parley.common.band_client import BandRestClient


def main() -> int:
    agents = ["COORDINATOR", "MODELER", "CHECKER", "VAULT"]
    ok = True
    for name in agents:
        try:
            creds = load_creds(name)
        except Exception as exc:  # missing/blank env
            print(f"[{name:11}] CREDS ERROR: {exc}")
            ok = False
            continue
        client = BandRestClient(creds.api_key)
        try:
            me = client.me()
            handle = (me or {}).get("handle") or (me or {}).get("name") or "?"
            print(f"[{name:11}] OK  account={creds.account:9} handle={creds.handle:30} me.handle={handle}")
        except Exception as exc:
            print(f"[{name:11}] AUTH FAIL: {exc}")
            ok = False

    print()
    print("RESULT:", "ALL 4 AGENTS REACHABLE [OK]" if ok else "SOME AGENTS FAILED [FAIL]")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
