"""One agent's own reasoning loop: think, call tools, read results, repeat, then report.

Every specialist and the Orchestrator run through this loop with their own definition.
"""

import asyncio
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agents.runtime.agent import AgentDefinition
from app.agents.runtime.context import ToolContext
from app.agents.runtime.messages import AgentMessage, MessageType
from app.agents.runtime.model import ModelClient, ToolUse


class AgentRunError(RuntimeError):
    pass


@dataclass
class AgentRun:
    agent: str
    output: BaseModel
    turns: int
    tool_calls: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"cannot serialise {type(value).__name__}")


async def _execute(agent: AgentDefinition, use: ToolUse, ctx: ToolContext) -> dict[str, Any]:
    spec = agent.tool(use.name)
    await ctx.log.append(AgentMessage(
        workflow_id=ctx.workflow.id, correlation_id=ctx.task_id, type=MessageType.TOOL_CALL,
        sender=agent.name, recipient=use.name, content={"tool": use.name, "input": use.input},
    ))
    if spec is None:
        return {"type": "tool_result", "tool_use_id": use.id, "is_error": True,
                "content": f"Error: unknown tool '{use.name}'"}
    try:
        args = spec.input_model.model_validate(use.input)
        result = await spec.handler(ctx, args)
        if isinstance(result, BaseModel):
            result = result.model_dump(mode="json")
        return {"type": "tool_result", "tool_use_id": use.id, "content": json.dumps(result, default=_json_default)}
    except ValidationError as exc:
        return {"type": "tool_result", "tool_use_id": use.id, "is_error": True,
                "content": f"Error: invalid input: {exc.errors(include_url=False)}"}
    except Exception as exc:  # tool errors go back to the agent so it can adapt
        return {"type": "tool_result", "tool_use_id": use.id, "is_error": True,
                "content": f"Error: {type(exc).__name__}: {exc}"}


async def run_agent(
    agent: AgentDefinition, task_prompt: str, ctx: ToolContext, model: ModelClient
) -> AgentRun:
    messages: list[dict[str, Any]] = [{"role": "user", "content": task_prompt}]
    run = AgentRun(agent=agent.name, output=None, turns=0)  # type: ignore[arg-type]
    reminded = False

    while run.turns < agent.max_turns:
        run.turns += 1
        response = await model.create(agent, messages)
        for k, v in response.usage.items():
            run.usage[k] = run.usage.get(k, 0) + v

        if response.stop_reason == "refusal":
            raise AgentRunError(f"{agent.name}: the model declined this request")
        if response.stop_reason == "max_tokens":
            raise AgentRunError(f"{agent.name}: response hit max_tokens")

        messages.append({"role": "assistant", "content": response.assistant_content})

        if response.stop_reason == "pause_turn":
            continue

        if response.tool_uses:
            results = await asyncio.gather(*(_execute(agent, u, ctx) for u in response.tool_uses))
            run.tool_calls.extend(u.name for u in response.tool_uses)
            messages.append({"role": "user", "content": list(results)})
            continue

        try:
            run.output = agent.output_model.model_validate_json(response.text)
            return run
        except ValidationError as exc:
            if reminded:
                raise AgentRunError(f"{agent.name}: output did not match its schema: {exc}") from None
            reminded = True
            messages.append({"role": "user", "content": (
                f"Your final answer did not match the required output schema: {exc.errors(include_url=False)}. "
                "Reply again with only the corrected JSON."
            )})

    raise AgentRunError(f"{agent.name}: no final answer within {agent.max_turns} turns")
