"""Tests for cross-deal memory (agents remember + evolve cross-org agreements).

Uses the JSONL backend so it runs offline with no Band — but the same DealMemory
drives the real Band backend in production (BandMemoryBackend)."""

from __future__ import annotations

from parley.memory import DealMemory, JsonlMemoryBackend, agreement_content


def _mem(tmp_path):
    return DealMemory(backend=JsonlMemoryBackend(path=tmp_path / "memories.jsonl"))


def test_recall_is_empty_for_unknown_counterparty(tmp_path):
    m = _mem(tmp_path)
    assert m.recall_agreement(counterparty="northwind") is None


def test_record_then_recall_agreement(tmp_path):
    m = _mem(tmp_path)
    m.record_agreement(counterparty="northwind", deal_id="deal-1",
                       capability="cohort_aggregate", terms="aggregates only; k>=25")
    hit = m.recall_agreement(counterparty="northwind")
    assert hit is not None
    assert "cohort_aggregate" in hit["content"]
    assert "northwind" in hit["content"]


def test_memory_is_isolated_per_counterparty(tmp_path):
    m = _mem(tmp_path)
    m.record_agreement(counterparty="northwind", deal_id="deal-1",
                       capability="cohort_aggregate", terms="k>=25")
    m.record_agreement(counterparty="acme", deal_id="deal-9",
                       capability="code_scan", terms="findings only")
    assert "cohort_aggregate" in m.recall_agreement(counterparty="northwind")["content"]
    assert "code_scan" in m.recall_agreement(counterparty="acme")["content"]


def test_supersede_creates_a_new_active_version(tmp_path):
    m = _mem(tmp_path)
    mid = m.record_agreement(counterparty="northwind", deal_id="deal-1",
                            capability="cohort_aggregate", terms="k>=25")
    m.update_terms(mid, counterparty="northwind", deal_id="deal-1",
                  capability="cohort_aggregate", terms="k>=50 (tightened)")
    # only the new version is active; it reflects the updated terms
    hit = m.recall_agreement(counterparty="northwind")
    assert "k>=50" in hit["content"]
    # the superseded original is no longer returned as active
    actives = m.backend.list(query="counterparty northwind")
    assert all("k>=25" not in r["content"] or "k>=50" in r["content"] for r in actives)


def test_band_backend_falls_back_to_jsonl_when_plan_gated(tmp_path):
    from parley.memory import BandMemoryBackend

    class GatedClient:
        def create_memory(self, *a, **k):
            raise type("E", (Exception,), {"status": 403})()
        def list_memories(self, *a, **k):
            raise type("E", (Exception,), {"status": 403})()

    be = BandMemoryBackend(GatedClient(), fallback=JsonlMemoryBackend(path=tmp_path / "m.jsonl"))
    mid = be.store(agreement_content("northwind", "deal-1", "cohort_aggregate", "k>=25"),
                  subject_id=None, tags=["parley"])
    assert mid and be.used_fallback is True
    assert be.list(query="northwind")  # served from JSONL
