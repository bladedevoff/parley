"""MAKE-OR-BREAK SPIKE: cross-org contact handshake + recruit into a room.

Pure REST, ZERO LLM cost. Proves the riskiest part of Parley works on the live
platform: an agent in org A (@northwind) can recruit a STRANGER agent in org B
(@lumen) — which requires a bilateral agent<->agent contact, then add_participant.

Steps:
  1. coordinator (org A) creates a deal room (or reuses one).
  2. coordinator sends a cross-org contact request to @lumen-retail/vault.
  3. vault (org B) lists its pending requests and APPROVES.
  4. coordinator lists peers (vault should now be a contact, recruitable).
  5. coordinator add_participant(vault) into the deal room.
  6. coordinator get_participants -> assert vault is in the room (live roster change).

Run:  uv run python scripts/spike_cross_org.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parley.config import load_creds
from parley.common.band_client import BandRestClient, BandClientError


def jprint(label, obj):
    import json
    s = json.dumps(obj, indent=2, ensure_ascii=False)
    if len(s) > 1500:
        s = s[:1500] + "\n  ...(truncated)"
    print(f"\n--- {label} ---\n{s}")


def D(resp):
    """Unwrap the Band {"data": ...} envelope."""
    if isinstance(resp, dict) and "data" in resp:
        return resp["data"]
    return resp


def main() -> int:
    coord = load_creds("COORDINATOR")
    vault = load_creds("VAULT")
    A = BandRestClient(coord.api_key)   # org A: northwind/coordinator
    B = BandRestClient(vault.api_key)   # org B: lumen/vault

    print(f"Coordinator: {coord.handle}  (org {coord.account})")
    print(f"Vault:       {vault.handle}  (org {vault.account})")

    # 1) Create (or reuse) a deal room owned by coordinator.
    room_id = None
    try:
        rooms = D(A._request("GET", "chats")) or []
        if isinstance(rooms, dict):
            rooms = rooms.get("chats") or rooms.get("rooms") or []
        for r in rooms:
            title = (r.get("title") or r.get("name") or "")
            if "parley" in title.lower() or "deal" in title.lower():
                room_id = r.get("id") or r.get("chat_id")
                print(f"\n[1] Reusing existing room: {room_id} ({title})")
                break
    except BandClientError as e:
        print(f"\n[1] list chats failed (will create): {e}")

    if not room_id:
        # Schema (verified from OpenAPI): {"chat": {"title": str}}; OMIT task_id (must be uuid).
        try:
            created = D(A._request("POST", "chats", body={"chat": {"title": "Parley Deal Room"}}))
            room_id = (created or {}).get("id") or (created or {}).get("chat_id")
            jprint("[1] created room", created)
        except BandClientError as e:
            print(f"\n[1] create room FAILED: {e}")
            return 1
    print(f"\n[1] deal room_id = {room_id}")
    if not room_id:
        print("[1] could not extract room_id; aborting")
        return 1

    # 2) Coordinator sends cross-org contact request to vault.
    try:
        resp = A.add_contact(vault.handle, message="Northwind requests collaboration on retail cohort aggregates. No raw PII leaves Lumen.")
        jprint("[2] add_contact response", resp)
    except BandClientError as e:
        if e.status == 409 or "exist" in e.body.lower() or "already" in e.body.lower():
            print(f"\n[2] contact already exists/pending (ok): {e.status}")
        else:
            print(f"\n[2] add_contact FAILED: {e}")

    # 3) Vault lists pending requests and approves.
    approved = False
    try:
        reqs = D(B._request("GET", "contacts/requests"))
        received = (reqs or {}).get("received") if isinstance(reqs, dict) else (reqs or [])
        jprint("[3] vault received requests", received)
        req_id = None
        for it in (received or []):
            frm = str(it.get("from_handle") or it.get("from_name") or "")
            if "coordinator" in frm.lower() or "northwind" in frm.lower():
                req_id = it.get("id") or it.get("request_id")
                break
        try:
            if req_id:
                r = D(B.respond_contact_request("approve", request_id=req_id))
            else:
                r = D(B.respond_contact_request("approve", handle=coord.handle))
            jprint("[3] vault approve response", r)
            approved = True
        except BandClientError as e:
            if e.status == 409 or "already" in e.body.lower():
                print(f"[3] already approved (ok): {e.status}")
                approved = True
            else:
                print(f"[3] approve FAILED: {e}")
    except BandClientError as e:
        print(f"\n[3] list requests FAILED: {e}")
        approved = True

    # 4) Coordinator lists peers; vault should be recruitable now.
    try:
        peers = D(A.lookup_peers(not_in_chat=room_id))
        items = peers if isinstance(peers, list) else (peers or {}).get("peers") or []
        handles = [p.get("handle") for p in (items or [])]
        jprint("[4] coordinator peers (handles)", handles)
        vault_peer = next((p for p in (items or []) if "vault" in str(p.get("handle", "")).lower()), None)
        jprint("[4] vault as peer", vault_peer)
    except BandClientError as e:
        print(f"\n[4] lookup_peers FAILED: {e}")
        vault_peer = None

    # 5) Recruit vault into the deal room.
    vault_id = (vault_peer or {}).get("id") if vault_peer else vault.agent_id
    try:
        added = A.add_participant(room_id, vault_id, role="member")
        jprint("[5] add_participant response", added)
    except BandClientError as e:
        if e.status == 409:
            print(f"\n[5] vault already in room (409 = idempotent OK)")
        elif e.status == 403:
            print(f"\n[5] add_participant 403 — contact not approved yet. body={e.body[:300]}")
            return 1
        else:
            print(f"\n[5] add_participant FAILED: {e}")
            return 1

    # 6) Verify roster.
    try:
        parts = D(A.get_participants(room_id))
        items = parts if isinstance(parts, list) else (parts or {}).get("participants") or []
        handles = [p.get("handle") or p.get("name") for p in (items or [])]
        jprint("[6] room participants", handles)
        vault_in = any("vault" in str(h).lower() for h in handles)
        print()
        print("=" * 60)
        print(f"  CROSS-ORG RECRUIT: {'SUCCESS - vault is in the room [OK]' if vault_in else 'vault NOT in room [FAIL]'}")
        print(f"  deal room_id = {room_id}")
        print("=" * 60)
        return 0 if vault_in else 1
    except BandClientError as e:
        print(f"\n[6] get_participants FAILED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
