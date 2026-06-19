"""Export gating + in-place aggregation. Pure — no band import.

The export gate ensures destructive / data-leaving operations cannot run
without an explicit human acknowledgement.  :func:`in_place_aggregate` is the
safe primitive: it returns only k-suppressed aggregate counts, never raw
records, and never exports rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_K_FLOOR = 25


class ConsentMissing(PermissionError):
    """Raised when a destructive export is attempted without human consent."""


@dataclass
class ExportTool:
    """A guarded callable. Destructive runs require ``human_ack=True``."""

    name: str
    run: Callable[..., Any]
    destructive: bool = True

    def guarded_run(self, *, human_ack: bool = False, **kwargs: Any) -> Any:
        """Run the tool, gating destructive ones behind ``human_ack``.

        Raises:
            ConsentMissing: if the tool is destructive and ``human_ack`` is False.
        """
        if self.destructive and not human_ack:
            raise ConsentMissing(
                f"Export tool {self.name!r} is destructive and requires human consent"
            )
        return self.run(**kwargs)


def in_place_aggregate(
    query: Any,
    dataset: Any,
    k_floor: int = DEFAULT_K_FLOOR,
) -> dict:
    """Aggregate *dataset* into k-suppressed bucket counts. Never exports rows.

    The implementation is intentionally minimal and safe: it groups records by
    a ``bucket`` field, counts each bucket, and drops (suppresses) any bucket
    whose count is below ``k_floor``.  No raw record ever leaves this function.

    Args:
        query: Opaque query descriptor (accepted for interface compatibility;
            an optional ``columns`` key/attr names the output columns).
        dataset: Iterable of records (dicts) with a ``bucket`` field, or an
            iterable of pre-bucketed values.
        k_floor: Minimum count for a bucket to be reported.

    Returns:
        ``{"columns": [...], "rows": [{"bucket", "count"}], "rows_exported": 0}``
        where every emitted ``count`` is ``>= k_floor``.
    """
    columns = _extract_columns(query)

    counts: dict[Any, int] = {}
    for record in dataset or []:
        bucket = _record_bucket(record)
        counts[bucket] = counts.get(bucket, 0) + 1

    rows = [
        {"bucket": bucket, "count": count}
        for bucket, count in counts.items()
        if count >= k_floor
    ]

    return {
        "columns": columns,
        "rows": rows,
        "rows_exported": 0,
    }


def _extract_columns(query: Any) -> list:
    """Best-effort extraction of column names from a query descriptor."""
    if isinstance(query, dict):
        cols = query.get("columns")
        if cols:
            return list(cols)
    cols = getattr(query, "columns", None)
    if cols:
        return list(cols)
    return ["bucket", "count"]


def _record_bucket(record: Any) -> Any:
    """Get the bucket key for a record (dict ``bucket`` field or the value itself)."""
    if isinstance(record, dict):
        return record.get("bucket")
    return record
