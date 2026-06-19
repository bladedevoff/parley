"""Parley full-run director — coordinator + modeler + checker + vault + human.

Plays @coordinator (liaison) over REST while @modeler, @checker, @vault run as
LIVE LLM agents. Drives the golden path end to end and captures the transcript.
Scenario-aware (handles/data from the active scenario.yaml / PARLEY_SCENARIO).

    # terminal 1:  PARLEY_CONTACT=disabled uv run python -m parley.agents.vault
    # terminal 2:  uv run python -m parley.agents.modeler
    # terminal 3:  uv run python -m parley.agents.checker
    # terminal 4:  uv run python scripts/run_demo.py

Flow: coordinator kicks off modeler -> modeler asks vault -> vault COUNTERs ->
coordinator relays -> modeler revises -> vault ACCEPTs -> coordinator (agent)
tries APPROVE and is REJECTED by the vault -> the OWNER's human DPO approves in
the room -> vault runs the capability (rows_exported=0) -> checker validates PASS.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parley.common.band_client import BandRestClient, BandClientError
from parley.config import load_creds
from parley.envelope import parse_consent_envelope
from parley.scenario import SCENARIO

ROOM_TITLE = "Parley Full Run"
GRACE = 7.0


def D(r):
    return r["data"] if isinstance(r, dict) and "data" in r else r


def msgs_of(A, room):
    d = D(A.get_messages(room)) or []
    return d if isinstance(d, list) else (d.get("messages") or [])


def main() -> int:
    coord = load_creds("COORDINATOR")
    modeler = load_creds("MODELER")
    checker = load_creds("CHECKER")
    vault = load_creds("VAULT")
    A = BandRestClient(coord.api_key)
    V = BandRestClient(vault.api_key)

    h_modeler = SCENARIO.agent("modeler").lstrip("@")
    h_checker = SCENARIO.agent("checker").lstrip("@")
    h_vault = SCENARIO.agent("vault").lstrip("@")
    deal = SCENARIO.deal_id

    room = (D(A._request("POST", "chats", body={"chat": {"title": ROOM_TITLE}})) or {}).get("id")
    print(f"[director] room {room}  ({SCENARIO.buyer['name']} -> {SCENARIO.owner['name']}, deal {deal})")

    # Coordinator adds its org-A teammates + the cross-org vault.
    for who in (modeler, checker, vault):
        try:
            A.add_participant(room, who.agent_id)
        except BandClientError as e:
            if e.status != 409:
                print(f"[director] add {who.handle}: {e.status}")
    # The OWNER side adds its own human DPO (a counterparty/coordinator cannot).
    try:
        owner_uuid = (D(V.me()) or {}).get("owner_uuid")
        if owner_uuid:
            V.add_participant(room, owner_uuid)
            print(f"[director] Lumen human DPO added by vault ({owner_uuid[:8]}…)")
    except BandClientError as e:
        print(f"[director] could not add owner human ({e.status}); approve manually in the owner UI")

    print(f"[director] waiting {GRACE}s for agents to subscribe…")
    time.sleep(GRACE)
    seen = {m.get("id") for m in msgs_of(A, room)}
    transcript = []

    def mention(handle, aid):
        return [{"id": aid, "handle": handle}]

    A.send_message(
        room,
        f"@{h_modeler} Kick-off ({deal}): {SCENARIO.buyer['goal']}. {SCENARIO.owner['name']}'s "
        f"custodian @{h_vault} is in the room — ask them for the data you need.",
        mentions=mention(h_modeler, modeler.agent_id),
    )
    print("[director] kicked off modeler\n")

    relayed = accepted = approve_prompted = False
    passed = False
    deadline = time.time() + 360
    while time.time() < deadline and not passed:
        time.sleep(5)
        for m in msgs_of(A, room):
            mid = m.get("id")
            if mid in seen:
                continue
            seen.add(mid)
            s = (m.get("sender_name") or "").strip()
            sid = m.get("sender_id") or ""
            c = m.get("content") or ""
            transcript.append({"sender": s, "sender_id": sid, "content": c})
            print(f"  [{s or sid[:8]}] {c.replace(chr(10), ' ')[:150]}")
            env = parse_consent_envelope(c)
            is_vault = sid == vault.agent_id or "vault" in s.lower()
            is_checker = sid == checker.agent_id or "checker" in s.lower()

            if env and is_vault and env.get("decision") == "counter" and not relayed:
                relayed = True
                spec = SCENARIO.request.get("aggregate_spec", "an in-place capability that releases no raw data")
                A.send_message(
                    room,
                    f"@{h_modeler} {SCENARIO.owner['name']} counter-offered: \"{env.get('terms','')}\" — "
                    f"revise your request to: {spec}. Send it to @{h_vault}.",
                    mentions=mention(h_modeler, modeler.agent_id),
                )
                print("  [director] relayed counter -> modeler\n")

            if env and is_vault and env.get("decision") == "accept" and not accepted:
                accepted = True
                owner = SCENARIO.owner["name"]
                # 1) Explicit, LABELED gate-check: deliberately attempt an agent
                #    approval to prove it is refused (not the liaison cheating).
                print("\n  [director] vault ACCEPTED — running an explicit gate-check (agent approve must be refused)\n")
                A.send_message(
                    room,
                    f"@{h_vault} [gate-check] Before involving a human, verifying the control: an agent "
                    f"is attempting to authorize {deal}. Per policy this MUST be refused — APPROVE {deal}",
                    mentions=mention(h_vault, vault.agent_id),
                )

            # After the gate-check is refused, hand off cleanly to the OWNER human (once).
            if accepted and not approve_prompted and is_vault and "human" in c.lower() and mid:
                approve_prompted = True
                owner = SCENARIO.owner["name"]
                A.send_message(
                    room,
                    f"@{h_vault} Gate verified — agent approval correctly refused. Handing off to the "
                    f"{owner} data owner: only their first-party human may authorize {deal}.",
                    mentions=mention(h_vault, vault.agent_id),
                )
                print("\n" + "!" * 64)
                print(f"  ACTION NEEDED: in the {owner} (Lumen) account UI, open room")
                print(f"  '{ROOM_TITLE}' and post:   APPROVE {deal}")
                print("  (the vault accepts authorization ONLY from a first-party owner human)")
                print("!" * 64 + "\n")

            if is_checker and ("PASS" in c or "BLOCK" in c):
                passed = "PASS" in c
                print(f"\n  [director] checker verdict: {'PASS' if passed else 'BLOCKED'}")
                break
        else:
            if not passed:
                left = int(deadline - time.time())
                print(f"  [director] …watching ({left}s)" + ("  [waiting for owner-human APPROVE]" if approve_prompted else ""))
            continue
        break

    Path("proof").mkdir(exist_ok=True)
    Path("proof/live-proof.json").write_text(json.dumps(
        {"_comment": "Live full run: coordinator + modeler + checker + vault + owner human on Band.",
         "deal_room_id": room, "deal_id": deal, "reached_accept": accepted, "checker_pass": passed,
         "transcript": transcript}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + "=" * 60)
    print(f"  FULL RUN: accept={accepted}  checker_pass={passed}  ({len(transcript)} msgs)")
    print("  -> proof/live-proof.json")
    print("=" * 60)
    return 0 if passed else (2 if accepted else 1)


if __name__ == "__main__":
    sys.exit(main())
