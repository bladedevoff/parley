"""Freeze REAL kernel output into the web app's public/ for the static Vercel demo.

The site is static, but the data is NOT mocked: this runs the actual offline kernel
(DealSession + attest) for each scenario and writes its genuine output as JSON, plus
a signed bundle + the owner public key so a judge can re-run `verify` themselves.

    uv run python scripts/gen_web_data.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui"))

from server import run_deal  # noqa: E402  (reuse the exact kernel-driving logic)

OUT = ROOT / "web" / "public" / "demo"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for mode in ("normal", "inject", "purpose", "budget"):
        d = run_deal(mode)
        (OUT / f"{mode}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {mode:8} {d['capability']['status']:7} verify_ok={d['verify_ok']} -> web/public/demo/{mode}.json")
    for f in ("proof/bundle-deal-1.json", "proof/owner_pubkey.hex"):
        src = ROOT / f
        if src.exists():
            shutil.copy(src, OUT / src.name)
            print(f"  copied {src.name} (verify-yourself)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
