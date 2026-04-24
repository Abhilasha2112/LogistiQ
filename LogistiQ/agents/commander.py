"""
Commander Agent — FIX: listens on logistiq:arbiter_output (not specialist outputs directly),
publishes to logistiq:commander_output AND logistiq:dashboard.
"""
import asyncio
import json
from typing import Any, Dict

try:
    from .base_agent import call_llm, get_redis_client, load_mock_response, publish_to_dashboard
except ImportError:
    from base_agent import call_llm, get_redis_client, load_mock_response, publish_to_dashboard

ARBITER_OUTPUT_CHANNEL   = "logistiq:arbiter_output"
COMMANDER_OUTPUT_CHANNEL = "logistiq:commander_output"

COMMANDER_SYSTEM_PROMPT = """You are the Commander Agent for LogistiQ. You receive the Arbiter's
resolved action set and produce the final human-readable executive output.

Respond ONLY with JSON containing:
- event_id: string
- executive_summary: 2-3 sentences, plain English, no jargon
- incidents_resolved: integer
- actions_taken: array of plain English strings
- actions_blocked: array of plain English strings with reason
- requires_human_attention: boolean
- human_attention_reason: string (if above is true, else empty string)
- confidence_overall: float 0-1
- estimated_cost_impact: string (e.g. "Prevented estimated ₹6,02,000 in spoilage and fines")
- incident_report: {title, timestamp, duration_seconds, root_causes, resolution}

Return ONLY valid JSON. No explanation, no markdown."""


async def run() -> None:
    redis_client = get_redis_client()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(ARBITER_OUTPUT_CHANNEL)
    print("🎖️  Commander Agent listening on logistiq:arbiter_output...")

    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if not message:
                await asyncio.sleep(0.05)
                continue

            raw_payload = message.get("data")
            if not isinstance(raw_payload, str):
                continue

            try:
                arbiter_output = json.loads(raw_payload)
            except json.JSONDecodeError:
                continue

            event_id = arbiter_output.get("event_id", "unknown")
            await publish_to_dashboard(redis_client, "COMMANDER",
                "Synthesising executive summary from Arbiter decision...")

            try:
                result = await call_llm(COMMANDER_SYSTEM_PROMPT, arbiter_output)
            except Exception:
                result = load_mock_response("COMMANDER")

            result["event_id"] = event_id

            # Publish the full structured output
            await redis_client.publish(COMMANDER_OUTPUT_CHANNEL, json.dumps(result, ensure_ascii=True))

            # Also broadcast the executive summary to the dashboard feed
            summary = result.get("executive_summary", "Decision complete.")
            cost    = result.get("estimated_cost_impact", "")
            human   = result.get("requires_human_attention", False)

            await publish_to_dashboard(redis_client, "COMMANDER", f"✅ {summary}")
            if cost:
                await publish_to_dashboard(redis_client, "COMMANDER", f"💰 {cost}")
            if human:
                reason = result.get("human_attention_reason", "")
                await publish_to_dashboard(redis_client, "COMMANDER",
                    f"⚠️ HUMAN ATTENTION REQUIRED: {reason}")

            # Push the full decision to the dashboard as a special event type
            await redis_client.publish("logistiq:dashboard", json.dumps({
                "agent":    "COMMANDER",
                "type":     "FINAL_DECISION",
                "decision": result,
            }))

            print(f"[COMMANDER] Published final decision for {event_id}")

    finally:
        await pubsub.unsubscribe(ARBITER_OUTPUT_CHANNEL)
        await pubsub.close()


if __name__ == "__main__":
    asyncio.run(run())
