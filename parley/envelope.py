"""CONSENT envelope (de)serialization. Pure — no band import.

A CONSENT envelope is a small dict::

    {
        "type": "CONSENT",
        "deal_id": ...,
        "decision": "accept" | "decline" | "counter",
        "terms": ...,
        "rationale": ...,
        "confidence": ...,
    }

On the wire it is rendered as a human-readable header line followed by the
dict as a triple-backtick-fenced ``json`` code block, so it is both readable
in a chat room and machine-parseable.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

CONSENT_TYPE = "CONSENT"

# Matches a ```json ... ``` fenced block; group 1 is the JSON body.
_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n(.*?)\n?```",
    re.DOTALL | re.IGNORECASE,
)


def build_consent_envelope(
    deal_id: Any,
    decision: str,
    terms: Any,
    rationale: Any,
    confidence: Any,
) -> str:
    """Build the wire string for a CONSENT envelope.

    Returns a header line ``CONSENT decision=<decision>`` followed by a newline
    and the envelope dict as a triple-backtick-fenced ``json`` code block.
    """
    envelope = {
        "type": CONSENT_TYPE,
        "deal_id": deal_id,
        "decision": decision,
        "terms": terms,
        "rationale": rationale,
        "confidence": confidence,
    }
    body = json.dumps(envelope)
    return f"CONSENT decision={decision}\n```json\n{body}\n```"


def parse_consent_envelope(text: str) -> Optional[dict]:
    """Extract the CONSENT envelope dict from *text*.

    Scans every ```json fenced block, returning the first whose parsed object
    is a dict with ``type == "CONSENT"``.  Returns ``None`` if none match.
    """
    if not text:
        return None

    for match in _FENCE_RE.finditer(text):
        candidate = match.group(1).strip()
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict) and obj.get("type") == CONSENT_TYPE:
            return obj

    return None
