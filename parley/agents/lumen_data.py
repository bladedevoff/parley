"""The data owner's private in-place dataset, sourced from scenario.yaml.

This stands in for the owner org's customer database. It never leaves: the vault
only runs ``in_place_aggregate`` over it and returns k-suppressed cohort counts.
Edit the ``cohorts`` block in scenario.yaml to change it (one cohort is below
k_floor to demonstrate k-anonymity suppression).
"""

from __future__ import annotations

from parley.scenario import SCENARIO

# One record per customer, carrying only a cohort bucket (no direct identifiers).
DATASET: list[dict] = SCENARIO.dataset

# The aggregate query the vault runs in place once the deal is human-approved.
QUERY: dict = {"columns": ["bucket", "count"]}

# Total raw customers (demo narration).
TOTAL_CUSTOMERS = SCENARIO.total_customers
