import redis
import json
import time

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

def test_commander_scenarios():
    print("🚀 Starting Commander Executive Tests...")

    # Scenario 1: CRITICAL SENTINEL (Should trigger EMERGENCY_STOP)
    print("\n--- Testing Scenario 1: Critical Equipment Failure ---")
    sentinel_payload = {
        "agent": "SENTINEL",
        "urgency": "CRITICAL",
        "root_cause": "Compressor Exploded"
    }
    r.publish("logistiq:sentinel_output", json.dumps(sentinel_payload))
    time.sleep(1)

    # Scenario 2: REROUTE + HIGH LOSS (Should trigger RETURN_TO_BASE)
    print("\n--- Testing Scenario 2: High Inventory Loss Conflict ---")
    # Reset sentinel urgency first
    r.publish("logistiq:sentinel_output", json.dumps({"urgency": "LOW"}))
    
    router_payload = {"decision": "REROUTE", "proposed_route": "Express_Way_B"}
    audit_payload = {"shrinkage_value": 25, "expected_total_quantity": 100} # 25% loss
    
    r.publish("logistiq:router_output", json.dumps(router_payload))
    r.publish("logistiq:audit_output", json.dumps(audit_payload))
    time.sleep(1)

    # Scenario 3: REROUTE + LOW LOSS (Should trigger APPROVE_REROUTE)
    print("\n--- Testing Scenario 3: Safe Reroute ---")
    audit_safe = {"shrinkage_value": 5, "expected_total_quantity": 100} # 5% loss
    r.publish("logistiq:audit_output", json.dumps(audit_safe))
    time.sleep(1)

if __name__ == "__main__":
    test_commander_scenarios()