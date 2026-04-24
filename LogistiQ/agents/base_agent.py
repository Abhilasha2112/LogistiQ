import anthropic
import redis
import json
import os
from dotenv import load_dotenv

load_dotenv()

r = redis.Redis(host='localhost', port=6379, decode_responses=True)
client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

DEMO_MODE = os.getenv('DEMO_MODE', 'false').lower() == 'true'


def call_llm(system_prompt: str, user_data: dict) -> dict:
    response = client.messages.create(
        model='claude-sonnet-4-20250514',
        max_tokens=1000,
        system=system_prompt,
        messages=[{'role': 'user', 'content': json.dumps(user_data)}]
    )
    text = response.content[0].text
    # Strip markdown code fences if present
    text = text.replace('```json', '').replace('```', '').strip()
    return json.loads(text)


def get_mock_response(agent_name: str) -> dict:
    """Load pre-baked response from crisis_scenario.json for DEMO_MODE."""
    mock_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'mock_responses', 'crisis_scenario.json'
    )
    with open(mock_path, encoding='utf-8') as f:
        return json.load(f)[agent_name]


def publish(channel: str, data: dict) -> None:
    """Publish a JSON message to a Redis channel."""
    r.publish(channel, json.dumps(data))


def health_check() -> bool:
    """Verify Redis is reachable before starting any agent."""
    try:
        r.ping()
        print("[INFO] Redis connection OK")
        return True
    except Exception as e:
        print(f"[ERROR] Redis not reachable: {e}")
        print("[ERROR] Make sure Memurai/Redis is running before starting agents.")
        return False
