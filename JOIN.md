# Join as the second operator (a real cross-org deal)

Parley's trust story is strongest when the two organizations are **two different
people**, not two accounts of one. This is the 5-minute onboarding for **Operator B
(Lumen — the data owner / the recruited stranger)**. Operator A (Northwind) runs the
requester side.

The two operators never share a Band account or a `.env`. Each runs only their side.

---

## Operator B — Lumen (owner), on your own machine

1. **Get the code + deps**
   ```bash
   git clone <repo> && cd band-ai-2026
   uv sync                       # add --extra cross-vendor to run the vault off-Claude
   claude login                  # the vault thinks via your Claude subscription
   ```
2. **Create your own Band account** at https://app.band.ai (a *different* account from
   Operator A — that is the real second org).
3. **Register the vault agent**: Agents → New Agent → External Agent, handle
   `lumen-retail` / agent `vault`. Copy the **Agent ID** and the **API Key**
   (the key is shown once).
4. **Fill only your section** of `.env`:
   ```ini
   VAULT_AGENT_ID=band_a_...
   VAULT_API_KEY=...
   # optional — run the stranger on a non-Claude vendor:
   # PARLEY_LLM_VENDOR=groq
   # GROQ_API_KEY=...
   ```
5. **Run your side** and accept the contact when Operator A recruits you:
   ```bash
   PARLEY_CONTACT=hub_room uv run python scripts/run_org.py owner
   ```
6. **You are the human gate.** When the deal reaches approval, post in the room:
   ```
   APPROVE deal-1
   ```
   An agent's APPROVE is refused by design — only you (a first-party Lumen human) can
   authorize the export.

## Operator A — Northwind (buyer)

1. Fill only the Org-A section of `.env` (coordinator / modeler / checker creds).
2. Run the buyer side, then drive the deal:
   ```bash
   uv run python scripts/run_org.py buyer
   uv run python scripts/run_demo.py
   ```

---

## What you get that a single-operator demo can't show

- A **genuine adversarial boundary**: the requester is literally a different account
  the owner doesn't control. Consent-to-a-stranger, cross-org injection defense, and
  the per-counterparty privacy budget are now tested against a real counterparty.
- A **retrievable, signed transcript** of the whole negotiation (verify it with
  `uv run python -m parley.verify <bundle.json>`).

> Note: live runs talk to app.band.ai over WebSocket — turn VPNs off if you hit SSL/EOF.
