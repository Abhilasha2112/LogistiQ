"""
LogistiQ — Data Simulator (Person 4 / Laptop 1)
================================================
Generates fake GPS, RFID, and IoT events and publishes them to Redis.

Usage:
    python data_generator.py             # continuous normal mode
    python data_generator.py --crisis    # trigger one crisis batch then continue normal
    python data_generator.py --once      # emit one normal event and exit (for testing)

Redis channel: logistiq:raw_data
"""

import argparse
import json
import math
import random
import time
import uuid
from datetime import datetime, timezone

# ── Try to import Redis; fall back to a print-only stub so the file
#    can be tested without Redis installed. ─────────────────────────
try:
    import redis

    _redis_available = True
except ImportError:
    _redis_available = False
    print("[WARN] redis-py not installed. Run: pip install redis")
    print("[WARN] Running in PRINT-ONLY mode.\n")


# ══════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════

REDIS_HOST = "localhost"
REDIS_PORT = 6379
CHANNEL = "logistiq:raw_data"
EMIT_INTERVAL_SECONDS = 3  # how often a normal event is published

# Bangalore-area bounding box used for all fake coordinates
BASE_LAT = 12.97
BASE_LNG = 77.59

# Fleet & warehouse definitions
TRUCK_IDS = [f"TRUCK_{str(i).zfill(2)}" for i in range(1, 13)]  # TRUCK_01 … TRUCK_12
WAREHOUSES = {
    "WH_A": {"expected": 912, "normal_gap": 0},
    "WH_B": {"expected": 912, "normal_gap": 0},
    "WH_C": {"expected": 650, "normal_gap": 0},
}
COLD_UNITS = ["COLD_01", "COLD_02", "COLD_03", "COLD_04"]

# SLA temperature ceiling for pharmaceutical cold chain
COLD_SLA_TEMP = 8.0  # °C


# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def event_id() -> str:
    return "evt_" + str(uuid.uuid4())[:8]


def jitter(base: float, spread: float) -> float:
    return round(base + random.uniform(-spread, spread), 6)


def normal_temp() -> float:
    """Normal cold storage temperature: 4–7 °C."""
    return round(random.uniform(4.0, 7.0), 1)


def normal_gps(truck_id: str) -> dict:
    """On-route coordinates — tight jitter around the base coordinate."""
    seed = int(truck_id.split("_")[1])
    lat = round(BASE_LAT + (seed * 0.003) + random.uniform(-0.005, 0.005), 6)
    lng = round(BASE_LNG + (seed * 0.002) + random.uniform(-0.005, 0.005), 6)
    return {
        "truck_id": truck_id,
        "lat": lat,
        "lng": lng,
        "heading_degrees": random.randint(0, 359),
        "speed_kmh": random.randint(30, 80),
        "on_route": True,
        "deviation_km": round(random.uniform(0.0, 0.4), 2),
        "route_corridor_km": 2.0,
    }


def normal_rfid(warehouse_id: str) -> dict:
    wh = WAREHOUSES[warehouse_id]
    expected = wh["expected"]
    # Small normal variance: ±2 units (scanning lag, not a real problem)
    scanned = expected + random.randint(-2, 2)
    return {
        "warehouse": warehouse_id,
        "scanned": scanned,
        "expected": expected,
        "gap": expected - scanned,
        "status": "OK",
        "last_scan_ts": now_iso(),
    }


def normal_iot(unit_id: str) -> dict:
    temp = normal_temp()
    return {
        "unit": unit_id,
        "temp_c": temp,
        "status": "OK" if temp < COLD_SLA_TEMP else "BREACH",
        "humidity_pct": round(random.uniform(60, 75), 1),
        "door_open": False,
        "vibration_g": round(random.uniform(0.01, 0.05), 3),
        "last_access_rfid": None,
        "last_access_ts": None,
    }


# ══════════════════════════════════════════════════════════════════════
# NORMAL EVENT
# ══════════════════════════════════════════════════════════════════════


def build_normal_event() -> dict:
    truck_id = random.choice(TRUCK_IDS)
    warehouse_id = random.choice(list(WAREHOUSES.keys()))
    cold_unit = random.choice(COLD_UNITS)

    return {
        "event_id": event_id(),
        "timestamp": now_iso(),
        "type": "NORMAL",
        "gps": normal_gps(truck_id),
        "rfid": normal_rfid(warehouse_id),
        "iot": normal_iot(cold_unit),
    }


# ══════════════════════════════════════════════════════════════════════
# CRISIS EVENT  (the demo centrepiece)
# ══════════════════════════════════════════════════════════════════════
#
# All three anomalies fire together, exactly as described in section 5.1:
#   • TRUCK_07 — GPS deviation 4.2 km outside corridor
#   • WH_B     — RFID scan 847 vs expected 912 (65-unit gap)
#   • COLD_03  — Temperature 12.4 °C, door access recorded 3 min prior


