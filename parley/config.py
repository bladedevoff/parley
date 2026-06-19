"""Agent credential loading from environment (.env via python-dotenv).

Each Parley agent has three env vars: ``<NAME>_HANDLE``, ``<NAME>_AGENT_ID``,
``<NAME>_API_KEY``.  The ``account`` (org slug) is derived generically from the
handle's owner segment — ``@<org>/<agent>`` -> ``<org>`` — so ANY pair of orgs
works with no code changes (e.g. ``@acme/lead`` -> ``acme``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Logical agent names known to Parley.
AGENT_NAMES = ("COORDINATOR", "MODELER", "CHECKER", "VAULT")


@dataclass
class AgentCreds:
    """Credentials + identity for a single Band agent."""

    handle: str
    agent_id: str
    api_key: str
    account: str  # org slug derived from the handle's owner segment


def _derive_account(handle: str) -> str:
    """Derive the org slug from a Band handle, generically.

    A handle is ``@<owner>/<agent-slug>`` (the leading ``@`` is optional). The
    account is the owner segment, lowercased — e.g. ``@northwind-analytics/coordinator``
    -> ``northwind-analytics``, ``@acme/lead`` -> ``acme``. No org names are
    hardcoded, so any deployment works.
    """
    owner = handle.lstrip("@").split("/", 1)[0].strip().lower()
    if not owner:
        raise ValueError(f"Cannot derive account from handle {handle!r}: empty owner segment")
    return owner


def load_creds(name: str) -> AgentCreds:
    """Load credentials for a logical agent name from the environment.

    Args:
        name: One of COORDINATOR, MODELER, CHECKER, VAULT (case-insensitive).

    Returns:
        Populated :class:`AgentCreds`.

    Raises:
        ValueError: if ``name`` is unknown or any required field is missing/blank.
    """
    load_dotenv()

    key = name.strip().upper()
    if key not in AGENT_NAMES:
        raise ValueError(
            f"Unknown agent name {name!r}; expected one of {', '.join(AGENT_NAMES)}"
        )

    handle = (os.getenv(f"{key}_HANDLE") or "").strip()
    agent_id = (os.getenv(f"{key}_AGENT_ID") or "").strip()
    api_key = (os.getenv(f"{key}_API_KEY") or "").strip()

    missing = [
        env_name
        for env_name, value in (
            (f"{key}_HANDLE", handle),
            (f"{key}_AGENT_ID", agent_id),
            (f"{key}_API_KEY", api_key),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            f"Missing/blank credential env var(s) for {key}: {', '.join(missing)}"
        )

    account = _derive_account(handle)
    return AgentCreds(
        handle=handle,
        agent_id=agent_id,
        api_key=api_key,
        account=account,
    )
