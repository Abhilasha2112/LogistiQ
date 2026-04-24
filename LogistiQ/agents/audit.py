"""
Audit Agent — FIX: now correctly parses Scout's anomalies[] array
and responds to RFID_MISMATCH anomalies.
"""
import asyncio
import json
from typing import Any, Dict, Iterable

try:
    from .base_agent import call_llm, get_redis_client, load_mock_response, publish_to_dashboard
except ImportError:
    from base_agent import call_llm, get_redis_client, load_mock_response, publish_to_dashboard

ALERTS_CHANNEL = "logistiq:alerts"
AUDIT_OUTPUT_CHANNEL = "logistiq:audit_output"

AUDIT_SYSTEM_PROMPT = """You are the Audit Agent for LogistiQ. You handle RFID inventory mismatch alerts.

Given an RFID_MISMATCH anomaly, respond ONLY with JSON containing:
- event_id: string (copy from input)
- gap_quantity: integer (expected - scanned)
- gap_value_estimate: string (e.g. "₹1,82,000")
- recount_priority: string (LOW / MEDIUM / HIGH / CRITICAL)
- will_reroute_worsen_shortage: boolean (true if rerouting the delivery truck delays restock)
- shortage_context: plain English explanation of the inventory situation
- recommended_action: plain English action string
- confidence: float 0-1

Return ONLY valid JSON. No explanation, no markdown."""


def _iter_rfid_anomalies(alert: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Extract RFID_MISMATCH anomalies from Scout's output."""
    anomalies = alert.get("anomalies", [])
    if not isinstance(anomalies, list):
        return []
    return [a for a in anomalies if isinstance(a, dict) and a.get("anomaly_type") == "RFID_MISMATCH"]


async def run() -> None:
    redis_client = get_redis_client()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(ALERTS_CHANNEL)
    print("📋 Audit Agent listening on logistiq:alerts...")

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
                alert = json.loads(raw_payload)
            except json.JSONDecodeError:
                continue

            event_id = alert.get("event_id", "unknown")

            for anomaly in _iter_rfid_anomalies(alert):
                await publish_to_dashboard(redis_client, "AUDIT",
                    f"Reconciling RFID mismatch for {anomaly.get('affected_asset', '?')}...")

                llm_input = {
                    "event_id": event_id,
                    "anomaly": anomaly,
                    "overall_assessment": alert.get("overall_assessment", ""),
                }
                try:
                    result = await call_llm(AUDIT_SYSTEM_PROMPT, llm_input)
                except Exception:
                    result = load_mock_response("AUDIT")

                result["event_id"] = event_id
                await redis_client.publish(AUDIT_OUTPUT_CHANNEL, json.dumps(result, ensure_ascii=True))
                await publish_to_dashboard(redis_client, "AUDIT",
                    f"Audit complete: gap={result.get('gap_quantity','?')} units, "
                    f"worsen_shortage={result.get('will_reroute_worsen_shortage','?')}")
                print(f"[AUDIT] Published: {result}")

    finally:
        await pubsub.unsubscribe(ALERTS_CHANNEL)
        await pubsub.close()


if __name__ == "__main__":
    asyncio.run(run())
