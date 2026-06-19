"""Tests for the multi-vendor stranger selection (cross-org, cross-vendor).

Every non-Claude vendor is an OpenAI-compatible endpoint reached through one path.
"""

from __future__ import annotations

from parley.providers import (
    CROSS_VENDOR,
    describe_provider,
    resolve_api_key,
    select_provider,
    select_vault_provider,
)


def test_default_is_claude_subscription_no_key():
    spec = select_vault_provider({})
    assert spec["effective_vendor"] == "claude"
    assert spec["adapter"] == "ClaudeSDKAdapter"
    assert spec["base_url"] is None
    assert spec["is_cross_vendor"] is False
    assert spec["fallback_to_claude"] is False
    assert spec["model"] == "claude-opus-4-8"


def test_groq_selected_with_its_own_key():
    spec = select_vault_provider({"VAULT_LLM_VENDOR": "groq", "GROQ_API_KEY": "x"})
    assert spec["effective_vendor"] == "groq"
    assert spec["adapter"] == "PydanticAIAdapter"
    assert spec["base_url"] == "https://api.groq.com/openai/v1"
    assert spec["model"] == "llama-3.3-70b-versatile"
    assert spec["is_cross_vendor"] is True
    assert "CROSS-VENDOR" in describe_provider(spec)


def test_openrouter_uses_universal_key_override():
    # no OPENROUTER_API_KEY, but the universal VAULT_LLM_API_KEY is honored
    env = {"VAULT_LLM_VENDOR": "openrouter", "VAULT_LLM_API_KEY": "sk-or-..."}
    spec = select_vault_provider(env)
    assert spec["effective_vendor"] == "openrouter"
    assert spec["base_url"] == "https://openrouter.ai/api/v1"
    assert spec["is_cross_vendor"] is True
    assert resolve_api_key(spec, env) == "sk-or-..."


def test_cross_vendor_without_key_falls_back_to_claude():
    spec = select_vault_provider({"VAULT_LLM_VENDOR": "groq"})
    assert spec["requested_vendor"] == "groq"
    assert spec["effective_vendor"] == "claude"
    assert spec["adapter"] == "ClaudeSDKAdapter"
    assert spec["base_url"] is None
    assert spec["is_cross_vendor"] is False
    assert spec["fallback_to_claude"] is True
    assert "FALLBACK" in describe_provider(spec)


def test_custom_vendor_requires_base_url_and_model():
    # 'custom' with a key but no base_url/model -> fall back (misconfigured)
    spec = select_vault_provider({"VAULT_LLM_VENDOR": "custom", "VAULT_LLM_API_KEY": "x"})
    assert spec["fallback_to_claude"] is True

    # fully configured custom endpoint -> cross-vendor
    spec = select_vault_provider({
        "VAULT_LLM_VENDOR": "custom",
        "VAULT_LLM_API_KEY": "x",
        "VAULT_LLM_BASE_URL": "https://my-llm.internal/v1",
        "VAULT_LLM_MODEL": "my-model",
    })
    assert spec["is_cross_vendor"] is True
    assert spec["base_url"] == "https://my-llm.internal/v1"
    assert spec["model"] == "my-model"


def test_model_and_base_url_overrides_respected():
    spec = select_vault_provider({
        "VAULT_LLM_VENDOR": "groq",
        "GROQ_API_KEY": "x",
        "VAULT_LLM_MODEL": "openai/gpt-oss-120b",
        "VAULT_LLM_BASE_URL": "https://proxy.internal/v1",
    })
    assert spec["model"] == "openai/gpt-oss-120b"
    assert spec["base_url"] == "https://proxy.internal/v1"


def test_unknown_vendor_degrades_to_claude():
    spec = select_vault_provider({"VAULT_LLM_VENDOR": "nope"})
    assert spec["effective_vendor"] == "claude"
    assert spec["is_cross_vendor"] is False


def test_cross_vendor_set_excludes_claude():
    assert "claude" not in CROSS_VENDOR
    assert {"groq", "openrouter", "openai", "custom"} <= set(CROSS_VENDOR)


def test_spec_never_leaks_key_value():
    env = {"VAULT_LLM_VENDOR": "groq", "GROQ_API_KEY": "super-secret"}
    spec = select_vault_provider(env)
    assert "super-secret" not in str(spec)


# ── generalized per-role selection (whole band can be cross-vendor) ──────────

def test_select_provider_per_role_prefix():
    env = {"COORDINATOR_LLM_VENDOR": "openai", "OPENAI_API_KEY": "x"}
    coord = select_provider("coordinator", env)
    assert coord["effective_vendor"] == "openai" and coord["is_cross_vendor"] is True
    # a different role with no override stays on Claude
    assert select_provider("modeler", env)["effective_vendor"] == "claude"


def test_parley_global_vendor_applies_to_all_roles():
    env = {"PARLEY_LLM_VENDOR": "groq", "GROQ_API_KEY": "x"}
    for role in ("vault", "coordinator", "modeler", "checker"):
        spec = select_provider(role, env)
        assert spec["is_cross_vendor"] is True and spec["effective_vendor"] == "groq"


def test_role_override_beats_global():
    env = {"PARLEY_LLM_VENDOR": "groq", "GROQ_API_KEY": "x",
           "CHECKER_LLM_VENDOR": "openai", "OPENAI_API_KEY": "y"}
    assert select_provider("checker", env)["effective_vendor"] == "openai"
    assert select_provider("vault", env)["effective_vendor"] == "groq"


def test_select_vault_provider_is_role_vault():
    env = {"VAULT_LLM_VENDOR": "groq", "GROQ_API_KEY": "x"}
    assert select_vault_provider(env) == select_provider("vault", env)