def build_crisis_gps() -> dict:
    """TRUCK_07 is 4.2 km outside its route corridor."""
    return {
        "truck_id": "TRUCK_07",
        "lat": 13.01,
        "lng": 77.62,
        "heading_degrees": 42,
        "speed_kmh": 54,
        "on_route": False,
        "deviation_km": 4.2,
        "route_corridor_km": 2.0,
        "expected_lat": BASE_LAT + (7 * 0.003),
        "expected_lng": BASE_LNG + (7 * 0.002),
        "driver_hours_remaining_min": 47,  # Arbiter will check this
    }


def build_crisis_rfid() -> dict:
    """WH_B has a 65-unit inventory gap."""
    return {
        "warehouse": "WH_B",
        "scanned": 847,
        "expected": 912,
        "gap": 65,
        "gap_pct": round((65 / 912) * 100, 1),
        "status": "MISMATCH",
        "last_scan_ts": now_iso(),
        "manifest_reference": "MNF-2024-0471",
    }


def build_crisis_iot() -> dict:
    """COLD_03 temperature breach — door left open 3 minutes ago."""
    access_ts = now_iso()  # simplified: same timestamp for demo
    return {
        "unit": "COLD_03",
        "temp_c": 12.4,
        "status": "BREACH",
        "humidity_pct": 88.3,         # humidity rises when door is open
        "door_open": True,
        "vibration_g": 0.04,          # normal vibration → not compressor fault
        "last_access_rfid": "#4471",
        "last_access_ts": access_ts,
        "nearby_sensors": {
            "COLD_02": 6.1,           # other unit fine → not environmental
            "COLD_04": 6.4,
        },
        "maintenance_history": {
            "last_service_days_ago": 12,
            "known_faults": [],
        },
        "sla_temp_c": COLD_SLA_TEMP,
    }


def build_crisis_event() -> dict:
    return {
        "event_id": event_id(),
        "timestamp": now_iso(),
        "type": "CRISIS",
        "gps": build_crisis_gps(),
        "rfid": build_crisis_rfid(),
        "iot": build_crisis_iot(),
    }


# ══════════════════════════════════════════════════════════════════════
# PUBLISHER
# ══════════════════════════════════════════════════════════════════════


def publish(r, event: dict) -> None:
    payload = json.dumps(event, indent=None)
    if r is not None:
        r.publish(CHANNEL, payload)
    # Always pretty-print to console so you can watch the stream
    event_type = event.get("type", "?")
    truck = event.get("gps", {}).get("truck_id", "—")
    wh = event.get("rfid", {}).get("warehouse", "—")
    temp = event.get("iot", {}).get("temp_c", "—")
    gap = event.get("rfid", {}).get("gap", 0)
    print(
        f"[{event['timestamp']}] [{event_type:6s}] "
        f"🚛 {truck:8s} | 📦 {wh} gap={gap:+d} | 🌡 {temp}°C"
    )


# ══════════════════════════════════════════════════════════════════════
# CRISIS SCENARIO JSON  (insurance policy — section 7.1 in the guide)
# ══════════════════════════════════════════════════════════════════════


