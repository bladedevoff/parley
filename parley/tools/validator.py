"""Aggregate validator. Pure — no band import.

Checks an aggregate payload for k-anonymity violations, unexpected columns,
and PII leakage before it is allowed to leave an org.
"""

from __future__ import annotations

from typing import Any

DEFAULT_K_FLOOR = 25

# Substrings that, if present in a column name, signal direct PII.
_PII_TOKENS = ("ssn", "email", "phone", "name")


def validate_aggregates(
    payload: Any,
    expected_schema: Any,
    k_floor: int = DEFAULT_K_FLOOR,
) -> dict:
    """Validate an aggregate payload against an expected schema + k-floor.

    Findings:
        - ``k_anonymity_violation``: any row's ``count`` is below ``k_floor``.
        - ``unexpected_columns``: columns present that aren't in the schema.
        - ``PII_LEAK``: a top-level ``raw`` key exists, or any column name
          contains an obvious PII token (ssn/email/phone/name).

    Args:
        payload: ``{"columns": [...], "rows": [{"count": ...}, ...], ...}``.
        expected_schema: Iterable of allowed column names.
        k_floor: Minimum acceptable per-row count.

    Returns:
        ``{"verdict": "PASS"|"BLOCKED", "findings": [...]}``.
    """
    findings: list[str] = []

    payload_dict = payload if isinstance(payload, dict) else {}
    columns = list(payload_dict.get("columns", []) or [])
    rows = list(payload_dict.get("rows", []) or [])
    schema = set(expected_schema or [])

    # k-anonymity: every reported row must clear the floor.
    for row in rows:
        count = row.get("count") if isinstance(row, dict) else None
        if isinstance(count, (int, float)) and count < k_floor:
            findings.append("k_anonymity_violation")
            break

    # Unexpected columns: anything outside the declared schema.
    if schema and any(col not in schema for col in columns):
        findings.append("unexpected_columns")

    # PII leak: explicit raw payload, or a PII-looking column name.
    if "raw" in payload_dict:
        findings.append("PII_LEAK")
    else:
        for col in columns:
            col_l = str(col).lower()
            if any(token in col_l for token in _PII_TOKENS):
                findings.append("PII_LEAK")
                break

    verdict = "PASS" if not findings else "BLOCKED"
    return {"verdict": verdict, "findings": findings}
