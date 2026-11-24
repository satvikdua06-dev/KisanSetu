"""Shared workflow state (the blackboard) and the human approval gate.

Every agent can read the whole workflow; each agent may write only its own section.
Commitments can only move forward through approvals recorded here, never by an agent.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class WorkflowStatus(StrEnum):
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    ESCALATED_TO_COORDINATOR = "escalated_to_coordinator"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    FAILED = "failed"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"  # a replan replaced this proposal; needs fresh approval


class AgentTask(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent: str
    goal: str
    constraints: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.QUEUED
    output: dict[str, Any] | None = None
    error: str | None = None


class Approval(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    farmer_id: str
    proposal: dict[str, Any]
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_at: datetime | None = None
    decided_by: str | None = None  # the farmer, or "coordinator:<fpo_id>" acting on recorded farmer confirmation
    confirmation_ref: str | None = None  # e.g. call recording or signed slip id when a coordinator decides
    note: str | None = None


class SectionWriteError(PermissionError):
    pass


class ApprovalRequiredError(PermissionError):
    pass


class WorkflowState(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    goal: str
    farmer_ids: list[str]
    status: WorkflowStatus = WorkflowStatus.RUNNING
    plan: list[str] = Field(default_factory=list)
    sections: dict[str, dict[str, Any]] = Field(default_factory=dict)
    tasks: dict[str, AgentTask] = Field(default_factory=dict)
    approvals: dict[str, Approval] = Field(default_factory=dict)
    usage: dict[str, int] = Field(default_factory=dict)  # model tokens spent on this workflow
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # --- blackboard -------------------------------------------------------------
    def write(self, agent: str, key: str, value: Any, *, section: str | None = None) -> None:
        target = section or agent
        if target != agent:
            raise SectionWriteError(f"agent '{agent}' may not write to section '{target}'")
        self.sections.setdefault(agent, {})[key] = value

    def read(self, section: str, key: str, default: Any = None) -> Any:
        return self.sections.get(section, {}).get(key, default)

    # --- approval gate ------------------------------------------------------------
    def request_approval(self, farmer_id: str, proposal: dict[str, Any]) -> Approval:
        if farmer_id not in self.farmer_ids:
            self.farmer_ids.append(farmer_id)
        for existing in self.approvals.values():
            if existing.farmer_id == farmer_id and existing.status == ApprovalStatus.PENDING:
                existing.status = ApprovalStatus.SUPERSEDED
        approval = Approval(farmer_id=farmer_id, proposal=proposal)
        self.approvals[approval.id] = approval
        self.status = WorkflowStatus.AWAITING_APPROVAL
        return approval

    def decide(self, approval_id: str, approved: bool, *, decided_by: str, coordinator_for: str | None = None,
               confirmation_ref: str | None = None, note: str | None = None) -> Approval:
        """Only the farmer, or their FPO coordinator with a recorded confirmation from the farmer, can decide.

        `coordinator_for` is the farmer's FPO id, passed by the caller after checking it in the store.
        """
        approval = self.approvals.get(approval_id)
        if approval is None:
            raise ApprovalRequiredError(f"unknown approval {approval_id}")
        if approval.status != ApprovalStatus.PENDING:
            raise ApprovalRequiredError(f"approval {approval_id} is {approval.status}, not pending")
        if decided_by != approval.farmer_id:
            if not (coordinator_for and decided_by == f"coordinator:{coordinator_for}"):
                raise ApprovalRequiredError(f"{decided_by} may not decide for {approval.farmer_id}")
            if not confirmation_ref:
                raise ApprovalRequiredError("a coordinator decision needs a confirmation_ref recording the farmer's answer")
        approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        approval.decided_at = datetime.now(UTC)
        approval.decided_by = decided_by
        approval.confirmation_ref = confirmation_ref
        approval.note = note
        if not self.pending_approvals():
            self.status = WorkflowStatus.RUNNING
        return approval

    def pending_approvals(self) -> list[Approval]:
        return [a for a in self.approvals.values() if a.status == ApprovalStatus.PENDING]

    def latest_approval(self, farmer_id: str) -> Approval | None:
        mine = [a for a in self.approvals.values() if a.farmer_id == farmer_id and a.status != ApprovalStatus.SUPERSEDED]
        return mine[-1] if mine else None

    def require_approved(self, farmer_id: str) -> Approval:
        """Guardrail for every commitment tool: raises unless this farmer's current proposal is approved."""
        approval = self.latest_approval(farmer_id)
        if approval is None or approval.status != ApprovalStatus.APPROVED:
            state = approval.status if approval else "no proposal"
            raise ApprovalRequiredError(f"farmer {farmer_id} has not approved a proposal ({state})")
        return approval

    def supersede_all(self) -> None:
        """A replan invalidates earlier proposals, approved or not: every farmer must approve again."""
        for approval in self.approvals.values():
            if approval.status in (ApprovalStatus.PENDING, ApprovalStatus.APPROVED):
                approval.status = ApprovalStatus.SUPERSEDED
