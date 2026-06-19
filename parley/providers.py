"""Multi-vendor model selection — make ANY Parley agent run on the vendor you choose.

Parley's thesis is heterogeneous, cross-org agents. This module decides, per agent
ROLE, which LLM it runs on — from the environment — so the recruited stranger (and,
if you want, the requester's whole band) can be Claude, Groq (Llama), OpenRouter,
OpenAI, or any custom OpenAI-compatible ``/v1`` endpoint. Every non-Claude vendor is
reached through ONE OpenAI-compatible path (``OpenAIChatModel(base_url=...)`` behind
Band's ``PydanticAIAdapter``); the default is the Claude subscription (no key), with
a safe fallback when a vendor is requested but its key/base_url is missing.

Per role R (e.g. VAULT, COORDINATOR, MODELER, CHECKER), env precedence is
``{R}_LLM_*`` then the global ``PARLEY_LLM_*``:
  {R}_LLM_VENDOR  | PARLEY_LLM_VENDOR     claude | groq | openrouter | openai | custom
  {R}_LLM_MODEL   | PARLEY_LLM_MODEL      model override
  {R}_LLM_BASE_URL| PARLEY_LLM_BASE_URL   endpoint (required for 'custom')
  <vendor key>    | {R}_LLM_API_KEY | PARLEY_LLM_API_KEY   e.g. GROQ_API_KEY

Pure module: stdlib only, no band import. The dict never contains the key value.
"""

from __future__ import annotations

import os
from typing import Optional

# vendor -> how to reach it. base_url=None means the Claude subscription (no key).
_VENDORS = {
    "claude": {"base_url": None, "key_env": None, "default_model": "claude-opus-4-8"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY",
             "default_model": "llama-3.3-70b-versatile"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY",
                   "default_model": "meta-llama/llama-3.3-70b-instruct"},
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY",
               "default_model": "gpt-4o-mini"},
    "custom": {"base_url": None, "key_env": None, "default_model": None},
}

CROSS_VENDOR = tuple(v for v in _VENDORS if v != "claude")


def _first(env: dict, names) -> Optional[str]:
    for n in names:
        if n and env.get(n):
            return env[n]
    return None


def select_provider(role: str, env: Optional[dict] = None) -> dict:
    """Decide ``role``'s vendor from env (pure). See module docstring for env keys."""
    env = env if env is not None else os.environ
    R = role.strip().upper()
    vendor = (_first(env, [f"{R}_LLM_VENDOR", "PARLEY_LLM_VENDOR"]) or "claude").strip().lower()
    spec = _VENDORS.get(vendor, _VENDORS["claude"])

    base_url = _first(env, [f"{R}_LLM_BASE_URL", "PARLEY_LLM_BASE_URL"]) or spec["base_url"]
    model = _first(env, [f"{R}_LLM_MODEL", "PARLEY_LLM_MODEL"]) or spec["default_model"]
    # where to look for the key: the vendor's own env, then the role/global overrides
    key_lookup = [e for e in (spec["key_env"], f"{R}_LLM_API_KEY", "PARLEY_LLM_API_KEY") if e]
    key_present = _first(env, key_lookup) is not None

    is_cross = vendor in CROSS_VENDOR
    use_fallback = is_cross and (not key_present or not base_url or not model)

    return {
        "role": role,
        "requested_vendor": vendor,
        "effective_vendor": "claude" if (use_fallback or vendor not in _VENDORS) else vendor,
        "adapter": "ClaudeSDKAdapter" if (use_fallback or not is_cross) else "PydanticAIAdapter",
        "model": _VENDORS["claude"]["default_model"] if use_fallback else model,
        "base_url": None if (use_fallback or not is_cross) else base_url,
        "key_env": spec["key_env"],
        "key_lookup": key_lookup,
        "key_present": key_present,
        "fallback_to_claude": use_fallback,
        "is_cross_vendor": is_cross and not use_fallback,
    }


def select_vault_provider(env: Optional[dict] = None) -> dict:
    """The recruited stranger's vendor (role=VAULT). Thin wrapper over select_provider."""
    return select_provider("vault", env)


def resolve_api_key(spec: dict, env: Optional[dict] = None) -> Optional[str]:
    """Read the actual key for a chosen spec (kept out of the spec dict itself)."""
    env = env if env is not None else os.environ
    return _first(env, spec.get("key_lookup", []))


def describe_provider(spec: dict) -> str:
    who = spec.get("role", "agent")
    if spec["fallback_to_claude"]:
        return (f"{who} -> Claude (FALLBACK: '{spec['requested_vendor']}' requested but "
                f"key/base_url/model incomplete)")
    if spec["is_cross_vendor"]:
        return f"{who} -> {spec['effective_vendor']} ({spec['model']} @ {spec['base_url']}) — CROSS-VENDOR"
    return f"{who} -> Claude ({spec['model']})"
