"""Model clients. The agent loop talks to this interface, so tests run with a scripted model
and production runs with Claude through the official Anthropic SDK."""

import json
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.agents.runtime.agent import AgentDefinition
from app.agents.runtime.schema import strict_schema

# Models that get the API's server-side refusal fallbacks (see docs/STACK.md).
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ModelResponse:
    stop_reason: str
    text: str
    tool_uses: list[ToolUse]
    assistant_content: Any  # appended back to the conversation unchanged
    model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


class ModelClient(Protocol):
    async def create(
        self, agent: AgentDefinition, messages: list[dict[str, Any]]
    ) -> ModelResponse: ...


class ClaudeModelClient:
    """Calls Claude with the agent's prompt, strict tools and structured output schema."""

    def __init__(self, client: Any | None = None):
        if client is None:
            import anthropic

            client = anthropic.AsyncAnthropic()
        self._client = client

    async def create(self, agent: AgentDefinition, messages: list[dict[str, Any]]) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": agent.model,
            "max_tokens": agent.max_tokens,
            "system": agent.system_prompt,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": agent.effort,
                "format": {"type": "json_schema", "schema": strict_schema(agent.output_model)},
            },
        }
        if agent.tools:
            kwargs["tools"] = [t.to_api() for t in agent.tools]

        if agent.model in _FALLBACK_MODELS:
            response = await self._client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        else:
            response = await self._client.messages.create(**kwargs)

        texts, tool_uses = [], []
        for block in response.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(ToolUse(id=block.id, name=block.name, input=block.input))
        usage = {
            "input_tokens": getattr(response.usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(response.usage, "output_tokens", 0) or 0,
        }
        return ModelResponse(
            stop_reason=response.stop_reason,
            text="".join(texts),
            tool_uses=tool_uses,
            assistant_content=response.content,
            model=response.model,
            usage=usage,
        )


# --- Scripted model for tests and offline demos --------------------------------------------

ScriptStep = Callable[[AgentDefinition, list[dict[str, Any]]], ModelResponse]


def call_tools(*calls: tuple[str, dict[str, Any]]) -> ScriptStep:
    """A scripted turn that calls one or more tools (in parallel, like Claude can)."""

    def step(agent: AgentDefinition, messages: list[dict[str, Any]]) -> ModelResponse:
        uses = [ToolUse(id=f"tu_{agent.name}_{len(messages)}_{i}", name=n, input=a) for i, (n, a) in enumerate(calls)]
        content = [{"type": "tool_use", "id": u.id, "name": u.name, "input": u.input} for u in uses]
        return ModelResponse(stop_reason="tool_use", text="", tool_uses=uses, assistant_content=content)

    return step


def finish(output: dict[str, Any] | Callable[[list[dict[str, Any]]], dict[str, Any]]) -> ScriptStep:
    """A scripted final turn returning the structured output (or a function of the conversation)."""

    def step(agent: AgentDefinition, messages: list[dict[str, Any]]) -> ModelResponse:
        data = output(messages) if callable(output) else output
        text = json.dumps(data)
        return ModelResponse(
            stop_reason="end_turn", text=text, tool_uses=[], assistant_content=[{"type": "text", "text": text}]
        )

    return step


class ScriptedModelClient:
    """Plays back a script per agent: a list of steps consumed in order each time that agent runs."""

    def __init__(self, scripts: dict[str, list[ScriptStep]]):
        self._scripts = {name: deque(steps) for name, steps in scripts.items()}
        self.calls: list[tuple[str, int]] = []

    async def create(self, agent: AgentDefinition, messages: list[dict[str, Any]]) -> ModelResponse:
        queue = self._scripts.get(agent.name)
        if not queue:
            raise AssertionError(f"no scripted step left for agent '{agent.name}'")
        self.calls.append((agent.name, len(messages)))
        return queue.popleft()(agent, messages)


def last_tool_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Helper for scripts: the parsed tool results from the latest user turn."""
    content = messages[-1]["content"]
    if not isinstance(content, list):
        return []
    out = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            try:
                out.append(json.loads(block["content"]))
            except (json.JSONDecodeError, TypeError):
                out.append({"raw": block["content"]})
    return out
