import json
import sys
import threading
import time
import redis

# The channel your agents are now listening to
CHANNEL = "logistiq:alerts"
r = redis.Redis(host="localhost", port=6379, decode_responses=True)

def _publish(payload):
    r.publish(CHANNEL, json.dumps(payload))

def test_conflict():
    """Simulates a route change vs inventory shortage conflict for the Arbiter"""
    gps_deviation_event = {
        "event_id": "evt_gps_001",
        "anomaly_type": "GPS_DEVIATION",
        "agent": "ROUTER",
        "truck_id": "TRK-21",
        "priority": "HIGH"
    }

    rfid_mismatch_event = {
        "event_id": "evt_rfid_001",
        "anomaly_type": "RFID_MISMATCH", # Arbiter looks for this
        "agent": "AUDIT",
        "truck_id": "TRK-21",
        "expected": 120,
        "scanned": 88
    }

    _publish(gps_deviation_event)
    time.sleep(0.1)
    _publish(rfid_mismatch_event)
    print("✅ test_conflict: Injected GPS vs RFID mismatch.")

def test_sentinel_logic():
    """Simulates IoT data to test Sentinel's Causal Reasoning"""
    
    # Scenario 1: Door Left Open (Human Error)
    door_event = {
        "event_id": "evt_iot_001",
        "anomaly_type": "IOT_ANOMALY", # Sentinel gatekeeper check
        "temperature": 10.7,
        "rfid_access": True,          # Triggers 'Human Error' logic
        "vibration": False,
        "note": "Testing: Door Left Open"
    }

    # Scenario 2: Compressor Fault (Mechanical)
    compressor_event = {
        "event_id": "evt_iot_002",
        "anomaly_type": "IOT_ANOMALY",
        "temperature": 11.2,
        "rfid_access": False,
        "vibration": True,            # Triggers 'Mechanical Fault' logic
        "note": "Testing: Compressor Fault"
    }

    _publish(door_event)
    print("✅ test_sentinel_logic: Injected 'Door Open' event.")
    time.sleep(2) # Pause so you can see the terminal output clearly
    _publish(compressor_event)
    print("✅ test_sentinel_logic: Injected 'Compressor Fault' event.")

def test_compliance():
    """Simulates a legal hours violation"""
    violation_event = {
        "event_id": "evt_cmp_001",
        "anomaly_type": "ROUTE_COMPLIANCE",
        "agent": "ROUTER",
        "truck_id": "TRK-34",
        "driver_hours_used": 11.5,
        "driver_hours_limit": 10
    }

    _publish(violation_event)
    print("✅ test_compliance: Injected Driver Hours violation.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_redis.py [conflict|logic|compliance|all]")
        sys.exit(1)

    command = sys.argv[1].strip().lower()

    if command == "conflict":
        test_conflict()
    elif command == "logic":
        test_sentinel_logic()
    elif command == "compliance":
        test_compliance()
    elif command == "all":
        test_conflict()
        time.sleep(1)
        test_sentinel_logic()
        time.sleep(1)
        test_compliance()
    else:
        print("Invalid command. Use: conflict, logic, compliance, or all")