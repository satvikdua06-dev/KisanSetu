"""Agent and tool definitions.

Each specialist is its own agent: its own system prompt, its own tools, its own output schema
and its own model tier. Tools wrap deterministic code; agents never compute numbers themselves.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from app.agents.runtime.schema import strict_schema

if TYPE_CHECKING:
    from app.agents.runtime.context import ToolContext

Effort = Literal["low", "medium", "high", "xhigh", "max"]


@dataclass
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[["ToolContext", Any], Awaitable[dict[str, Any] | BaseModel]]

    def to_api(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "strict": True,
            "input_schema": strict_schema(self.input_model),
        }


class Source(BaseModel):
    name: str = Field(description="Source or tool the information came from")
    data_kind: Literal["observed", "historical", "forecast", "simulated", "computed", "reported"]
    as_of: str | None = Field(description="Date of the data, YYYY-MM-DD, if known")


class Escalation(BaseModel):
    reason: str = Field(description="Why the goal can't be met as stated")
    options: list[str] = Field(description="What would unblock it, e.g. 'pool 2,000 kg from nearby farmers'")


class SpecialistReport(BaseModel):
    """Envelope every specialist returns. `result` is specific to the agent."""

    status: Literal["completed", "escalated", "failed"]
    summary: str = Field(description="One or two sentences for the Orchestrator")
    confidence: float = Field(ge=0, le=1)
    assumptions: list[str]
    sources: list[Source]
    escalation: Escalation | None = Field(description="Required when status is 'escalated', else null")


@dataclass
class AgentDefinition:
    name: str
    role: str  # one line, shown to the Orchestrator so it knows whom to delegate to
    system_prompt: str
    output_model: type[BaseModel]
    tools: list[ToolSpec] = field(default_factory=list)
    model: str = "claude-sonnet-5-5"
    effort: Effort = "medium"
    max_turns: int = 12
    max_tokens: int = 16000

    def tool(self, name: str) -> ToolSpec | None:
        return next((t for t in self.tools if t.name == name), None)
