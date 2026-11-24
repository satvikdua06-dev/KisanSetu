"""What a tool sees when an agent calls it."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.agents.runtime.messages import MessageLog
from app.agents.runtime.state import WorkflowState

if TYPE_CHECKING:
    from app.agents.runtime.orchestrator import Runtime


@dataclass
class ToolContext:
    agent: str
    workflow: WorkflowState
    log: MessageLog
    store: Any  # app.domain.store.Store; Any to avoid an import cycle
    runtime: "Runtime"
    task_id: str | None = None
