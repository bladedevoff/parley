"""Real-time transcript recorder — captures the FULL room as it happens.

Band's Human/Memory APIs are Enterprise-gated and agent GET /messages only
returns an agent's own @mentions (and only while unprocessed). So to capture a
complete transcript — including the human DPO's APPROVE (which @mentions the
vault) — we poll ALL FOUR agent keys frequently DURING a live run and union
everything ever seen by id. Run this in parallel with a live run/director.

    uv run python scripts/record_run.py <room_id> <out.json> [seconds]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parley.config import load_creds
from parley.common.band_client import BandRestClient, BandClientError


def main() -> int:
    room = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else f"proof/recorded-{room[:8]}.json"
    secs = int(sys.argv[3]) if len(sys.argv) > 3 else 420

    clients = {}
    for name in ("COORDINATOR", "MODELER", "CHECKER", "VAULT"):
        try:
            clients[name] = BandRestClient(load_creds(name).api_key)
        except Exception as e:
            print(f"[{name}] creds error: {e}")

    seen: dict[str, dict] = {}
    print(f"[recorder] room {room}; polling all {len(clients)} agent views for {secs}s ...")
    deadline = time.time() + secs
    while time.time() < deadline:
        for name, c in clients.items():
            try:
                d = c.get_messages(room, page_size=80)
                data = d.get("data", d) if isinstance(d, dict) else d
                msgs = data if isinstance(data, list) else (data or {}).get("messages", [])
                for m in msgs:
                    mid = m.get("id")
                    if mid and mid not in seen:
                        seen[mid] = m
                        who = m.get("sender_name", "?")
                        print(f"  +[{who}/{(m.get('sender_type') or '?')[0]}] {(m.get('content') or '').replace(chr(10),' ')[:80]}")
            except BandClientError:
                pass
        # stop early once we've seen a checker PASS
        blob = " ".join((m.get("content") or "") for m in seen.values())
        if "PASS" in blob and any((m.get("sender_type") == "User") for m in seen.values()):
            print("[recorder] human message + checker PASS captured — finishing")
            break
        time.sleep(1.5)

    msgs = sorted(seen.values(), key=lambda x: x.get("inserted_at", ""))
    transcript = [{"sender": m.get("sender_name"), "sender_type": m.get("sender_type"),
                   "content": m.get("content"), "at": m.get("inserted_at")} for m in msgs]
    blob = " ".join((t.get("content") or "") for t in transcript)
    flags = {
        "messages": len(transcript),
        "human_approve_present": any(t.get("sender_type") == "User" and "approve" in (t.get("content") or "").lower() for t in transcript),
        "agent_approve_refused": any(x in blob for x in ("Refused", "cannot be honored", "does not count")),
        "has_counter": "counter" in blob.lower(),
        "has_accept": '"decision": "accept"' in blob or "decision=accept" in blob,
        "checker_pass": "PASS" in blob,
        "rows_exported_zero": any(x in blob for x in ("rows_exported=0", "rows_exported: 0", '"rows_exported": 0')),
    }
    proof = {"_comment": "Real-time recorded COMPLETE transcript (all 4 agent views unioned live) — includes the human DPO APPROVE.",
             "deal_room_id": room, "flags": flags, "transcript": transcript}
    Path("proof").mkdir(exist_ok=True)
    Path(out).write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[recorder] saved {len(transcript)} msgs -> {out}\nflags: {json.dumps(flags)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
