"""The Claude client against the real Anthropic SDK, with the HTTP layer mocked (no API key, no network)."""

import json

import anthropic
import httpx2 as httpx  # the Anthropic SDK 2.x is built on httpx2

from app.agents.definitions.orchestrator import ORCHESTRATOR_AGENT
from app.agents.definitions.specialists import CROP_AND_HARVEST
from app.agents.runtime.model import ClaudeModelClient


def fake_api(captured: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append({"path": request.url.path, "query": dict(request.url.params),
                         "beta": request.headers.get("anthropic-beta"), "body": body})
        return httpx.Response(200, json={
            "id": "msg_test", "type": "message", "role": "assistant", "model": body["model"],
            "content": [
                {"type": "text", "text": '{"status": "in_progress", "summary": "ok", "next_steps": [], "open_risks": []}'},
                {"type": "tool_use", "id": "toolu_1", "name": "read_workflow", "input": {}},
            ],
            "stop_reason": "tool_use", "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 7},
        })

    return httpx.MockTransport(handler)


async def test_opus_agent_request_uses_strict_tools_output_schema_and_fallbacks():
    captured: list[dict] = []
    sdk = anthropic.AsyncAnthropic(api_key="test", http_client=httpx.AsyncClient(transport=fake_api(captured)))
    response = await ClaudeModelClient(sdk).create(ORCHESTRATOR_AGENT, [{"role": "user", "content": "start"}])

    req = captured[0]
    body = req["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in req["beta"]
    assert body["output_config"]["effort"] == "high"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert all(t["strict"] for t in body["tools"])
    assert {t["name"] for t in body["tools"]} >= {"delegate", "request_approval", "replan"}
    assert "tool_choice" not in body  # forced tool choice is not allowed on these models

    assert response.stop_reason == "tool_use"
    assert response.tool_uses[0].name == "read_workflow"
    assert response.usage == {"input_tokens": 12, "output_tokens": 7}


async def test_haiku_agent_uses_standard_endpoint():
    captured: list[dict] = []
    sdk = anthropic.AsyncAnthropic(api_key="test", http_client=httpx.AsyncClient(transport=fake_api(captured)))
    await ClaudeModelClient(sdk).create(CROP_AND_HARVEST, [{"role": "user", "content": "start"}])
    body = captured[0]["body"]
    assert body["model"] == "claude-haiku-5-5"
    assert "fallbacks" not in body
