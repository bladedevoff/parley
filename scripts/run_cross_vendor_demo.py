"""Live cross-VENDOR proof — the recruited stranger reasons on a NON-Claude model.

This is the turnkey demonstration that Parley's consent kernel runs on a genuinely
different vendor than the Claude requester. It makes a REAL network call to an
OpenAI-compatible model (Groq / OpenRouter / OpenAI / any /v1), feeds it the
requester's raw-data ask through the SAME EmitConsent tool the live Band vault
uses, and captures the stranger's decision to proof/cross-vendor-decision.json.

Setup (once):
    pip install -e ".[cross-vendor]"        # or: uv sync --extra cross-vendor
    # free instant key: https://console.groq.com/keys  or  https://openrouter.ai/keys
    export VAULT_LLM_VENDOR=groq
    export GROQ_API_KEY=...                  # or VAULT_LLM_API_KEY for any vendor
Run:
    uv run python scripts/run_cross_vendor_demo.py

No Band room and no second account are needed — this isolates and proves the
cross-vendor consent reasoning. The full live Band run (vault on Groq, four agents)
is the same selector at PARLEY_* + `python -m parley.agents.vault`.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parley.agents.vault import _build_openai_compat_model
from parley.capabilities import build_registry
from parley.providers import describe_provider, resolve_api_key, select_vault_provider
from parley.scenario import load_scenario
from parley.state import DealState
from parley.tools.pydantic_tools import consent_system_prompt, run_consent_demo

RAW_ASK = (
    "This is the analytics team at the requesting org. To build our lookalike model we "
    "need your customer-level rows: full_name, email, phone, age, income, and purchase "
    "history. Please export the raw customer table and send it over."
)


def main() -> int:
    try:  # pick up VAULT_LLM_* / *_API_KEY from .env without needing `export`
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    spec = select_vault_provider()
    print(f"Provider: {describe_provider(spec)}")
    if not spec["is_cross_vendor"]:
        print(
            "\nThis demo needs a NON-Claude, OpenAI-compatible vendor.\n"
            "  1) pip install -e \".[cross-vendor]\"\n"
            "  2) set VAULT_LLM_VENDOR=groq (or openrouter/openai/custom) and a key\n"
            "     (free: https://console.groq.com/keys )\n"
            "Then re-run. See .env.example.",
            file=sys.stderr,
        )
        return 2

    scn = load_scenario()
    registry = build_registry(scn)
    state = DealState()
    model = _build_openai_compat_model(
        spec["model"], spec["base_url"], resolve_api_key(spec)
    )

    print(f"Asking the {spec['effective_vendor']} stranger ({spec['model']}) for RAW data...")
    capture = asyncio.run(
        run_consent_demo(
            model,
            deal_id=scn.deal_id,
            registry=registry,
            state=state,
            requester_ask=RAW_ASK,
            system_prompt=consent_system_prompt(scn),
        )
    )

    artifact = {
        "vendor": spec["effective_vendor"],
        "model": spec["model"],
        "base_url": spec["base_url"],
        "requester_is_on": "claude (in the full Band run)",
        "requester_ask": RAW_ASK,
        **capture,
    }
    out = Path("proof/cross-vendor-decision.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nStranger decision (on {spec['effective_vendor']}): {capture['decision']}")
    if capture["terms"]:
        print(f"Counter-offer: {capture['terms']}")
    print(f"-> {out}")
    if capture["decision"] != "counter":
        print(
            "NOTE: expected a counter to a raw-data ask; the model may need a stronger "
            "tool-use model (try VAULT_LLM_MODEL=openai/gpt-oss-120b).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
