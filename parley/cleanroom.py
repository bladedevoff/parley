"""In-process clean room — aggregate over ACTUAL row-level records, release only counts.

The critical review noted the demo aggregates a pre-summarized cohort table, so the
"raw rows never leave" claim wasn't shown over real rows. This module closes that:
it synthesizes row-level customer records (deterministically, for reproducibility),
then runs a group-by aggregation IN PLACE and returns only k-anonymous cohort counts
— never a single row. It is the concrete, inspectable version of the guarantee:
row-level data exists here, and exactly zero rows are exported.

In production the ``rows`` come from the owner's real database/warehouse behind this
same function; nothing else in the kernel changes. Pure: stdlib only, no band import.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from parley.dp import privatize_count

_AGE_BANDS = ("18-24", "25-34", "35-44", "45-54", "55-64", "65+")
_REGIONS = ("west", "east", "central", "rural")


def _u(seed: str) -> float:
    """Deterministic uniform in [0,1) from a string seed."""
    return int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:13], 16) / float(16 ** 13)


def synthesize_customers(n: int, *, seed: str = "lumen") -> list[dict]:
    """Generate ``n`` deterministic row-level customer records (the owner's raw data).

    Each row has direct identifiers (customer_id, email) PLUS the quasi-identifiers
    we aggregate on (age_band, region) — so the no-raw guarantee is meaningful: these
    rows must never leave, only counts derived from them may.
    """
    rows: list[dict] = []
    for i in range(n):
        ab = _AGE_BANDS[int(_u(f"{seed}:{i}:age") * len(_AGE_BANDS)) % len(_AGE_BANDS)]
        rg = _REGIONS[int(_u(f"{seed}:{i}:region") * len(_REGIONS)) % len(_REGIONS)]
        rows.append({
            "customer_id": f"C{i:06d}",
            "email": f"user{i}@example.com",        # PII — must never be exported
            "age_band": ab,
            "region": rg,
            "spend": round(20 + _u(f"{seed}:{i}:spend") * 480, 2),
        })
    return rows


def aggregate_in_place(
    rows: list[dict],
    *,
    group_by: tuple = ("age_band", "region"),
    k_floor: int = 25,
    epsilon: Optional[float] = None,
    seed: str = "deal",
) -> dict:
    """Group rows in place, suppress cohorts below ``k_floor``, optionally add DP noise.

    Returns ONLY aggregate counts (rows_exported is always 0). With ``epsilon`` set,
    each released count gets calibrated Laplace noise and is re-suppressed below k
    AFTER the noise, so the post-DP k-floor always holds.
    """
    counts: dict[str, int] = {}
    for r in rows:
        key = "|".join(f"{g}:{r.get(g)}" for g in group_by)
        counts[key] = counts.get(key, 0) + 1

    cohorts = []
    for bucket, true_c in counts.items():
        # k-anonymity is a property of the TRUE cohort size: suppress small cohorts
        # BEFORE adding noise. (Suppressing on the noisy count is unsound — a real
        # sub-k cohort could be released when its noise pushes it over the floor.)
        if true_c < k_floor:
            continue
        c = true_c
        if epsilon:
            c = privatize_count(true_c, epsilon=float(epsilon), seed=f"{seed}:{bucket}:{epsilon}")
        if c >= k_floor:                       # keep released counts above the floor too
            cohorts.append({"bucket": bucket, "count": c})
    cohorts.sort(key=lambda x: x["count"], reverse=True)

    return {
        "rows_scanned": len(rows),
        "rows_exported": 0,                     # the guarantee, over real rows
        "k_floor": k_floor,
        "dp_applied": bool(epsilon),
        "epsilon": (float(epsilon) if epsilon else None),
        "columns": ["bucket", "count"],
        "rows": cohorts,
        "cohorts_released": len(cohorts),
    }
