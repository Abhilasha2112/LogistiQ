import json
import os

import redis
import requests

# --- CONFIGURATION ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
COMMANDER_CHANNEL = os.getenv("COMMANDER_CHANNEL", "logistiq:commander_output")
r = redis.Redis(host="localhost", port=6379, decode_responses=True)

def send_telegram_msg(text):
    if not TOKEN or not CHAT_ID:
        print("❌ Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in environment.")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            print(f"❌ Telegram API rejected message: {body}")
        else:
            print("✅ Telegram message sent.")
    except Exception as e:
        print(f"❌ Telegram Error: {e}")


def validate_telegram_connection():
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN is not set.")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/getMe"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 404:
            print("❌ Telegram rejected the bot token. Check TELEGRAM_BOT_TOKEN from BotFather.")
            return False
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            print(f"❌ Telegram token validation failed: {body}")
            return False

        bot_info = body.get("result", {})
        print(f"✅ Telegram bot authenticated: @{bot_info.get('username', 'unknown')}")
        return True
    except Exception as e:
        print(f"❌ Telegram validation error: {e}")
        return False


def build_message(data):
    # Support both commander payload contracts used in this workspace.
    if isinstance(data, dict) and isinstance(data.get("executive_decision"), dict):
        decision = data.get("executive_decision", {})
        action = decision.get("action", "UNKNOWN_ACTION")
        reason = decision.get("reasoning", "No reason provided.")
        return (
            "COMMANDER UPDATE\n"
            "---------------\n"
            f"Action: {action}\n"
            f"Reason: {reason}\n"
            f"Time: {data.get('timestamp', 'N/A')}"
        )

    summary = data.get("executive_summary", "Decision compiled.") if isinstance(data, dict) else str(data)
    human = data.get("requires_human_attention", False) if isinstance(data, dict) else False
    human_reason = data.get("human_attention_reason", "") if isinstance(data, dict) else ""
    return (
        "COMMANDER UPDATE\n"
        "---------------\n"
        f"Summary: {summary}\n"
        f"Needs human attention: {human}\n"
        f"Reason: {human_reason or 'N/A'}"
    )


def run_notifier():
    print("📱 Telegram Notifier: ONLINE")
    print(f"🔔 Subscribed channel: {COMMANDER_CHANNEL}")

    if not validate_telegram_connection():
        return

    pubsub = r.pubsub()

    # Listen to the Commander's final decisions
    pubsub.subscribe(COMMANDER_CHANNEL)

    for message in pubsub.listen():
        if message["type"] == "message":
            raw = message.get("data", "")
            print(f"📥 Received commander event: {raw}")

            try:
                data = json.loads(raw)
            except Exception:
                data = {"raw": str(raw)}

            msg = build_message(data)
            print("📩 Forwarding decision to Telegram...")
            send_telegram_msg(msg)

if __name__ == "__main__":
    run_notifier()