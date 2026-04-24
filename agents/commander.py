import asyncio
import json

try:
    import redis.asyncio as aioredis
except ImportError:  # fallback for older aioredis package naming
    import aioredis


class CommanderAgent:
    def __init__(self, redis_host="localhost", redis_port=6379):
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_client = None
        self.pubsub = None

        self.latest_sentinel = None
        self.latest_audit = None
        self.latest_router = None

    def _parse_payload(self, raw_data):
        try:
            return json.loads(raw_data)
        except (TypeError, json.JSONDecodeError):
            return None

    def _router_proposes_new_route(self):
        if not isinstance(self.latest_router, dict):
            return False

        route_keys = ["proposed_route", "new_route", "route_change", "route_plan"]
        if any(self.latest_router.get(key) for key in route_keys):
            return True

        route_action = str(self.latest_router.get("action", "")).upper()
        route_decision = str(self.latest_router.get("decision", "")).upper()
        return "REROUTE" in route_action or "REROUTE" in route_decision

    def _audit_missing_percentage(self):
        if not isinstance(self.latest_audit, dict):
            return 0.0

        direct_keys = [
            "missing_inventory_percent",
            "inventory_missing_percent",
            "missing_percentage",
            "shrinkage_percent",
        ]
        for key in direct_keys:
            if self.latest_audit.get(key) is not None:
                try:
                    return float(self.latest_audit.get(key))
                except (TypeError, ValueError):
                    pass

        try:
            shrinkage_value = float(self.latest_audit.get("shrinkage_value", 0))
        except (TypeError, ValueError):
            shrinkage_value = 0.0

        expected_total = self.latest_audit.get("expected_total_quantity")
        if expected_total is None:
            manifest_snapshot = self.latest_audit.get("expected_manifest_snapshot")
            if isinstance(manifest_snapshot, dict):
                expected_total = sum(manifest_snapshot.values())

        try:
            expected_total = float(expected_total)
            if expected_total > 0:
                return (shrinkage_value / expected_total) * 100
        except (TypeError, ValueError):
            pass

        return 0.0

    def _sentinel_is_critical(self):
        if not isinstance(self.latest_sentinel, dict):
            return False
        return str(self.latest_sentinel.get("urgency", "")).upper() == "CRITICAL"

    def build_executive_decision(self, trigger_channel):
        reasoning = []
        action = "CONTINUE_MONITORING"

        if self._sentinel_is_critical():
            action = "EMERGENCY_STOP"
            reasoning.append(
                "Sentinel reported CRITICAL equipment status, requiring an immediate emergency stop."
            )
        else:
            router_reroute = self._router_proposes_new_route()
            missing_pct = self._audit_missing_percentage()

            if router_reroute and missing_pct >= 20.0:
                action = "RETURN_TO_BASE"
                reasoning.append(
                    f"Router proposed a reroute, but Audit indicates {missing_pct:.1f}% inventory missing; reroute overridden."
                )
            elif router_reroute:
                action = "APPROVE_REROUTE"
                reasoning.append(
                    "Router proposed a reroute and inventory loss threshold was not breached."
                )
            else:
                reasoning.append("No blocking conflict detected; continuing monitored operations.")

        if trigger_channel == "logistiq:sentinel_output":
            reasoning.append("Decision triggered by Sentinel update.")
        elif trigger_channel == "logistiq:audit_output":
            reasoning.append("Decision triggered by Audit reconciliation update.")
        elif trigger_channel == "logistiq:router_output":
            reasoning.append("Decision triggered by Router proposal update.")

        return {
            "agent": "COMMANDER",
            "executive_decision": {
                "action": action,
                "reasoning": " ".join(reasoning),
                "inputs": {
                    "sentinel": self.latest_sentinel,
                    "audit": self.latest_audit,
                    "router": self.latest_router,
                },
            },
        }

    async def run(self):
        self.redis_client = aioredis.Redis(
            host=self.redis_host,
            port=self.redis_port,
            decode_responses=True,
        )

        self.pubsub = self.redis_client.pubsub()
        await self.pubsub.subscribe(
            "logistiq:sentinel_output",
            "logistiq:audit_output",
            "logistiq:router_output",
        )

        startup_text = "Commander Agent: prioritize the inventory management and stop rerouting"
        print(startup_text)
        await self.redis_client.publish(
            "logistiq:commander_output",
            json.dumps(
                {
                    "agent": "COMMANDER",
                    "executive_decision": {
                        "action": "INFO",
                        "reasoning": startup_text,
                        "inputs": {
                            "sentinel": self.latest_sentinel,
                            "audit": self.latest_audit,
                            "router": self.latest_router,
                        },
                    },
                }
            ),
        )
        print("Published startup commander message to logistiq:commander_output")

        try:
            while True:
                message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    await asyncio.sleep(0.05)
                    continue

                if message.get("type") != "message":
                    continue

                channel = message.get("channel")
                payload = self._parse_payload(message.get("data"))
                if not isinstance(payload, dict):
                    continue

                if channel == "logistiq:sentinel_output":
                    self.latest_sentinel = payload
                elif channel == "logistiq:audit_output":
                    self.latest_audit = payload
                elif channel == "logistiq:router_output":
                    self.latest_router = payload

                decision = self.build_executive_decision(trigger_channel=channel)
                await self.redis_client.publish("logistiq:commander_output", json.dumps(decision))
                print("Published executive decision:", decision)
        finally:
            if self.pubsub is not None:
                await self.pubsub.unsubscribe(
                    "logistiq:sentinel_output",
                    "logistiq:audit_output",
                    "logistiq:router_output",
                )
                await self.pubsub.close()
            if self.redis_client is not None:
                await self.redis_client.close()


if __name__ == "__main__":
    agent = CommanderAgent()
    asyncio.run(agent.run())
