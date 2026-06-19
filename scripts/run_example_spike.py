"""Run the active scenario's negotiation moment LIVE: post the buyer's raw ask to
a running vault and capture the vault's domain-aware COUNTER-OFFER.

The vault must be running with the SAME PARLEY_SCENARIO, e.g.:
    PARLEY_SCENARIO=examples/02_code_review.yaml uv run python -m parley.agents.vault
    PARLEY_SCENARIO=examples/02_code_review.yaml uv run python scripts/run_example_spike.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parley.config import load_creds
from parley.common.band_client import BandRestClient
from parley.envelope import parse_consent_envelope
from parley.scenario import SCENARIO


def D(r):
    return r["data"] if isinstance(r, dict) and "data" in r else r


def main() -> int:
    coord = load_creds("COORDINATOR")
    vault = load_creds("VAULT")
    A = BandRestClient(coord.api_key)
    vault_handle = SCENARIO.agent("vault").lstrip("@")
    ask = SCENARIO.request.get("raw_ask", "we need your data")
    deal = SCENARIO.deal_id

    print(f"[example] {deal}: {SCENARIO.buyer['name']} -> {SCENARIO.owner['name']}")
    room = D(A._request("POST", "chats", body={"chat": {"title": f"Parley Example {deal}"}}))
    room_id = room.get("id")
    A.add_participant(room_id, vault.agent_id)
    print(f"[example] room {room_id}; vault joining…")
    time.sleep(7)

    seen = {m.get("id") for m in (D(A.get_messages(room_id)) or [])}
    A.send_message(room_id, f"@{vault_handle} For deal {deal}: {ask}. Please provide this.",
                   mentions=[{"id": vault.agent_id, "handle": vault_handle}])
    print("[example] raw ask sent; waiting for the vault's counter-offer…\n")

    deadline = time.time() + 150
    while time.time() < deadline:
        time.sleep(6)
        for m in (D(A.get_messages(room_id)) or []):
            if m.get("id") in seen:
                continue
            seen.add(m.get("id"))
            s = m.get("sender_name", "?")
            c = m.get("content") or ""
            if "vault" not in str(s).lower() and m.get("sender_id") != vault.agent_id:
                continue
            print(f"[{s}] {c[:260].replace(chr(10), ' ')}\n")
            env = parse_consent_envelope(c)
            if env:
                dec = env.get("decision")
                Path("proof").mkdir(exist_ok=True)
                Path(f"proof/example-{deal}.json").write_text(json.dumps(
                    {"deal_id": deal, "buyer": SCENARIO.buyer["name"], "owner": SCENARIO.owner["name"],
                     "raw_ask": ask, "decision": dec, "terms": env.get("terms"),
                     "rationale": env.get("rationale"), "room_id": room_id}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
                print("=" * 60)
                print(f"  {deal}: vault decision = {str(dec).upper()}  (saved proof/example-{deal}.json)")
                print("=" * 60)
                return 0 if dec in ("counter", "decline") else 2
        print(f"[example] …waiting ({int(deadline - time.time())}s)")
    print("[example] TIMEOUT")
    return 1


if __name__ == "__main__":
    sys.exit(main())