CRISIS_SCENARIO = {
    "_meta": {
        "description": "Pre-baked agent responses for DEMO_MODE=true. "
                        "Use these when live LLM calls are slow or unavailable.",
        "scenario": "TRUCK_07 deviation + WH_B RFID mismatch + COLD_03 temperature breach",
    },
    "SCOUT": {
        "event_id": "evt_demo01",
        "timestamp": "2024-01-15T14:32:07Z",
        "anomalies": [
            {
                "anomaly_type": "GPS_DEVIATION",
                "severity": 4,
                "confidence": 0.91,
                "affected_asset": "TRUCK_07",
                "key_facts": [
                    "Vehicle is 4.2 km outside the 2 km route corridor",
                    "Driver has 47 minutes of legal drive time remaining",
                    "Truck carries restocking inventory for WH_B",
                ],
                "recommended_agents": ["ROUTER"],
            },
            {
                "anomaly_type": "RFID_MISMATCH",
                "severity": 3,
                "confidence": 0.87,
                "affected_asset": "WH_B",
                "key_facts": [
                    "65-unit gap: 847 scanned vs 912 expected",
                    "Gap represents 7.1% of manifest — above 5% threshold",
                    "TRUCK_07 is the scheduled restock vehicle for WH_B",
                ],
                "recommended_agents": ["AUDIT"],
            },
            {
                "anomaly_type": "IOT_ANOMALY",
                "severity": 5,
                "confidence": 0.94,
                "affected_asset": "COLD_03",
                "key_facts": [
                    "Temperature 12.4°C breaches SLA ceiling of 8°C",
                    "RFID access event #4471 recorded 3 minutes before spike",
                    "Adjacent units COLD_02 and COLD_04 reading normal (6.1°C / 6.4°C)",
                    "Vibration within normal range — compressor functioning",
                ],
                "recommended_agents": ["SENTINEL"],
            },
        ],
        "overall_assessment": (
            "Three simultaneous anomalies detected: vehicle deviation on active restock "
            "route, significant inventory gap at destination warehouse, and cold storage "
            "breach with access-event correlation suggesting door left open."
        ),
    },
    "ROUTER": {
        "event_id": "evt_demo01",
        "proposed_action": "REROUTE_NORTH",
        "route_description": (
            "Take NH44 north toward Yelahanka, then divert via Bellary Road to reach "
            "WH_B via the northern gate. Avoids the current congestion on Outer Ring Road."
        ),
        "eta_delta_minutes": 14,
        "driver_hours_remaining": 47,
        "driver_hours_after_reroute": -2,
        "driver_hours_violated": True,
        "priority_score": 8,
        "downstream_inventory_impact": (
            "14-minute delay worsens WH_B shortage; however northern route is only viable path."
        ),
    },
    "AUDIT": {
        "event_id": "evt_demo01",
        "gap_quantity": 65,
        "gap_value_estimate": "Rs.1,82,000",
        "recount_priority": "HIGH",
        "will_reroute_worsen_shortage": True,
        "shortage_context": (
            "WH_B is operating at 92.9% of expected stock. TRUCK_07 reroute "
            "delays restock by 14+ minutes during peak dispatch window."
        ),
        "recommended_action": "Expedite TRUCK_07 restock; initiate manual recount at WH_B Gate 2.",
    },
    "SENTINEL": {
        "event_id": "evt_demo01",
        "symptom": "Temperature spike from 6.2°C to 12.4°C over 8 minutes",
        "probable_cause": "DOOR_LEFT_OPEN",
        "confidence": 0.94,
        "causal_chain": [
            "Step 1: RFID access event #4471 recorded at COLD_03 entry at 14:28 UTC.",
            "Step 2: Temperature begins rising at 14:29 UTC — 1 minute after access.",
            "Step 3: Adjacent units COLD_02 (6.1°C) and COLD_04 (6.4°C) show no change — "
            "rules out environmental or power issue.",
            "Step 4: Vibration sensor reading 0.04g — within normal range — "
            "rules out compressor fault.",
            "Step 5: Humidity rising to 88.3% consistent with open door, "
            "not mechanical failure.",
            "Conclusion: Access event opened door; door was not closed; "
            "ambient air has warmed the unit.",
        ],
        "recommended_action": (
            "Dispatch personnel to close COLD_03 door immediately. "
            "Assess pharmaceutical stock for temperature exposure duration. "
            "Log incident for compliance report."
        ),
        "urgency": "CRITICAL",
        "estimated_goods_at_risk": "Rs.4,20,000 in pharmaceutical inventory",
    },
    "ARBITER": {
        "event_id": "evt_demo01",
        "conflicts_detected": [
            {
                "conflict_type": "ROUTE_VS_INVENTORY",
                "agents_involved": ["ROUTER", "AUDIT"],
                "description": (
                    "Router proposes REROUTE_NORTH (+14 min) but Audit confirms this "
                    "worsens the 65-unit WH_B shortage during peak dispatch window."
                ),
            },
            {
                "conflict_type": "DRIVER_HOURS_VIOLATION",
                "agents_involved": ["ROUTER"],
                "description": (
                    "Proposed reroute would leave driver 2 minutes over legal hours limit. "
                    "Non-negotiable regulatory block applied."
                ),
            },
        ],
        "final_actions": [
            {
                "action": "INITIATE_DRIVER_SWAP",
                "asset": "TRUCK_07",
                "rationale": "Replace current driver before executing any reroute.",
            },
            {
                "action": "CLOSE_COLD_STORE_DOOR",
                "asset": "COLD_03",
                "rationale": "Sentinel causal diagnosis is 94% confident — door left open.",
            },
            {
                "action": "DISPATCH_RECOUNT_TEAM",
                "asset": "WH_B",
                "rationale": "65-unit gap requires physical verification before next dispatch.",
            },
        ],
        "blocked_actions": [
            {
                "action": "REROUTE_NORTH",
                "reason": "DRIVER_HOURS_VIOLATION",
                "rule_violated": "Commercial vehicle driver max 9 hours per shift",
            }
        ],
        "escalate_to_human": True,
        "escalation_reason": (
            "Driver swap requires human dispatch coordinator approval. "
            "Cold store pharmaceutical assessment requires on-site manager sign-off."
        ),
        "confidence_overall": 0.87,
        "resolution_reasoning": (
            "Two conflicts detected and resolved. REROUTE_NORTH blocked unconditionally "
            "due to driver hours — this is a legal constraint, not a judgement call. "
            "ROUTE_VS_INVENTORY conflict resolved by treating driver swap as prerequisite; "
            "restock route can be assigned to a fresh driver immediately. "
            "Cold store action is independent and proceeds with high confidence. "
            "Human escalation required for driver coordination and pharmaceutical sign-off."
        ),
    },
    "COMMANDER": {
        "event_id": "evt_demo01",
        "executive_summary": (
            "Three simultaneous supply chain incidents detected and resolved in under 10 seconds. "
            "A delivery truck was diverted and its driver replaced before a legal hours violation "
            "occurred. A cold storage door was found open — pharmaceutical stock is at risk and "
            "a manager has been alerted. A warehouse inventory gap has triggered a recount. "
            "Two actions required human approval; all others executed autonomously."
        ),
        "incidents_resolved": 3,
        "actions_taken": [
            "Driver swap initiated for TRUCK_07 — replacement driver dispatched.",
            "Cold store COLD_03 flagged for immediate door closure.",
            "Recount team dispatched to WH_B Gate 2.",
        ],
        "actions_blocked": [
            "Northern reroute blocked — would have put driver 2 minutes over legal limit.",
        ],
        "requires_human_attention": True,
        "human_attention_reason": (
            "Driver swap coordination and pharmaceutical stock assessment require "
            "manager approval within the next 5 minutes to prevent SLA breach."
        ),
        "confidence_overall": 0.87,
        "estimated_cost_impact": "Prevented estimated Rs.6,02,000 in combined spoilage, "
                                  "regulatory fines, and missed delivery penalties.",
        "incident_report": {
            "title": "Triple Simultaneous Anomaly — Route / Inventory / Cold Chain",
            "timestamp": "2024-01-15T14:32:07Z",
            "duration_seconds": 8,
            "root_causes": [
                "TRUCK_07 navigated around an unreported road closure without dispatcher notice.",
                "WH_B RFID gap caused by loading error at origin facility.",
                "COLD_03 door left open after access event #4471 — staff did not re-latch.",
            ],
            "resolution": (
                "Driver swap ordered. Cold store door closure dispatched. "
                "Recount team en route to WH_B. Human escalation raised for "
                "pharmaceutical assessment."
            ),
        },
    },
}


