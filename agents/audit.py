import redis
import json

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

def perform_reconciliation(data):
    """
    Compares expected inventory vs actual scanned items.
    """
    expected = data.get("expected", 0)
    scanned = data.get("scanned", 0)
    gap = expected - scanned
    
    # Logic: If more than 10% is missing, it's a critical risk
    is_critical = gap > (expected * 0.1)
    
    result = {
        "agent": "AUDIT",
        "truck_id": data.get("truck_id", "UNKNOWN"),
        "inventory_gap": gap,
        "status": "CRITICAL_SHORTAGE" if is_critical else "NORMAL",
        "will_reroute_worsen_shortage": is_critical,
        "potential_loss": gap * 150, # Example value per unit
        "confidence": 1.0
    }
    return result

def run_audit():
    pubsub = r.pubsub()
    # Listen to the simulation channel
    pubsub.subscribe("logistiq:alerts")
    
    print("📋 Audit Agent listening for inventory scans...")
    
    for message in pubsub.listen():
        if message["type"] == "message":
            try:
                data = json.loads(message["data"])
            except:
                continue

            # Only process if it's an inventory mismatch
            if data.get("anomaly_type") == "RFID_MISMATCH":
                print(f"\n📦 Reconciling Shipment for {data.get('truck_id')}")
                
                audit_result = perform_reconciliation(data)
                
                print("✅ Audit Complete:")
                print(json.dumps(audit_result, indent=2))
                
                # Send the analysis to the Arbiter for final decision
                r.publish("logistiq:audit_output", json.dumps(audit_result))

if __name__ == "__main__":
    run_audit()