import asyncio
import json
import os
from typing import Any, Dict

from redis.exceptions import ConnectionError as RedisConnectionError

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


def _is_demo_mode() -> bool:
	return os.getenv("DEMO_MODE", "false").lower() == "true"


def _build_demo_scout_alert(incoming_data: Dict[str, Any]) -> Dict[str, Any]:
	event_id = str(incoming_data.get("event_id", "evt_demo_runtime"))

	asset = (
		incoming_data.get("asset_id")
		or incoming_data.get("truck_id")
		or incoming_data.get("vehicle", {}).get("id")
		or incoming_data.get("gps", {}).get("truck_id")
		or "TRK-21"
	)

	deviation_km = (
		incoming_data.get("gps", {}).get("deviation_km")
		or incoming_data.get("vehicle", {}).get("deviation_km")
		or 3.5
	)

	try:
		deviation_km = float(deviation_km)
	except (TypeError, ValueError):
		deviation_km = 3.5

	severity = 5 if deviation_km >= 5 else 4 if deviation_km >= 3 else 3 if deviation_km >= 2 else 2

	return {
		"event_id": event_id,
		"anomalies": [
			{
				"anomaly_type": "GPS_DEVIATION",
				"severity": severity,
				"confidence": 0.9,
				"affected_asset": str(asset),
				"key_facts": [
					f"Vehicle deviated approximately {deviation_km:.1f} km from expected corridor",
					"Deviation sustained beyond monitoring threshold",
				],
				"recommended_agents": ["ROUTER"],
			}
		],
		"overall_assessment": "Route deviation detected and escalated to Router.",
	}


def _parse_message(data: str) -> Dict[str, Any] | None:
	try:
		parsed = json.loads(data)
		if isinstance(parsed, dict):
			return parsed
	except json.JSONDecodeError:
		return None
	return None


async def run() -> None:
	print("\n\U0001f52d Scout Agent monitoring route integrity...\n")
	redis_client = get_redis_client()
	pubsub = redis_client.pubsub()
	try:
		await pubsub.subscribe(RAW_DATA_CHANNEL)
	except RedisConnectionError as exc:
		print(f"[SCOUT] Redis connection failed on {RAW_DATA_CHANNEL}: {exc}")
		print("[SCOUT] Start Redis on localhost:6379 and retry.")
		await pubsub.aclose()
		return

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

			if _is_demo_mode():
				alert_data = _build_demo_scout_alert(incoming_data)
			else:
				try:
					alert_data = await call_llm(SCOUT_SYSTEM_PROMPT, incoming_data)
				except Exception:
					alert_data = load_mock_response("scout")

			has_route_deviation = any(
				isinstance(a, dict) and a.get("anomaly_type") == "GPS_DEVIATION"
				for a in alert_data.get("anomalies", [])
			)
			if has_route_deviation:
				print("\u2705 Scout Analysis: Route Deviation detected.")
			await redis_client.publish(ALERTS_CHANNEL, json.dumps(alert_data, ensure_ascii=True))
	finally:
		try:
			await pubsub.unsubscribe(RAW_DATA_CHANNEL)
		except Exception:
			pass
		await pubsub.aclose()


if __name__ == "__main__":
	try:
		asyncio.run(run())
	except KeyboardInterrupt:
		pass