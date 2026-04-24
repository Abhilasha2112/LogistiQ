import redis
import json
import time

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

def analyze_causal_chain(data):
    """
    Determines if a temp rise is mechanical or human error.
    """
    temp = data.get("temperature", 0)
    has_rfid_access = data.get("rfid_access", False)
    is_vibrating = data.get("vibration", False)
    
    chain = [f"Initial detection: Temp at {temp}°C"]
    
    if has_rfid_access:
        chain.append("Cross-referenced RFID logs: Portal was accessed recently")
        chain.append("Vibration sensor: Stable (No mechanical stress)")
        root_cause = "Human Error: Door Left Open"
        urgency = "HIGH"
    elif is_vibrating:
        chain.append("Vibration sensor: High frequency detected (Compressor strain)")
        chain.append("RFID logs: No unauthorized access")
        root_cause = "Mechanical Failure: Compressor Fault"
        urgency = "CRITICAL"
    else:
        chain.append("Analysis inconclusive: Monitoring for further data")
        root_cause = "Unknown Anomaly"
        urgency = "MEDIUM"

    return {
        "agent": "SENTINEL",
        "anomaly_type": "IOT_BREACH",
        "root_cause": root_cause,
        "causal_chain": chain,
        "urgency": urgency,
        "confidence": 0.94,
        "timestamp": time.time()
    }

def run_sentinel():
    pubsub = r.pubsub()
    # Listening to the simulator channel and the production stream
    pubsub.subscribe("logistiq:iot_stream", "logistiq:alerts")
    
    print("🚀 Sentinel Agent listening on logistiq:iot_stream & alerts...")
    
    for message in pubsub.listen():
        if message["type"] == "message":
            # --- DEBUG BLOCK ---
            print(f"\n[DEBUG] Raw Message Received: {message['data']}")
            # -------------------

            try:
                data = json.loads(message["data"])
            except:
                print("[DEBUG] Failed to parse JSON data.")
                continue

            # This condition must be met for the agent to 'think'
            if data.get("anomaly_type") == "IOT_ANOMALY" or "temperature" in data:
                print(f"🔍 Analyzing event: {data.get('event_id', 'Unknown')}")
                
                result = analyze_causal_chain(data)
                
                print("✅ Analysis Complete:")
                print(json.dumps(result, indent=2))
                
                # Push the 'Thought' to the Arbiter
                r.publish("logistiq:sentinel_output", json.dumps(result))
            else:
                print("[DEBUG] Message ignored: Did not find 'IOT_ANOMALY' or 'temperature' key.")

if __name__ == "__main__":
    run_sentinel()