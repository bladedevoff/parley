#!/usr/bin/env bash
# Parley offline demo: runs the pure-module test suite (no Band SDK, no network)
# and prints a KEYSTONE line proving the consent + export-gate invariants hold.
set -euo pipefail

# Resolve repo root from this script's location so the demo works from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

echo "== Parley offline demo =="
echo "[1/3] Full offline test suite (uv run pytest -q) — no Band, no network..."
uv run pytest -q

echo "[2/3] Governed end-to-end across 3 domains (policy + DP budget + provenance + checker)..."
uv run python scripts/run_governed_demo.py

echo "[3/3] Third-party re-attestation of each sealed bundle (run-it-yourself proof)..."
for b in proof/bundle-*.json; do uv run python -m parley.verify "$b"; done

echo
echo "KEYSTONE: all bundles VERIFIED — provenance chain intact; consent = stricter_of(LLM, policy);"
echo "  first-party owner-human gate (agent APPROVE refused); rows_exported=0; post-DP k-anonymity; DP budget honored."
