import asyncio
import json
import os
from typing import Any, Dict, Iterable

from redis.exceptions import ConnectionError as RedisConnectionError

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


def _is_demo_mode() -> bool:
	return os.getenv("DEMO_MODE", "false").lower() == "true"


def _build_demo_router_plan(alert: Dict[str, Any], anomaly: Dict[str, Any]) -> Dict[str, Any]:
	event_id = str(alert.get("event_id", "evt_demo_runtime"))
	asset = str(anomaly.get("affected_asset", "TRK-21"))
	severity = anomaly.get("severity", 3)

	try:
		severity = int(severity)
	except (TypeError, ValueError):
		severity = 3

	eta_delta = 6 + (severity * 2)
	driver_remaining = 47
	driver_after = driver_remaining - eta_delta
	violated = driver_after < 0

	# Keep the required JSON field while surfacing the lane decision in route_description.
	return {
		"event_id": event_id,
		"proposed_action": "REROUTE_NORTH",
		"route_description": "Bypass_Lane_7",
		"eta_delta_minutes": eta_delta,
		"driver_hours_remaining": driver_remaining,
		"driver_hours_after_reroute": driver_after,
		"driver_hours_violated": violated,
		"priority_score": min(10, max(1, severity * 2)),
		"downstream_inventory_impact": f"Reroute suggested for {asset}; moderate delivery impact expected.",
	}


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
	print("\n\U0001f6e3\ufe0f Router Agent ready to recalculate...\n")
	redis_client = get_redis_client()
	pubsub = redis_client.pubsub()
	try:
		await pubsub.subscribe(ALERTS_CHANNEL)
	except RedisConnectionError as exc:
		print(f"[ROUTER] Redis connection failed on {ALERTS_CHANNEL}: {exc}")
		print("[ROUTER] Start Redis on localhost:6379 and retry.")
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

			alert = _parse_alert(raw_payload)
			if alert is None:
				continue

			event_id = alert.get("event_id", "unknown_event")
			for anomaly in _iter_qualifying_anomalies(alert):
				asset = anomaly.get("affected_asset", "TRK-21")
				print(f"\U0001f504 Recalculating for {asset}...")
				llm_input = {
					"event_id": event_id,
					"anomaly": anomaly,
					"overall_assessment": alert.get("overall_assessment", ""),
				}
				if _is_demo_mode():
					routed_plan = _build_demo_router_plan(alert, anomaly)
				else:
					try:
						routed_plan = await call_llm(ROUTER_SYSTEM_PROMPT, llm_input)
					except Exception:
						routed_plan = load_mock_response("router")

				print(f"\u2705 Proposed: {routed_plan.get('route_description', 'N/A')}")
				await redis_client.publish(
					ROUTER_OUTPUT_CHANNEL,
					json.dumps(routed_plan, ensure_ascii=True),
				)
	finally:
		try:
			await pubsub.unsubscribe(ALERTS_CHANNEL)
		except Exception:
			pass
		await pubsub.aclose()


if __name__ == "__main__":
	try:
		asyncio.run(run())
	except KeyboardInterrupt:
		pass