def write_crisis_scenario_json(path: str = "mock_responses/crisis_scenario.json") -> None:
    import os

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(CRISIS_SCENARIO, f, indent=2, ensure_ascii=False)
    print(f"[INFO] crisis_scenario.json written to {path}")


# ══════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ══════════════════════════════════════════════════════════════════════


def connect_redis():
    if not _redis_available:
        return None
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        r.ping()
        print(f"[INFO] Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
        return r
    except Exception as e:
        print(f"[WARN] Could not connect to Redis: {e}")
        print("[WARN] Running in PRINT-ONLY mode.")
        return None


def main():
    parser = argparse.ArgumentParser(description="LogistiQ Data Simulator")
    parser.add_argument("--crisis", action="store_true", help="Emit one crisis batch immediately")
    parser.add_argument("--once", action="store_true", help="Emit one normal event then exit")
    parser.add_argument("--write-json", action="store_true",
                        help="Write crisis_scenario.json and exit")
    args = parser.parse_args()

    # Always write the JSON so it is ready as the insurance policy
    write_crisis_scenario_json()

    if args.write_json:
        return

    r = connect_redis()

    if args.once:
        event = build_normal_event()
        publish(r, event)
        return

    print("\n[LogistiQ Simulator] Starting continuous emission...")
    print(f"  Interval : {EMIT_INTERVAL_SECONDS}s")
    print(f"  Channel  : {CHANNEL}")
    print(f"  Redis    : {'connected' if r else 'PRINT-ONLY'}")
    print("  Press Ctrl+C to stop.\n")

    # If --crisis flag, emit crisis first
    if args.crisis:
        print(">>> CRISIS EVENT TRIGGERED <<<")
        publish(r, build_crisis_event())
        time.sleep(1)

    counter = 0
    try:
        while True:
            counter += 1
            # Every 30 normal events (~90 seconds), emit a crisis to keep the
            # demo interesting during a long run. Comment this out if you only
            # want crises on demand via --crisis.
            if counter % 30 == 0:
                print("\n>>> AUTO-CRISIS (every 30 events) <<<")
                publish(r, build_crisis_event())
                print()
            else:
                publish(r, build_normal_event())

            time.sleep(EMIT_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\n[INFO] Simulator stopped.")


if __name__ == "__main__":
    main()
