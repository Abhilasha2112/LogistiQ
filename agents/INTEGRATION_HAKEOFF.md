# LogistiQ Redis Integration Handoff

This document lists the JSON payload keys currently published by Sentinel, Audit, and Arbiter agents to Redis, with data types for Commander (Person 1) and Dashboard (Person 4).

## 1) Sentinel -> logistiq:sentinel_output

Published payload schema:

| Key | Type | Description |
|---|---|---|
| agent | string | Constant publisher identity. Current value: "Sentinel" |
| issue_detected | boolean | Whether Sentinel detected an issue condition |
| causal_chain | array<string> | Ordered autonomous reasoning steps used to infer cause |
| urgency | string | Severity label. Current value: "CRITICAL" |

### causal_chain structure (ordered list)

`causal_chain` is an ordered `array<string>` and currently follows this 4-step professional reasoning pattern:

1. Detected temperature spike (for example: "Detected temperature spike (9.0C).")
2. Cross-referenced RFID access context (for example: door access approximately 2 minutes earlier)
3. Verified compressor power draw status
4. Final conclusion statement (for example: "Conclusion: Compressor Malfunction.")

## 2) Audit -> logistiq:audit_output

Published payload schema (only when shrinkage is detected):

| Key | Type | Description |
|---|---|---|
| agent | string | Constant publisher identity. Current value: "AUDIT" |
| shipment_id | string \| null | Shipment identifier associated with reconciliation output |
| issue | string | Current value: "INVENTORY_SHRINKAGE" |
| missing_items | array<object> | List of items with quantity shortfall |
| shrinkage_value | integer | Total missing quantity across all expected items |
| priority | string | Current values observed: "MEDIUM" or "HIGH" |

`missing_items` object schema:

| Key | Type | Description |
|---|---|---|
| item_id | string | Missing item identifier |
| missing_quantity | integer | Quantity not found in RFID scans |

### inventory_gap and shipment_id mapping

- `shipment_id` is currently published directly.
- `inventory_gap` is **not** currently emitted as a literal key.
- Use `shrinkage_value` as the current backend equivalent of `inventory_gap`.

## 3) Arbiter -> logistiq:arbiter_output

Published payload schema:

| Key | Type | Description |
|---|---|---|
| agent | string | Constant publisher identity. Current value: "ARBITER" |
| conflicts_detected | array<string> | Conflict tags detected during arbitration |
| final_decision | string | Primary arbitration decision |
| actions | array<string> | Action list selected by Arbiter |
| blocked_actions | array<string> | Actions that were explicitly blocked |
| confidence_overall | float | Overall confidence score (for example: 0.9) |
| resolution_reasoning | string | Human-readable explanation of applied decision logic |
| incident_summary | object | Structured summary for executive/demo reporting |

`incident_summary` object schema:

| Key | Type | Description |
|---|---|---|
| threat_level | string | Threat level classification |
| action_taken | string | Action/decision executed |
| logic_applied | string | Summary of rules/reasoning applied |
| potential_loss_prevented | string | Estimated business loss avoided |

### resolution_reasoning and escalate_to_human mapping

- `resolution_reasoning` is currently published directly.
- `escalate_to_human` is **not** currently emitted as a literal key.
- Current UI workaround: derive `escalate_to_human = true` when `incident_summary.threat_level == "CRITICAL"`; otherwise `false`.

## 4) Integration Notes for Commander and Dashboard

- Treat `causal_chain` as ordered evidence, not independent labels.
- Use `shrinkage_value` as the current canonical numeric gap metric until/if `inventory_gap` is added.
- Use `resolution_reasoning` for timeline/audit narratives and `incident_summary` for executive cards.
- If strict contract keys are required by the UI (`inventory_gap`, `escalate_to_human`), add explicit aliases in backend publishers to avoid client-side derivation.
