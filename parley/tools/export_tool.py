"""Band custom tools for the export + validation beats (pure; no band import).

- ``make_export_tool``: the vault's RunExport tool. Runs ``in_place_aggregate``
  over Lumen's private dataset and returns ONLY k-suppressed cohort counts
  (rows_exported=0). The vault calls this AFTER a Lumen human approves.
- ``make_validate_tool``: the checker's ValidateExport tool. Parses an aggregate
  payload and runs ``validate_aggregates`` (k-floor, schema, PII) -> verdict.

Both return the ``(InputModel, handler)`` tuple a ClaudeSDKAdapter expects in
``additional_tools``. They compute + return a result; the agent's LLM posts the
result into the room via band_send_message.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field

from parley.scenario import SCENARIO
from parley.security.guard import assert_aggregates_only, is_authorized_approver
from parley.tools.export_gate import in_place_aggregate
from parley.tools.validator import DEFAULT_K_FLOOR, validate_aggregates


class RunExportInput(BaseModel):
    """Run the approved in-place aggregate export. Call ONLY after a first-party Lumen human has issued APPROVE <deal_id>. Returns k-suppressed cohort counts; never raw rows. Fill approver fields from the message that issued APPROVE."""

    deal_id: str = Field(..., description="The deal id that was human-approved, e.g. deal-1")
    approver_is_human: bool = Field(False, description="True ONLY if a human (not an agent) issued the APPROVE")
    approver_org: str = Field("", description="The org of the approver, e.g. 'lumen'. Export runs only if this is the data-owner org.")


class RunCapabilityInput(BaseModel):
    """Run one of the owner's approved capabilities over its own data/tools (e.g. cohort_aggregate, train_in_place). Gated capabilities run ONLY after a first-party owner human has issued APPROVE <deal_id>. Never returns raw rows."""

    capability: str = Field(..., description="The capability name to run, e.g. 'cohort_aggregate' or 'train_in_place'")
    deal_id: str = Field(..., description="The human-approved deal id, e.g. deal-1")
    approver_is_human: bool = Field(False, description="True ONLY if a human (not an agent) issued the APPROVE")
    approver_org: str = Field("", description="The org of the approver, e.g. 'lumen'. A gated capability runs only if this is the data-owner org.")


class ValidateExportInput(BaseModel):
    """Validate an aggregate payload from the vault: k-anonymity (k>=25), schema, and no PII. Pass the aggregate JSON exactly as received."""

    payload_json: str = Field(..., description="The aggregate payload as a JSON string: {columns:[...], rows:[{bucket,count}], rows_exported:0}")
    deal_id: str = Field("", description="The deal id, e.g. deal-1")


def make_export_tool(dataset: Any, query: Any, *, k_floor: int | None = None, owner_org: str | None = None):
    """Build the vault's RunExport custom tool over a fixed in-place dataset.

    k_floor and owner_org default to the deployment's scenario.yaml policy.
    """
    k_floor = SCENARIO.k_floor if k_floor is None else k_floor
    owner_org = SCENARIO.owner_org if owner_org is None else owner_org

    async def _handler(args: RunExportInput) -> dict:
        # FAIL-CLOSED authorization: export runs only if a first-party human of
        # the data-owner org approved. A hijacked LLM that omits/falsifies the
        # approver still cannot get raw data out — in_place_aggregate returns
        # aggregates only by construction — but this blocks the export entirely.
        if not is_authorized_approver(
            sender_is_human=args.approver_is_human,
            sender_org=args.approver_org,
            owner_org=owner_org,
        ):
            return {
                "status": "BLOCKED",
                "deal_id": args.deal_id,
                "reason": "Export requires APPROVE from a first-party Lumen human (the data owner). "
                "An agent, or a human from the requesting org, cannot authorize it.",
            }
        result = in_place_aggregate(query, dataset, k_floor=k_floor)
        leak = assert_aggregates_only({"aggregates": result, "rows_exported": result["rows_exported"]})
        if leak:  # defense-in-depth; should never fire
            return {"status": "BLOCKED", "deal_id": args.deal_id, "reason": f"safety check failed: {leak}"}
        return {
            "status": "ok",
            "deal_id": args.deal_id,
            "k_floor": k_floor,
            "rows_exported": result["rows_exported"],  # always 0
            "aggregates": result,
            "note": "In-place aggregation complete. Only k-suppressed cohort counts returned; raw rows never left Lumen.",
        }

    return (RunExportInput, _handler)


def make_capability_tool(registry: Any, *, owner_org: str | None = None):
    """Build the owner's RunCapability tool over a capability registry.

    Generalizes RunExport to ANY registered capability (any data + tools): the
    same fail-closed human gate + aggregates-only safety check apply to every one.
    """
    owner_org = SCENARIO.owner_org if owner_org is None else owner_org

    async def _handler(args: RunCapabilityInput) -> dict:
        cap = registry.get(args.capability)
        if cap is None:
            return {"status": "BLOCKED", "reason": f"unknown capability '{args.capability}'. Available: {registry.names()}"}
        # Gated capabilities require a first-party owner human.
        if cap.requires_human_gate and not is_authorized_approver(
            sender_is_human=args.approver_is_human, sender_org=args.approver_org, owner_org=owner_org
        ):
            return {"status": "BLOCKED", "deal_id": args.deal_id,
                    "reason": f"'{cap.name}' requires APPROVE from a first-party {owner_org} human."}
        result = cap.run({"deal_id": args.deal_id})
        # Defense-in-depth: nothing raw ever leaves, whatever the capability did.
        leak = assert_aggregates_only(result)
        if leak or cap.releases_raw:
            return {"status": "BLOCKED", "deal_id": args.deal_id, "reason": f"safety check failed: {leak or 'capability releases raw data'}"}
        return {"status": "ok", "deal_id": args.deal_id, "capability": cap.name,
                "rows_exported": result.get("rows_exported", 0), "result": result.get("result", result)}

    return (RunCapabilityInput, _handler)


def make_validate_tool(expected_schema: Optional[list] = None, *, k_floor: int | None = None):
    """Build the checker's ValidateExport custom tool."""
    k_floor = SCENARIO.k_floor if k_floor is None else k_floor
    schema = expected_schema or ["bucket", "count"]

    async def _handler(args: ValidateExportInput) -> dict:
        try:
            payload = json.loads(args.payload_json)
        except (ValueError, TypeError) as exc:
            return {"status": "INVALID", "reason": f"could not parse payload_json: {exc}"}
        # Allow either the full export envelope or the inner aggregates object.
        if "aggregates" in payload and isinstance(payload["aggregates"], dict):
            payload = payload["aggregates"]
        verdict = validate_aggregates(payload, schema, k_floor=k_floor)
        return {
            "status": "ok",
            "deal_id": args.deal_id,
            "verdict": verdict["verdict"],
            "findings": verdict["findings"],
        }

    return (ValidateExportInput, _handler)
