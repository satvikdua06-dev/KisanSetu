"""The agent message log: every task, result, escalation, question and external event.

It is the audit trail and the source of the dashboard's agent-trace view.
In-memory here; the Postgres-backed log keeps the same interface.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MessageType(StrEnum):
    TASK = "task"  # Orchestrator -> specialist
    RESULT = "result"  # specialist -> Orchestrator
    ESCALATION = "escalation"  # specialist -> Orchestrator: goal can't be met as stated
    QUESTION = "question"  # specialist -> Orchestrator
    EVENT = "event"  # outside world -> Orchestrator (buyer withdrew, farmer replied...)
    APPROVAL_REQUEST = "approval_request"  # Orchestrator -> farmer
    APPROVAL_DECISION = "approval_decision"  # farmer -> workflow
    TOOL_CALL = "tool_call"  # any agent -> deterministic tool (trace only)
    NOTE = "note"


class AgentMessage(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    workflow_id: str
    correlation_id: str | None = None  # ties a result/escalation to its task
    type: MessageType
    sender: str
    recipient: str
    content: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MessageLog:
    def __init__(self) -> None:
        self._messages: list[AgentMessage] = []
        self._lock = asyncio.Lock()

    async def append(self, message: AgentMessage) -> AgentMessage:
        async with self._lock:
            self._messages.append(message)
        return message

    def for_workflow(self, workflow_id: str) -> list[AgentMessage]:
        return [m for m in self._messages if m.workflow_id == workflow_id]

    def trace(self, workflow_id: str) -> list[str]:
        """Human-readable one-line-per-message trace (demo and debugging)."""
        lines = []
        for m in self.for_workflow(workflow_id):
            summary = m.content.get("summary") or m.content.get("goal") or m.content.get("tool") or ""
            lines.append(f"{m.type.value:<18} {m.sender} -> {m.recipient}: {summary}")
        return lines
