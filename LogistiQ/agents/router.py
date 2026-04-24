import asyncio
import json
from typing import Any, Dict, Iterable

try:
	from .base_agent import call_llm, get_redis_client, load_mock_response
except ImportError:
	from base_agent import call_llm, get_redis_client, load_mock_response

ALERTS_CHANNEL = "logistiq:alerts"
ROUTER_OUTPUT_CHANNEL = "logistiq:router_output"

ROUTER_SYSTEM_PROMPT = """You are the Router Agent for LogistiQ. You handle vehicle deviation alerts.

Given a GPS_DEVIATION alert, respond ONLY with JSON containing:
- event_id: string
- proposed_action: string (REROUTE_NORTH / REROUTE_SOUTH / HOLD / RETURN_TO_BASE)
- route_description: plain English reroute instruction
- eta_delta_minutes: integer (positive = delay, negative = faster)
- driver_hours_remaining: integer minutes (assume 47 minutes remaining)
- driver_hours_after_reroute: integer minutes
- driver_hours_violated: boolean
- priority_score: integer 1-10
- downstream_inventory_impact: string description

Return ONLY valid JSON. No explanation, no markdown."""


def _parse_alert(data: str) -> Dict[str, Any] | None:
	try:
		parsed = json.loads(data)
		if isinstance(parsed, dict):
			return parsed
	except json.JSONDecodeError:
		return None
	return None


def _iter_qualifying_anomalies(alert: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
	anomalies = alert.get("anomalies", [])
	if not isinstance(anomalies, list):
		return []

	qualifying: list[Dict[str, Any]] = []
	for anomaly in anomalies:
		if not isinstance(anomaly, dict):
			continue
		anomaly_type = anomaly.get("anomaly_type")
		severity = anomaly.get("severity", 0)
		if anomaly_type == "GPS_DEVIATION" and isinstance(severity, int) and severity >= 3:
			qualifying.append(anomaly)
	return qualifying


async def run() -> None:
	redis_client = get_redis_client()
	pubsub = redis_client.pubsub()
	await pubsub.subscribe(ALERTS_CHANNEL)

	try:
		while True:
			message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
			if not message:
				await asyncio.sleep(0.05)
				continue

			raw_payload = message.get("data")
			if not isinstance(raw_payload, str):
				continue

			alert = _parse_alert(raw_payload)
			if alert is None:
				continue

			event_id = alert.get("event_id", "unknown_event")
			for anomaly in _iter_qualifying_anomalies(alert):
				llm_input = {
					"event_id": event_id,
					"anomaly": anomaly,
					"overall_assessment": alert.get("overall_assessment", ""),
				}
				try:
					routed_plan = await call_llm(ROUTER_SYSTEM_PROMPT, llm_input)
				except Exception:
					routed_plan = load_mock_response("router")
				await redis_client.publish(
					ROUTER_OUTPUT_CHANNEL,
					json.dumps(routed_plan, ensure_ascii=True),
				)
	finally:
		await pubsub.unsubscribe(ALERTS_CHANNEL)
		await pubsub.close()


if __name__ == "__main__":
	asyncio.run(run())
