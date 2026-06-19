"""Minimal stdlib REST client for the Band Agent API.

This is a thin, dependency-free wrapper around the Band Agent REST surface
(``https://app.band.ai/api/v1/agent/...``) built on :mod:`urllib`.  It exists
for out-of-band bootstrap / orchestration tasks the live :class:`band.Agent`
runtime does not expose directly — e.g. an org-A coordinator discovering peers
and adding an org-B stranger to a room *before* the WebSocket session loop is
running.

Authentication is via the ``X-API-Key`` header (Agent API keys).  A custom
``User-Agent`` is sent because Cloudflare returns error **1010** ("The owner of
this website has banned your access based on your browser's signature") to the
default Python ``urllib`` User-Agent; a browser-ish UA avoids that block.

This module is intentionally band-import-free: it only uses the stdlib, so it
can be imported and unit-tested offline.  The *agents* use the real
:class:`band.runtime.tools.AgentTools` for in-room actions; this client is for
the REST-only bootstrap path and for scripts.

Endpoints (Band Agent REST API):
    add_contact              -> POST   /agent/contacts/add
    respond_contact_request  -> POST   /agent/contacts/requests/respond
    lookup_peers             -> GET    /agent/peers
    add_participant          -> POST   /agent/chats/{chat_id}/participants
    get_participants         -> GET    /agent/chats/{chat_id}/participants
    send_message             -> POST   /agent/chats/{chat_id}/messages
    send_event               -> POST   /agent/chats/{chat_id}/events
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

# Default platform base.  Trailing slash is normalized in __init__.
DEFAULT_BASE_URL = "https://app.band.ai/"

# Cloudflare returns error 1010 to the stock Python-urllib User-Agent.  A
# browser-shaped UA passes the bot check.  Keep it static + recognizable so it
# is easy to allowlist server-side if needed.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Parley/0.1 (+band-agent)"
)

# Agent endpoints live under this prefix; the Human API uses /api/v1/me.
_API_PREFIX = "api/v1/agent"
_HUMAN_PREFIX = "api/v1/me"


class BandClientError(RuntimeError):
    """Raised on a non-2xx response from the Band REST API.

    Carries the HTTP ``status`` code and the raw response ``body`` so callers
    can branch on (for example) 409 "already resolved" when responding to a
    contact request.
    """

    def __init__(self, status: int, body: str, url: str) -> None:
        super().__init__(f"Band REST {status} for {url}: {body[:500]}")
        self.status = status
        self.body = body
        self.url = url


class BandRestClient:
    """Synchronous stdlib REST client for the Band Agent API.

    Args:
        api_key: Agent API key (sent as ``X-API-Key``).
        base_url: Platform base URL; defaults to ``https://app.band.ai/``.
        user_agent: Override the Cloudflare-friendly default User-Agent.
        timeout: Per-request socket timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 30.0,
        human: bool = False,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        # Normalize to a single trailing slash so urljoin-style concat is safe.
        self.base_url = base_url.rstrip("/") + "/"
        self.user_agent = user_agent
        self.timeout = timeout
        # human=True targets the Human API (/api/v1/me), which can read a room's
        # FULL message history (incl. human messages) — agent keys only see their
        # own @mentions.
        self.prefix = _HUMAN_PREFIX if human else _API_PREFIX

    # -- low-level request -------------------------------------------------

    def _url(self, path: str, query: Optional[dict[str, Any]] = None) -> str:
        """Build an absolute URL for an API *path* (relative to the API prefix)."""
        clean = path.lstrip("/")
        url = f"{self.base_url}{self.prefix}/{clean}"
        if query:
            # Drop None values so optional params don't show up as "None".
            items = {k: v for k, v in query.items() if v is not None}
            if items:
                url = f"{url}?{urllib.parse.urlencode(items)}"
        return url

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Optional[dict[str, Any]] = None,
        query: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Perform an HTTP request and return the parsed JSON (or ``None``)."""
        url = self._url(path, query)
        data: Optional[bytes] = None
        headers = {
            "X-API-Key": self.api_key,
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:  # non-2xx
            err_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise BandClientError(exc.code, err_body, url) from exc
        except urllib.error.URLError as exc:  # DNS / connection / TLS
            raise BandClientError(0, str(exc.reason), url) from exc

    # -- identity ----------------------------------------------------------

    def me(self) -> Any:
        """Return this agent's identity. ``GET /agent/me`` (validates the connection)."""
        return self._request("GET", "me")

    # -- contacts ----------------------------------------------------------

    def add_contact(self, handle: str, message: Optional[str] = None) -> Any:
        """Send a contact request. ``POST /agent/contacts/add``.

        Args:
            handle: Handle to add (with or without ``@`` prefix).
            message: Optional note (<=500 chars) included with the request.
        """
        payload: dict[str, Any] = {"handle": handle}
        if message is not None:
            payload["message"] = message
        return self._request("POST", "contacts/add", body=payload)

    def respond_contact_request(
        self,
        action: str,
        *,
        handle: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Any:
        """Approve / reject / cancel a contact request.

        ``POST /agent/contacts/requests/respond``.

        Args:
            action: One of ``approve`` | ``reject`` | ``cancel``.
            handle: Other party's handle (approve/reject = requester,
                cancel = recipient). Provide this *or* ``request_id``.
            request_id: The contact request UUID (alternative to ``handle``).
        """
        if action not in ("approve", "reject", "cancel"):
            raise ValueError(f"invalid action {action!r}")
        if not handle and not request_id:
            raise ValueError("respond_contact_request needs handle or request_id")
        payload: dict[str, Any] = {"action": action}
        if handle is not None:
            payload["handle"] = handle
        if request_id is not None:
            payload["request_id"] = request_id
        return self._request("POST", "contacts/requests/respond", body=payload)

    # -- peer discovery ----------------------------------------------------

    def lookup_peers(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        not_in_chat: Optional[str] = None,
    ) -> Any:
        """List recruitable peers. ``GET /agent/peers``.

        Args:
            page: 1-based page number.
            page_size: Items per page (server caps at ~100).
            not_in_chat: Optional room UUID to exclude peers already in it.

        Returns:
            Parsed response, typically ``{"data": [<peer>...], "meta": {...}}``.
            Each peer carries ``handle`` (without ``@``), ``id``, ``is_contact``.
        """
        return self._request(
            "GET",
            "peers",
            query={"page": page, "page_size": page_size, "not_in_chat": not_in_chat},
        )

    # -- room participants -------------------------------------------------

    def add_participant(
        self,
        chat_id: str,
        participant_id: str,
        *,
        role: str = "member",
    ) -> Any:
        """Add a user/agent to a room.

        ``POST /agent/chats/{chat_id}/participants``.

        Args:
            chat_id: Room UUID.
            participant_id: User UUID or Agent ID to add.
            role: ``owner`` | ``admin`` | ``member`` (default ``member``).
        """
        body = {"participant": {"participant_id": participant_id, "role": role}}
        return self._request(
            "POST", f"chats/{chat_id}/participants", body=body
        )

    def get_participants(self, chat_id: str) -> Any:
        """List participants in a room.

        ``GET /agent/chats/{chat_id}/participants``.
        """
        return self._request("GET", f"chats/{chat_id}/participants")

    def get_messages(self, chat_id: str, *, page: int = 1, page_size: int = 50) -> Any:
        """List messages in a room. ``GET /agent/chats/{chat_id}/messages``."""
        return self._request(
            "GET",
            f"chats/{chat_id}/messages",
            query={"page": page, "page_size": page_size},
        )

    # -- messages & events -------------------------------------------------

    def send_message(
        self,
        chat_id: str,
        content: str,
        mentions: list[dict[str, str]] | list[str],
    ) -> Any:
        """Post a text message with @mentions.

        ``POST /agent/chats/{chat_id}/messages``.

        The Band message API requires at least one mention.  Each mention is an
        object ``{"id", "handle"}``; for convenience a bare list of handle
        strings is also accepted and wrapped as ``{"handle": <h>}`` (the server
        resolves the id, though supplying both is preferred when known).

        Args:
            chat_id: Room UUID.
            content: Message text.
            mentions: List of ``{"id", "handle"}`` dicts, or a list of handle
                strings.
        """
        if not mentions:
            raise ValueError("send_message requires at least one mention")
        mention_items: list[dict[str, str]] = []
        for m in mentions:
            if isinstance(m, str):
                mention_items.append({"handle": m})
            else:
                mention_items.append(dict(m))
        body = {"message": {"content": content, "mentions": mention_items}}
        return self._request("POST", f"chats/{chat_id}/messages", body=body)

    # -- memory ------------------------------------------------------------

    def create_memory(
        self,
        content: str,
        *,
        scope: str = "organization",
        subject_id: Optional[str] = None,
        system: str = "long_term",
        type: str = "episodic",
        segment: str = "agent",
        tags: Optional[list[str]] = None,
        thought: Optional[str] = None,
    ) -> Any:
        """Store a cross-agent memory. ``POST /agent/memories``.

        Subject-scoped memories (``scope="subject"``) need a ``subject_id`` UUID;
        organization-scoped memories omit it and are visible to all org agents.
        """
        body: dict[str, Any] = {
            "content": content, "scope": scope, "system": system,
            "type": type, "segment": segment,
        }
        if subject_id:
            body["subject_id"] = subject_id
        if thought:
            body["thought"] = thought
        if tags:
            body["metadata"] = {"tags": tags}
        return self._request("POST", "memories", body=body)

    def list_memories(self, *, query: Optional[str] = None, page: int = 1, page_size: int = 50) -> Any:
        """List/search memories. ``GET /agent/memories`` (``content_query`` search)."""
        return self._request(
            "GET", "memories",
            query={"content_query": query, "page": page, "page_size": page_size},
        )

    def supersede_memory(self, memory_id: str, content: str) -> Any:
        """Replace a memory with a new version. ``POST /agent/memories/{id}/supersede``."""
        return self._request("POST", f"memories/{memory_id}/supersede", body={"content": content})

    # -- events ------------------------------------------------------------

    def send_event(
        self,
        chat_id: str,
        content: str,
        message_type: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Post a non-mention event (thought/tool_call/tool_result/error/task).

        ``POST /agent/chats/{chat_id}/events``.

        Args:
            chat_id: Room UUID.
            content: Human-readable event content.
            message_type: One of ``tool_call`` | ``tool_result`` | ``thought``
                | ``error`` | ``task``.
            metadata: Optional structured payload.
        """
        event: dict[str, Any] = {"content": content, "message_type": message_type}
        if metadata is not None:
            event["metadata"] = metadata
        return self._request("POST", f"chats/{chat_id}/events", body={"event": event})
