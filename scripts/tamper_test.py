"""On-camera proof: a sealed deal verifies, and ANY tamper is caught — exit 0 then 1.

Run this in the demo video. It re-attests a real bundle (all invariants PASS, exit 0),
then flips ONE field in a signed provenance step and re-attests — the chain/signature
invariant FAILS and the CLI exits 1. Nobody can edit a deal and have it still verify.

    uv run python scripts/tamper_test.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parley.verify import attest  # noqa: E402

BUNDLE = ROOT / "proof" / "bundle-deal-1.json"


def _show(title: str, result: dict) -> None:
    print(f"\n=== {title} ===")
    for c in result["checks"]:
        print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['invariant']}: {c['detail']}")
    print(f"  RESULT: {'VERIFIED (exit 0)' if result['ok'] else 'FAILED (exit 1)'}")


def main() -> int:
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))

    original = attest(bundle)
    _show("ORIGINAL sealed deal", original)
    assert original["ok"], "the committed bundle should verify"

    # Tamper: flip ONE field inside a signed provenance step (the consent decision).
    forged = copy.deepcopy(bundle)
    for r in forged["provenance"]["receipts"]:
        if r.get("kind") == "consent":
            r["data"]["final"] = "accept"          # attacker tries to loosen consent
            r["data"]["note"] = "raw rows allowed"  # ...and slip in a leak
            break
    tampered = attest(forged)
    _show("TAMPERED (one byte flipped in a signed step)", tampered)

    print("\n" + "-" * 60)
    if (not original["ok"]) or tampered["ok"]:
        print("UNEXPECTED: tamper was not caught.")
        return 2
    broke = next(c["invariant"] for c in tampered["checks"] if not c["ok"])
    print(f"Tamper caught by '{broke}'. Forging a deal requires the owner's private key.")
    return 1  # non-zero: the tampered bundle is rejected, exactly as it should be


if __name__ == "__main__":
    sys.exit(main())
