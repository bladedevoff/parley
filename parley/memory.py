"""Cross-deal memory — agents REMEMBER and evolve cross-org agreements.

Band gives agents a structured, cross-agent memory store (system/type/segment/
scope + supersede versioning). Parley uses it so that when the SAME counterparty
returns, the vault recalls the terms it already agreed (capability, k_floor,
no-raw) and short-circuits the negotiation — and `supersede` keeps a versioned
audit chain when terms change.

Two backends behind one interface so it always works:
- ``BandMemoryBackend``  — real Band REST (/agent/memories, supersede).
- ``JsonlMemoryBackend`` — local JSONL fallback (used offline / in tests, or when
  the Band Memory API is plan-gated and returns 402/403).

``DealMemory`` is pure logic over a backend; the JSONL path imports no ``band``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

# Search-safe envelope: agents store a compact, queryable record of an agreement.
MEMORY_SYSTEM = "long_term"
MEMORY_TYPE = "episodic"
MEMORY_SEGMENT = "agent"


def agreement_content(counterparty: str, deal_id: str, capability: str, terms: str) -> str:
    """A compact, search-safe memory line for a settled cross-org agreement."""
    return (
        f"parley_agreement counterparty {counterparty} deal {deal_id} "
        f"capability {capability} terms {terms}"
    )


class MemoryBackend(Protocol):
    def store(self, content: str, *, subject_id: Optional[str], tags: list[str]) -> str: ...
    def list(self, *, query: Optional[str] = None) -> list[dict]: ...
    def supersede(self, memory_id: str, content: str) -> str: ...


@dataclass
class JsonlMemoryBackend:
    """Append-only JSONL store (single machine). Used offline / in tests / when
    the Band Memory API is plan-gated. Supersede chains via ``superseded_by``."""

    path: Path = field(default_factory=lambda: Path(".parley/memories.jsonl"))
    _clock: int = 0

    def _now(self) -> str:
        # Monotonic, deterministic-ish stamp without wall clock for testability.
        self._clock += 1
        return f"t{self._clock}"

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def _append(self, rec: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def store(self, content: str, *, subject_id: Optional[str], tags: list[str]) -> str:
        mid = f"mem-{len(self._read()) + 1}"
        self._append({"id": mid, "content": content, "subject_id": subject_id,
                      "tags": tags, "stamp": self._now(), "superseded_by": None})
        return mid

    def list(self, *, query: Optional[str] = None) -> list[dict]:
        recs = [r for r in self._read() if r.get("superseded_by") is None]
        if query:
            q = query.lower()
            recs = [r for r in recs if q in (r.get("content", "").lower())]
        return recs

    def supersede(self, memory_id: str, content: str) -> str:
        recs = self._read()
        new_id = f"mem-{len(recs) + 1}"
        for r in recs:
            if r.get("id") == memory_id:
                r["superseded_by"] = new_id
        # rewrite with supersede links updated, then append the new version
        self.path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
            encoding="utf-8",
        )
        self._append({"id": new_id, "content": content, "subject_id": None,
                      "tags": ["parley", "supersedes:" + memory_id], "stamp": self._now(),
                      "superseded_by": None})
        return new_id


def _unwrap(resp: Any) -> Any:
    """Unwrap a Band REST envelope: ``{"data": ...}`` -> ``...``, else passthrough."""
    return resp.get("data", resp) if isinstance(resp, dict) else resp


class BandMemoryBackend:
    """Real Band memory via a BandRestClient-like object. Falls back to a
    provided JSONL backend if the API is plan-gated (402/403/404)."""

    def __init__(self, client: Any, fallback: Optional[JsonlMemoryBackend] = None) -> None:
        self.client = client
        self.fallback = fallback or JsonlMemoryBackend()
        self.used_fallback = False

    def _gated(self, exc: Any) -> bool:
        return getattr(exc, "status", None) in (402, 403, 404)

    def store(self, content: str, *, subject_id: Optional[str], tags: list[str]) -> str:
        try:
            resp = self.client.create_memory(content, scope=("subject" if subject_id else "organization"),
                                              subject_id=subject_id, system=MEMORY_SYSTEM,
                                              type=MEMORY_TYPE, segment=MEMORY_SEGMENT, tags=tags)
            data = _unwrap(resp)
            return (data or {}).get("id", "band-mem")
        except Exception as exc:  # plan-gated or transient -> JSONL
            if self._gated(exc):
                self.used_fallback = True
                return self.fallback.store(content, subject_id=subject_id, tags=tags)
            raise

    def list(self, *, query: Optional[str] = None) -> list[dict]:
        try:
            resp = self.client.list_memories(query=query)
            data = _unwrap(resp)
            return data if isinstance(data, list) else (data or {}).get("memories", [])
        except Exception as exc:
            if self._gated(exc):
                self.used_fallback = True
                return self.fallback.list(query=query)
            raise

    def supersede(self, memory_id: str, content: str) -> str:
        try:
            resp = self.client.supersede_memory(memory_id, content)
            data = _unwrap(resp)
            return (data or {}).get("id", "band-mem-v2")
        except Exception as exc:
            if self._gated(exc):
                self.used_fallback = True
                return self.fallback.supersede(memory_id, content)
            raise


@dataclass
class DealMemory:
    """High-level cross-deal memory used by the vault."""

    backend: MemoryBackend

    def record_agreement(self, *, counterparty: str, deal_id: str, capability: str,
                         terms: str, subject_id: Optional[str] = None) -> str:
        content = agreement_content(counterparty, deal_id, capability, terms)
        return self.backend.store(content, subject_id=subject_id,
                                  tags=["parley", "agreement", f"cp:{counterparty}"])

    def recall_agreement(self, *, counterparty: str) -> Optional[dict]:
        """Return the most recent active agreement with this counterparty, or None."""
        hits = self.backend.list(query=f"counterparty {counterparty}")
        return hits[-1] if hits else None

    def update_terms(self, memory_id: str, *, counterparty: str, deal_id: str,
                     capability: str, terms: str) -> str:
        content = agreement_content(counterparty, deal_id, capability, terms)
        return self.backend.supersede(memory_id, content)
