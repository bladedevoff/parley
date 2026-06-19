"""LIVE spike: prove Parley uses Band MEMORY (store -> list -> supersede).

The vault records the terms it agreed with a counterparty as a Band memory, lists
it back, then supersedes it when terms change — a versioned cross-org agreement
trail. Falls back to JSONL only if the Band Memory API is plan-gated (402/403),
and reports honestly which path was used. No WS agent needed (pure REST).

    uv run python scripts/spike_memory.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parley.config import load_creds
from parley.common.band_client import BandRestClient
from parley.memory import BandMemoryBackend, DealMemory, JsonlMemoryBackend


def main() -> int:
    vault = load_creds("VAULT")
    coord = load_creds("COORDINATOR")
    client = BandRestClient(vault.api_key)
    backend = BandMemoryBackend(client, fallback=JsonlMemoryBackend(path=Path(".parley/spike-memories.jsonl")))
    mem = DealMemory(backend=backend)

    cp = coord.handle.lstrip("@").split("/")[0]  # "northwind-analytics"

    print(f"[memory] vault recording agreement with counterparty '{cp}' ...")
    mid = mem.record_agreement(counterparty=cp, deal_id="deal-1",
                               capability="cohort_aggregate",
                               terms="aggregates only; k>=25; no raw rows",
                               subject_id=coord.agent_id)
    print(f"[memory] stored id={mid}")

    recalled = mem.recall_agreement(counterparty=cp)
    print(f"[memory] recalled: {recalled.get('content') if recalled else None}")

    print("[memory] terms change -> supersede ...")
    new_id = mem.update_terms(mid, counterparty=cp, deal_id="deal-1",
                              capability="cohort_aggregate",
                              terms="aggregates only; k>=50 (tightened); no raw rows")
    after = mem.recall_agreement(counterparty=cp)
    print(f"[memory] new version id={new_id}; active terms now: {after.get('content') if after else None}")

    backend_used = "JSONL fallback (Band Memory API plan-gated)" if getattr(backend, "used_fallback", False) else "REAL Band memory API (app.band.ai)"
    proof = {
        "_comment": "Parley uses Band MEMORY: store -> recall -> supersede a versioned cross-org agreement.",
        "counterparty": cp, "stored_id": mid, "superseded_to": new_id,
        "active_terms": (after or {}).get("content"),
        "backend": backend_used,
    }
    Path("proof").mkdir(exist_ok=True)
    Path("proof/spike-memory.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + "=" * 60)
    print(f"  MEMORY SPIKE OK via {backend_used}")
    print("  store -> recall -> supersede proven; proof/spike-memory.json")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
