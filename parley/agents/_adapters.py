"""Shared adapter factory — build any agent on Claude OR a cross-vendor model.

One place that turns a role + prompt (+ optional tools) into the right Band adapter:
ClaudeSDKAdapter by default, or PydanticAIAdapter on an OpenAI-compatible vendor when
``select_provider(role)`` says so. Used by every agent so the WHOLE band can be made
cross-vendor from env (e.g. PARLEY_LLM_VENDOR=groq, or per-role COORDINATOR_LLM_VENDOR).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

from band.adapters import ClaudeSDKAdapter

from parley.providers import describe_provider, resolve_api_key, select_provider

logger = logging.getLogger(__name__)


def build_openai_compat_model(model: str, base_url: str, api_key: str) -> Any:
    """A pydantic-ai model for ANY OpenAI-compatible endpoint (Groq/OpenRouter/OpenAI/...)."""
    from pydantic_ai.providers.openai import OpenAIProvider
    try:
        from pydantic_ai.models.openai import OpenAIChatModel as _Model
    except ImportError:  # older pydantic-ai
        from pydantic_ai.models.openai import OpenAIModel as _Model  # type: ignore[no-redef]
    return _Model(model, provider=OpenAIProvider(base_url=base_url, api_key=api_key))


def build_agent_adapter(
    role: str,
    *,
    custom_section: str,
    claude_model: str,
    claude_fallback: Optional[str] = None,
    tuple_tools: Optional[list] = None,          # (InputModel, handler) tuples for ClaudeSDKAdapter
    pydantic_tools: Optional[Callable[[], list]] = None,  # 0-arg factory (lazy: only on cross-vendor)
    contacts: bool = False,
) -> Any:
    """Return the role's adapter. Cross-vendor when env selects it, else Claude."""
    spec = select_provider(role, os.environ)
    logger.info("Provider [%s]: %s", role, describe_provider(spec))

    if spec["is_cross_vendor"]:
        try:
            from band.adapters import PydanticAIAdapter
            from band.core.types import AdapterFeatures, Capability, Emit

            model_obj = build_openai_compat_model(spec["model"], spec["base_url"], resolve_api_key(spec))
            ptools = pydantic_tools() if callable(pydantic_tools) else (pydantic_tools or [])
            caps = {Capability.CONTACTS} if contacts else set()
            return PydanticAIAdapter(
                model=model_obj,
                custom_section=custom_section,
                additional_tools=list(ptools),
                features=AdapterFeatures(capabilities=caps, emit={Emit.EXECUTION}),
            )
        except Exception:  # missing extra / bad key -> never break the live run
            logger.exception("[%s] cross-vendor adapter unavailable; falling back to Claude", role)

    kwargs: dict = {"model": claude_model, "custom_section": custom_section,
                    "enable_execution_reporting": True}
    if claude_fallback:
        kwargs["fallback_model"] = claude_fallback
    if tuple_tools:
        kwargs["additional_tools"] = list(tuple_tools)
    return ClaudeSDKAdapter(**kwargs)
