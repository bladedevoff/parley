"""Human approval gate. Pure — no band import.

Recognizes ``APPROVE <deal_id>`` / ``DENY <deal_id>`` messages from a human
participant so the runtime can flip a deal's human-ack flag.
"""

from __future__ import annotations

import re
from typing import Optional

# ^(APPROVE|DENY) <deal_id>$  — case-insensitive on the verb.
ACK_RE = re.compile(r"^\s*(APPROVE|DENY)\s+(\S+)\s*$", re.IGNORECASE)


def parse_human_ack(message_content: str, sender_is_human: bool) -> Optional[dict]:
    """Parse a human approval/denial command.

    Args:
        message_content: Raw message text.
        sender_is_human: Whether the sender is a human (only humans may ack).

    Returns:
        ``{"action": "APPROVE"|"DENY", "deal_id": <str>}`` on a match from a
        human sender, else ``None``.
    """
    if not sender_is_human or not message_content:
        return None

    match = ACK_RE.match(message_content)
    if not match:
        return None

    return {
        "action": match.group(1).upper(),
        "deal_id": match.group(2),
    }
