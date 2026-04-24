"""
Arbiter Agent — FIX: fully async, collects all 3 specialist outputs
then fires once per event_id, publishes to logistiq:arbiter_output.
"""
import asyncio
import json
from collections import defaultdict
from typing import Any, Dict

try:
    from .base_agent import call_llm, get_redis_client, load_mock_response, publish_to_dashboard
except ImportError:
    from base_agent import call_llm, get_redis_client, load_mock_response, publish_to_dashboard

ROUTER_OUTPUT_CHANNEL   = "logistiq:router_output"
AUDIT_OUTPUT_CHANNEL    = "logistiq:audit_output"
SENTINEL_OUTPUT_CHANNEL = "logistiq:sentinel_output"
ARBITER_OUTPUT_CHANNEL  = "logistiq:arbiter_output"

ARBITER_SYSTEM_PROMPT = """You are the Arbiter Agent for LogistiQ. You receive outputs from
specialist agents and must: (1) detect conflicts, (2) apply compliance rules,
(3) produce a resolved final action set.

CONFLICT RULES (check in this order):
1. If Router has driver_hours_violated=true: BLOCK the reroute.
   Action: INITIATE_DRIVER_SWAP. This is non-negotiable.
2. If Router proposes reroute AND Audit says will_reroute_worsen_shortage=true:
   CONFLICT: ROUTE_VS_INVENTORY. Resolution: prioritise restock.
3. If any agent confidence < 0.80: set escalate_to_human=true.

Respond ONLY with JSON containing:
- event_id: string
- conflicts_detected: array of {conflict_type, agents_involved, description}
- final_actions: array of {action, asset, rationale}
- blocked_actions: array of {action, reason, rule_violated}
- escalate_to_human: boolean
- escalation_reason: string (if escalate_to_human is true, else empty string)
- confidence_overall: float 0-1
- resolution_reasoning: plain English explanation of all decisions

Return ONLY valid JSON. No explanation, no markdown."""


# Collect outputs per event_id — waits for all three specialists
_pending: Dict[str, Dict[str, Any]] = defaultdict(dict)
_TIMEOUT_SECONDS = 8  # fire even if not all three arrive within this window


async def _try_resolve(event_id: str, redis_client, redis_pub) -> None:
    """Called whenever a new specialist output arrives. Fires when all 3 ready or on timeout."""
    bucket = _pending[event_id]

    # Check if all three are in
    has_all = all(k in bucket for k in ("router", "audit", "sentinel"))

    if not has_all:
        return  # wait for more

    await _resolve_and_publish(event_id, bucket, redis_client)
    del _pending[event_id]


async def _resolve_and_publish(event_id: str, bucket: Dict[str, Any], redis_client) -> None:
    await publish_to_dashboard(redis_client, "ARBITER",
        "Conflict detection running — checking router vs audit vs sentinel outputs...")

    llm_input = {
        "event_id": event_id,
        "router_output":   bucket.get("router", {}),
        "audit_output":    bucket.get("audit", {}),
        "sentinel_output": bucket.get("sentinel", {}),
    }

    try:
        result = await call_llm(ARBITER_SYSTEM_PROMPT, llm_input)
    except Exception:
        result = load_mock_response("ARBITER")

    result["event_id"] = event_id

    conflicts = result.get("conflicts_detected", [])
    blocked   = result.get("blocked_actions", [])
    escalate  = result.get("escalate_to_human", False)

    summary = f"{len(conflicts)} conflict(s) detected, {len(blocked)} action(s) blocked"
    if escalate:
        summary += " — HUMAN ESCALATION REQUIRED"
    await publish_to_dashboard(redis_client, "ARBITER", summary)

    await redis_client.publish(ARBITER_OUTPUT_CHANNEL, json.dumps(result, ensure_ascii=True))
    print(f"[ARBITER] Published resolution for {event_id}: {summary}")


async def _timeout_flush(event_id: str, redis_client) -> None:
    """Flush whatever we have after timeout — don't block the demo."""
    await asyncio.sleep(_TIMEOUT_SECONDS)
    if event_id in _pending and _pending[event_id]:
        print(f"[ARBITER] Timeout flush for {event_id} — only received: {list(_pending[event_id].keys())}")
        await _resolve_and_publish(event_id, _pending[event_id], redis_client)
        del _pending[event_id]


async def run() -> None:
    redis_client = get_redis_client()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(ROUTER_OUTPUT_CHANNEL, AUDIT_OUTPUT_CHANNEL, SENTINEL_OUTPUT_CHANNEL)
    print("⚖️  Arbiter Agent listening on router/audit/sentinel outputs...")

    timeout_tasks: Dict[str, asyncio.Task] = {}

    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if not message:
                await asyncio.sleep(0.05)
                continue

            channel = message.get("channel", "")
            raw_payload = message.get("data")
            if not isinstance(raw_payload, str):
                continue

            try:
                payload = json.loads(raw_payload)
            except json.JSONDecodeError:
                continue

            event_id = payload.get("event_id", "unknown")

            # Route to the right bucket slot
            if channel == ROUTER_OUTPUT_CHANNEL:
                _pending[event_id]["router"] = payload
            elif channel == AUDIT_OUTPUT_CHANNEL:
                _pending[event_id]["audit"] = payload
            elif channel == SENTINEL_OUTPUT_CHANNEL:
                _pending[event_id]["sentinel"] = payload

            # Start a timeout task if this is the first message for this event_id
            if event_id not in timeout_tasks:
                timeout_tasks[event_id] = asyncio.create_task(
                    _timeout_flush(event_id, redis_client)
                )

            # Try to resolve immediately if all three are ready
            await _try_resolve(event_id, redis_client, None)

            # Cancel the timeout task if we already resolved
            if event_id not in _pending and event_id in timeout_tasks:
                timeout_tasks[event_id].cancel()
                del timeout_tasks[event_id]

    finally:
        await pubsub.unsubscribe(ROUTER_OUTPUT_CHANNEL, AUDIT_OUTPUT_CHANNEL, SENTINEL_OUTPUT_CHANNEL)
        await pubsub.close()


if __name__ == "__main__":
    asyncio.run(run())
