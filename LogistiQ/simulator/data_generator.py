import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from itertools import cycle
from pathlib import Path
from typing import Any, Dict, List

import redis.asyncio as redis

try:
	from dotenv import load_dotenv
	load_dotenv()
except Exception:
	pass


RAW_DATA_CHANNEL = "logistiq:raw_data"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _project_root() -> Path:
	return Path(__file__).resolve().parents[1]


def _load_demo_events() -> List[Dict[str, Any]]:
	mock_file = _project_root() / "mock_responses" / "crisis_scenario.json"
	if mock_file.exists():
		try:
			payload = json.loads(mock_file.read_text(encoding="utf-8"))
			demo_id = "EVT-20260424-7781"
			if isinstance(payload, dict) and ("scout" in payload or "SCOUT" in payload):
				scout_payload = payload.get("scout") if isinstance(payload.get("scout"), dict) else payload.get("SCOUT", {})
				return [
					{
						"event_id": scout_payload.get("event_id", demo_id),
						"timestamp": datetime.now(timezone.utc).isoformat(),
						"asset_id": "TRUCK-17",
						"vehicle": {
							"latitude": 36.1699,
							"longitude": -115.1398,
							"heading": 241,
							"speed_kph": 62,
							"planned_corridor": "I-15 SOUTHBOUND",
							"actual_corridor": "County Road 12",
						},
						"telemetry": {
							"rfid_match": True,
							"temperature_c": 4.2,
							"door_open": False,
							"battery_voltage": 12.6,
						},
						"note": "demo crisis scenario",
					}
				]
		except Exception:
			pass

	return [
		{
			"event_id": "EVT-DEMO-001",
			"timestamp": datetime.now(timezone.utc).isoformat(),
			"asset_id": "TRUCK-17",
			"vehicle": {
				"latitude": 36.1699,
				"longitude": -115.1398,
				"heading": 241,
				"speed_kph": 62,
				"planned_corridor": "I-15 SOUTHBOUND",
				"actual_corridor": "County Road 12",
			},
			"telemetry": {
				"rfid_match": True,
				"temperature_c": 4.2,
				"door_open": False,
				"battery_voltage": 12.6,
			},
			"note": "demo crisis scenario",
		},
		{
			"event_id": "EVT-DEMO-002",
			"timestamp": datetime.now(timezone.utc).isoformat(),
			"asset_id": "PALLET-42",
			"vehicle": {
				"latitude": 34.0522,
				"longitude": -118.2437,
				"heading": 88,
				"speed_kph": 0,
				"planned_corridor": "DISTRIBUTION BAY 4",
				"actual_corridor": "DISTRIBUTION BAY 4",
			},
			"telemetry": {
				"rfid_match": False,
				"temperature_c": 7.8,
				"door_open": True,
				"battery_voltage": 11.9,
			},
			"note": "secondary anomaly",
		},
	]


async def publish_events(count: int, interval_seconds: float) -> None:
	client = redis.from_url(REDIS_URL, decode_responses=True)
	events = _load_demo_events()
	if not events:
		return

	try:
		if count == 0:
			while True:
				for event in events:
					await client.publish(RAW_DATA_CHANNEL, json.dumps(event, ensure_ascii=True))
					await asyncio.sleep(max(interval_seconds, 0.0))
		else:
			for event in cycle(events):
				await client.publish(RAW_DATA_CHANNEL, json.dumps(event, ensure_ascii=True))
				count -= 1
				if count <= 0:
					break
				await asyncio.sleep(max(interval_seconds, 0.0))
	finally:
		await client.aclose()


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Publish demo raw telemetry for LogistiQ agents.")
	parser.add_argument("--count", type=int, default=1, help="Number of events to publish. Use 0 to stream forever.")
	parser.add_argument("--interval", type=float, default=2.0, help="Seconds between published events.")
	return parser.parse_args()


async def main() -> None:
	args = parse_args()
	await publish_events(count=args.count, interval_seconds=args.interval)


if __name__ == "__main__":
	asyncio.run(main())
