"""
Sentinel Agent — FIX: now listens on logistiq:alerts (same as other agents)
and correctly parses Scout's anomalies[] array for IOT_ANOMALY entries.
"""
import asyncio
import json
from typing import Any, Dict, Iterable

try:
    from .base_agent import call_llm, get_redis_client, load_mock_response, publish_to_dashboard
except ImportError:
    from base_agent import call_llm, get_redis_client, load_mock_response, publish_to_dashboard

ALERTS_CHANNEL = "logistiq:alerts"
SENTINEL_OUTPUT_CHANNEL = "logistiq:sentinel_output"

SENTINEL_SYSTEM_PROMPT = """You are the Sentinel Agent for LogistiQ. You specialise in causal
reasoning for IoT equipment anomalies.

Given an IOT_ANOMALY alert with supporting data, determine the ROOT CAUSE
by following this reasoning chain:
1. Check RFID access log: any access in the 10 minutes before anomaly?
2. Check vibration sensor: abnormal readings suggest mechanical fault
3. Check nearby sensors: if multiple sensors spike = environmental issue
4. If access event found AND no mechanical fault = DOOR_LEFT_OPEN
5. If vibration anomaly = COMPRESSOR_FAULT
6. If isolated sensor only = SENSOR_FAULT

Respond ONLY with JSON containing:
- event_id: string
- symptom: string (plain English description of what was observed)
- probable_cause: one of DOOR_LEFT_OPEN, COMPRESSOR_FAULT, SENSOR_FAULT
- confidence: float 0-1
- causal_chain: array of strings, each a reasoning step
- recommended_action: plain English action
- urgency: LOW, MEDIUM, HIGH, or CRITICAL
- estimated_goods_at_risk: string

Return ONLY valid JSON. No explanation, no markdown."""


def _iter_iot_anomalies(alert: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Extract IOT_ANOMALY entries from Scout's output."""
    anomalies = alert.get("anomalies", [])
    if not isinstance(anomalies, list):
        return []
    return [a for a in anomalies if isinstance(a, dict) and a.get("anomaly_type") == "IOT_ANOMALY"]


async def run() -> None:
    redis_client = get_redis_client()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(ALERTS_CHANNEL)
    print("🌡️  Sentinel Agent listening on logistiq:alerts...")

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

            for anomaly in _iter_iot_anomalies(alert):
                await publish_to_dashboard(redis_client, "SENTINEL",
                    f"Diagnosing IoT anomaly on {anomaly.get('affected_asset', '?')}...")

                llm_input = {
                    "event_id": event_id,
                    "anomaly": anomaly,
                    "overall_assessment": alert.get("overall_assessment", ""),
                }
                try:
                    result = await call_llm(SENTINEL_SYSTEM_PROMPT, llm_input)
                except Exception:
                    result = load_mock_response("SENTINEL")

                result["event_id"] = event_id
                await redis_client.publish(SENTINEL_OUTPUT_CHANNEL, json.dumps(result, ensure_ascii=True))
                await publish_to_dashboard(redis_client, "SENTINEL",
                    f"Root cause identified: {result.get('probable_cause','?')} "
                    f"(confidence={result.get('confidence','?')}, urgency={result.get('urgency','?')})")
                print(f"[SENTINEL] Published: {result}")

    finally:
        await pubsub.unsubscribe(ALERTS_CHANNEL)
        await pubsub.close()


if __name__ == "__main__":
    asyncio.run(run())
