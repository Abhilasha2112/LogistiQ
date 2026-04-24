import asyncio
import json
from typing import Any, Dict

try:
	from .base_agent import call_llm, get_redis_client, load_mock_response
except ImportError:
	from base_agent import call_llm, get_redis_client, load_mock_response

RAW_DATA_CHANNEL = "logistiq:raw_data"
ALERTS_CHANNEL = "logistiq:alerts"

SCOUT_SYSTEM_PROMPT = """You are the Scout Agent for LogistiQ, an autonomous supply chain
intelligence system. You receive raw sensor data and must classify
anomalies precisely.

Analyse the input JSON and respond ONLY with a JSON object containing:
- event_id: string (copy from input)
- anomalies: array of objects, each with:
- anomaly_type: one of GPS_DEVIATION, RFID_MISMATCH, IOT_ANOMALY
- severity: integer 1-5 (5 = critical)
- confidence: float 0-1
- affected_asset: string identifier
- key_facts: array of strings, plain English observations
- recommended_agents: array from [ROUTER, AUDIT, SENTINEL]
- overall_assessment: one sentence plain English summary

Return ONLY valid JSON. No explanation, no markdown."""


def _parse_message(data: str) -> Dict[str, Any] | None:
	try:
		parsed = json.loads(data)
		if isinstance(parsed, dict):
			return parsed
	except json.JSONDecodeError:
		return None
	return None


async def run() -> None:
	redis_client = get_redis_client()
	pubsub = redis_client.pubsub()
	await pubsub.subscribe(RAW_DATA_CHANNEL)

	try:
		while True:
			message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
			if not message:
				await asyncio.sleep(0.05)
				continue

			raw_payload = message.get("data")
			if not isinstance(raw_payload, str):
				continue

			incoming_data = _parse_message(raw_payload)
			if incoming_data is None:
				continue

			try:
				alert_data = await call_llm(SCOUT_SYSTEM_PROMPT, incoming_data)
			except Exception:
				alert_data = load_mock_response("scout")
			await redis_client.publish(ALERTS_CHANNEL, json.dumps(alert_data, ensure_ascii=True))
	finally:
		await pubsub.unsubscribe(RAW_DATA_CHANNEL)
		await pubsub.close()


if __name__ == "__main__":
	asyncio.run(run())
