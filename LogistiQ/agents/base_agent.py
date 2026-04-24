import json
import os
from pathlib import Path
from typing import Any, Dict

import redis.asyncio as redis
from anthropic import AsyncAnthropic

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

MODEL_NAME = "claude-sonnet-4-20250514"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_anthropic_client: AsyncAnthropic | None = None
_redis_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def get_anthropic_client() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    return _anthropic_client


def _strip_markdown_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        parts = cleaned.splitlines()
        if parts:
            parts = parts[1:]
        if parts and parts[-1].strip().startswith("```"):
            parts = parts[:-1]
        cleaned = "\n".join(parts).strip()
    return cleaned


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _infer_agent_key(system_prompt: str) -> str:
    """Map system prompt to the correct mock response key. Covers all 6 agents."""
    prompt = system_prompt.lower()
    if "arbiter" in prompt:
        return "ARBITER"
    if "commander" in prompt:
        return "COMMANDER"
    if "sentinel" in prompt:
        return "SENTINEL"
    if "audit" in prompt:
        return "AUDIT"
    if "router" in prompt:
        return "ROUTER"
    return "SCOUT"


def load_mock_response(agent_key: str) -> Dict[str, Any]:
    mock_file = _project_root() / "mock_responses" / "crisis_scenario.json"
    key = agent_key.upper()

    if not mock_file.exists():
        return {"error": "mock file not found", "agent": key}
    try:
        parsed = json.loads(mock_file.read_text(encoding="utf-8").strip())
        if isinstance(parsed, dict):
            if key in parsed:
                return parsed[key]
            if key.lower() in parsed:
                return parsed[key.lower()]
    except Exception as e:
        return {"error": str(e), "agent": key}
    return {"error": f"key {key} not found in mock", "agent": key}


async def call_llm(system_prompt: str, user_data: Dict[str, Any]) -> Dict[str, Any]:
    agent_key = _infer_agent_key(system_prompt)
    if os.getenv("DEMO_MODE", "false").lower() == "true":
        return load_mock_response(agent_key)
    try:
        client = get_anthropic_client()
        response = await client.messages.create(
            model=MODEL_NAME,
            max_tokens=1200,
            system=system_prompt,
            messages=[{"role": "user", "content": json.dumps(user_data, ensure_ascii=True)}],
        )
        text_chunks = [getattr(b, "text", None) for b in response.content]
        raw_text = "\n".join(t for t in text_chunks if t)
        return json.loads(_strip_markdown_fences(raw_text))
    except Exception:
        return load_mock_response(agent_key)


async def publish_to_dashboard(redis_client, agent: str, message: str) -> None:
    payload = json.dumps({"agent": agent, "message": message})
    await redis_client.publish("logistiq:dashboard", payload)
