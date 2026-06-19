"""Tests for the in-process clean room: aggregate real rows, export zero rows."""

from __future__ import annotations

from parley.cleanroom import aggregate_in_place, synthesize_customers


def test_synthesis_is_deterministic_and_row_level():
    a = synthesize_customers(200, seed="lumen")
    b = synthesize_customers(200, seed="lumen")
    assert a == b                      # reproducible
    assert len(a) == 200
    assert {"customer_id", "email", "age_band", "region"} <= set(a[0])  # real rows w/ PII


def test_aggregate_exports_zero_rows_and_counts_sum():
    rows = synthesize_customers(500, seed="lumen")
    out = aggregate_in_place(rows, k_floor=1)   # k=1 so nothing is suppressed
    assert out["rows_exported"] == 0
    assert out["rows_scanned"] == 500
    assert sum(c["count"] for c in out["rows"]) == 500  # every row counted, none leaked


def test_k_floor_suppresses_small_cohorts():
    rows = synthesize_customers(300, seed="lumen")
    out = aggregate_in_place(rows, k_floor=25)
    assert all(c["count"] >= 25 for c in out["rows"])   # post-suppression floor holds


def test_no_raw_identifiers_in_output():
    rows = synthesize_customers(400, seed="lumen")
    out = aggregate_in_place(rows, k_floor=10)
    blob = str(out)
    assert "email" not in blob and "customer_id" not in blob and "@example.com" not in blob


def test_dp_keeps_post_noise_k_floor():
    rows = synthesize_customers(600, seed="lumen")
    out = aggregate_in_place(rows, k_floor=25, epsilon=1.0, seed="deal-1")
    assert out["dp_applied"] is True
    assert all(c["count"] >= 25 for c in out["rows"])   # re-suppressed AFTER noise
    assert out["rows_exported"] == 0


def test_true_subk_cohort_is_never_released_even_with_noise():
    # Soundness: a genuinely tiny (true-count < k) cohort must NEVER be released,
    # regardless of DP noise. Suppression is on the TRUE count, before noise.
    rows = [{"customer_id": f"C{i}", "email": f"u{i}@e.com", "age_band": "18-24", "region": "west"}
            for i in range(3)]                                   # a real 3-person cohort
    rows += [{"customer_id": f"D{i}", "email": f"v{i}@e.com", "age_band": "25-34", "region": "east"}
             for i in range(90)]                                 # a safe cohort
    tiny = "age_band:18-24|region:west"
    for s in range(50):                                          # many noise draws
        out = aggregate_in_place(rows, k_floor=25, epsilon=0.2, seed=f"trial{s}")
        assert tiny not in {c["bucket"] for c in out["rows"]}    # never leaks the 3-person cohort
