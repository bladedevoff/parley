"""In-memory deal state. Pure — no band import.

Tracks, per deal, the latest decision, its terms, and whether a human has
acknowledged (approved) it.  Dict-backed so it serializes trivially.
"""

from __future__ import annotations

from typing import Any, Optional


class DealState:
    """Dict-backed store of per-deal negotiation state.

    Each entry has the shape::

        {"decision": <str|None>, "terms": <Any>, "human_ack": <bool>}
    """

    def __init__(self) -> None:
        self._deals: dict[str, dict[str, Any]] = {}

    def _entry(self, deal_id: Any) -> dict[str, Any]:
        key = str(deal_id)
        entry = self._deals.get(key)
        if entry is None:
            entry = {"decision": None, "terms": None, "human_ack": False}
            self._deals[key] = entry
        return entry

    def record(self, deal_id: Any, decision: str, terms: Optional[Any] = None) -> None:
        """Record (or overwrite) the latest decision + terms for a deal.

        Does not reset an existing human acknowledgement.
        """
        entry = self._entry(deal_id)
        entry["decision"] = decision
        entry["terms"] = terms

    def set_human_ack(self, deal_id: Any, ok: bool) -> None:
        """Set the human acknowledgement flag for a deal."""
        entry = self._entry(deal_id)
        entry["human_ack"] = bool(ok)

    def is_acked(self, deal_id: Any) -> bool:
        """Return True iff a human has acknowledged (approved) this deal."""
        return bool(self._entry(deal_id)["human_ack"])

    def get(self, deal_id: Any) -> dict[str, Any]:
        """Return the entry dict (decision, terms, human_ack) for a deal.

        Creates a default entry if the deal is unknown.
        """
        return self._entry(deal_id)
