"""Tests for the aggregate validator (pure). No band import."""

from __future__ import annotations

from parley.tools.validator import validate_aggregates


EXPECTED_SCHEMA = ["bucket", "count"]


def test_clean_aggregates_pass():
    payload = {
        "columns": ["bucket", "count"],
        "rows": [
            {"bucket": "west", "count": 27},
            {"bucket": "east", "count": 250},
        ],
    }
    result = validate_aggregates(payload, EXPECTED_SCHEMA, k_floor=25)

    assert result["verdict"] == "PASS"
    assert result["findings"] == []


def test_k_anonymity_violation_blocks():
    payload = {
        "columns": ["bucket", "count"],
        "rows": [
            {"bucket": "west", "count": 30},
            {"bucket": "rare", "count": 3},  # below the k_floor
        ],
    }
    result = validate_aggregates(payload, EXPECTED_SCHEMA, k_floor=25)

    assert result["verdict"] == "BLOCKED"
    assert "k_anonymity_violation" in result["findings"]


def test_pii_leak_on_email_column_blocks():
    payload = {
        "columns": ["email", "count"],
        "rows": [{"bucket": "a@b.com", "count": 100}],
    }
    result = validate_aggregates(payload, ["email", "count"], k_floor=25)

    assert result["verdict"] == "BLOCKED"
    assert "PII_LEAK" in result["findings"]


def test_pii_leak_on_ssn_column_blocks():
    payload = {
        "columns": ["ssn", "count"],
        "rows": [{"bucket": "x", "count": 100}],
    }
    result = validate_aggregates(payload, ["ssn", "count"], k_floor=25)

    assert result["verdict"] == "BLOCKED"
    assert "PII_LEAK" in result["findings"]


def test_pii_leak_on_raw_payload_blocks():
    payload = {
        "columns": ["bucket", "count"],
        "rows": [{"bucket": "west", "count": 100}],
        "raw": [{"email": "a@b.com", "ssn": "123-45-6789"}],
    }
    result = validate_aggregates(payload, EXPECTED_SCHEMA, k_floor=25)

    assert result["verdict"] == "BLOCKED"
    assert "PII_LEAK" in result["findings"]


def test_unexpected_columns_blocks():
    payload = {
        "columns": ["bucket", "count", "region_secret"],
        "rows": [{"bucket": "west", "count": 100}],
    }
    result = validate_aggregates(payload, EXPECTED_SCHEMA, k_floor=25)

    assert result["verdict"] == "BLOCKED"
    assert "unexpected_columns" in result["findings"]
