"""Tests for the export gate + in-place aggregation. No band import."""

from __future__ import annotations

import pytest

from parley.tools.export_gate import (
    ConsentMissing,
    ExportTool,
    in_place_aggregate,
)


def test_guarded_run_raises_without_ack():
    tool = ExportTool(name="raw_export", run=lambda **kw: kw, destructive=True)
    with pytest.raises(ConsentMissing):
        tool.guarded_run(human_ack=False, table="customers")


def test_guarded_run_default_ack_is_false_and_raises():
    tool = ExportTool(name="raw_export", run=lambda **kw: kw, destructive=True)
    with pytest.raises(ConsentMissing):
        tool.guarded_run(table="customers")


def test_guarded_run_with_ack_runs_and_exports_no_rows():
    called = {}

    def runner(**kwargs):
        called.update(kwargs)
        # The safe export path only ever returns aggregates.
        return in_place_aggregate(kwargs.get("query"), kwargs.get("dataset"))

    tool = ExportTool(name="aggregate_export", run=runner, destructive=True)
    result = tool.guarded_run(
        human_ack=True,
        query={"columns": ["bucket", "count"]},
        dataset=[{"bucket": "a"} for _ in range(30)],
    )

    assert result["rows_exported"] == 0
    assert called["query"] == {"columns": ["bucket", "count"]}


def test_non_destructive_tool_runs_without_ack():
    tool = ExportTool(name="readonly", run=lambda **kw: "ran", destructive=False)
    assert tool.guarded_run(human_ack=False) == "ran"


def test_in_place_aggregate_never_returns_raw_rows():
    dataset = [{"bucket": "x", "ssn": "123-45-6789", "email": "a@b.com"} for _ in range(40)]
    out = in_place_aggregate({"columns": ["bucket", "count"]}, dataset, k_floor=25)

    assert out["rows_exported"] == 0
    for row in out["rows"]:
        # Only bucket + count, never raw fields.
        assert set(row.keys()) == {"bucket", "count"}
        assert "ssn" not in row
        assert "email" not in row
        assert row["count"] >= 25


def test_in_place_aggregate_suppresses_below_k_floor():
    dataset = (
        [{"bucket": "big"} for _ in range(30)]
        + [{"bucket": "small"} for _ in range(3)]
    )
    out = in_place_aggregate({"columns": ["bucket", "count"]}, dataset, k_floor=25)

    buckets = {row["bucket"] for row in out["rows"]}
    assert "big" in buckets
    assert "small" not in buckets  # k-suppressed
    for row in out["rows"]:
        assert row["count"] >= 25
