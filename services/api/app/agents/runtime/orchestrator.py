"""The multi-agent runtime: runs the Orchestrator, delegates goals to specialists (in parallel),
records every message, and resumes workflows on approvals and outside events.

Workflows live in state, not in a model's context, so they can wait days for a farmer's answer.
"""

import asyncio
import json
from typing import Any

from app.agents.runtime.agent import AgentDefinition
from app.agents.runtime.context import ToolContext
from app.agents.runtime.loop import AgentRun, AgentRunError, run_agent
from app.agents.runtime.messages import AgentMessage, MessageLog, MessageType
from app.agents.runtime.model import ModelClient
from app.agents.runtime.state import AgentTask, TaskStatus, WorkflowState, WorkflowStatus

ORCHESTRATOR = "orchestrator"


class Runtime:
    def __init__(
        self,
        orchestrator: AgentDefinition,
        specialists: dict[str, AgentDefinition],
        model: ModelClient,
        store: Any,
        log: MessageLog | None = None,
    ):
        self.orchestrator = orchestrator
        self.specialists = specialists
        self.model = model
        self.store = store
        self.log = log or MessageLog()
        self.workflows: dict[str, WorkflowState] = {}

    # --- entry points ---------------------------------------------------------------------
    async def start(self, goal: str, farmer_id: str) -> WorkflowState:
        wf = WorkflowState(goal=goal, farmer_ids=[farmer_id])
        self.workflows[wf.id] = wf
        await self._msg(wf, MessageType.EVENT, "farmer", ORCHESTRATOR, {"summary": goal, "farmer_id": farmer_id})
        await self._run_orchestrator(wf, f"New selling workflow {wf.id}.\nFarmer: {farmer_id}\nGoal: {goal}")
        return wf

    async def decide_approval(self, workflow_id: str, approval_id: str, approved: bool, note: str | None = None) -> WorkflowState:
        """Called by the farmer-facing channel only (app, SMS, voice call, coordinator with recorded consent)."""
        wf = self.workflows[workflow_id]
        approval = wf.decide(approval_id, approved, note)
        await self._msg(wf, MessageType.APPROVAL_DECISION, approval.farmer_id, ORCHESTRATOR,
                        {"summary": f"{approval.farmer_id} {'approved' if approved else 'rejected'}",
                         "approval_id": approval_id, "approved": approved, "note": note})
        if not wf.pending_approvals():
            decisions = [{"farmer_id": a.farmer_id, "status": a.status.value, "note": a.note}
                         for a in wf.approvals.values() if a.status.value in ("approved", "rejected")]
            await self._run_orchestrator(wf, f"All pending approvals are decided: {json.dumps(decisions)}. Decide the next step.")
        return wf

    async def handle_event(self, workflow_id: str, event: dict[str, Any]) -> WorkflowState:
        """Something changed in the outside world (buyer withdrew, vehicle cancelled, harvest smaller...)."""
        wf = self.workflows[workflow_id]
        await self._msg(wf, MessageType.EVENT, event.get("source", "external"), ORCHESTRATOR,
                        {"summary": event.get("summary", ""), **event})
        wf.status = WorkflowStatus.RUNNING
        await self._run_orchestrator(wf, f"External event for workflow {wf.id}: {json.dumps(event)}\nRe-plan from the current state.")
        return wf

    # --- delegation (called by the Orchestrator's delegate tool) ---------------------------
    async def delegate(self, wf: WorkflowState, tasks: list[AgentTask]) -> list[dict[str, Any]]:
        for t in tasks:
            if t.agent not in self.specialists:
                raise ValueError(f"unknown agent '{t.agent}'; available: {sorted(self.specialists)}")
            wf.tasks[t.id] = t
            await self._msg(wf, MessageType.TASK, ORCHESTRATOR, t.agent,
                            {"summary": t.goal, "goal": t.goal, "constraints": t.constraints,
                             "acceptance_criteria": t.acceptance_criteria}, correlation_id=t.id)
        return list(await asyncio.gather(*(self._run_specialist(wf, t) for t in tasks)))

    async def _run_specialist(self, wf: WorkflowState, task: AgentTask) -> dict[str, Any]:
        agent = self.specialists[task.agent]
        task.status = TaskStatus.RUNNING
        ctx = ToolContext(agent=agent.name, workflow=wf, log=self.log, store=self.store, runtime=self, task_id=task.id)
        prompt = (
            f"Task {task.id} from the Orchestrator, workflow {wf.id}.\n"
            f"Goal: {task.goal}\n"
            f"Constraints: {json.dumps(task.constraints)}\n"
            f"Acceptance criteria: {json.dumps(task.acceptance_criteria)}\n"
            f"Farmers in this workflow: {json.dumps(wf.farmer_ids)}\n"
            f"What other agents have found so far: {json.dumps(wf.sections, default=str)}"
        )
        try:
            run: AgentRun = await run_agent(agent, prompt, ctx, self.model)
        except AgentRunError as exc:
            task.status, task.error = TaskStatus.FAILED, str(exc)
            await self._msg(wf, MessageType.RESULT, agent.name, ORCHESTRATOR,
                            {"summary": f"failed: {exc}", "status": "failed"}, correlation_id=task.id)
            return {"task_id": task.id, "agent": agent.name, "status": "failed", "error": str(exc)}

        output = run.output.model_dump(mode="json")
        task.output = output
        task.status = TaskStatus.ESCALATED if output["status"] == "escalated" else (
            TaskStatus.FAILED if output["status"] == "failed" else TaskStatus.COMPLETED)
        wf.write(agent.name, task.id, output)  # the specialist's own section of the blackboard
        msg_type = MessageType.ESCALATION if output["status"] == "escalated" else MessageType.RESULT
        await self._msg(wf, msg_type, agent.name, ORCHESTRATOR, output, correlation_id=task.id)
        return {"task_id": task.id, "agent": agent.name, **output}

    # --- internals ------------------------------------------------------------------------
    async def _run_orchestrator(self, wf: WorkflowState, prompt: str) -> AgentRun | None:
        ctx = ToolContext(agent=ORCHESTRATOR, workflow=wf, log=self.log, store=self.store, runtime=self)
        try:
            run = await run_agent(self.orchestrator, prompt, ctx, self.model)
        except AgentRunError as exc:
            wf.status = WorkflowStatus.ESCALATED_TO_COORDINATOR
            await self._msg(wf, MessageType.NOTE, ORCHESTRATOR, "fpo_coordinator",
                            {"summary": f"Orchestrator failed, handing to coordinator: {exc}"})
            return None
        output = run.output.model_dump(mode="json")
        wf.write(ORCHESTRATOR, "last_report", output)
        if wf.pending_approvals():
            wf.status = WorkflowStatus.AWAITING_APPROVAL
        elif output.get("status") == "completed":
            wf.status = WorkflowStatus.COMPLETED
        await self._msg(wf, MessageType.NOTE, ORCHESTRATOR, "workflow", output)
        return run

    async def _msg(self, wf: WorkflowState, type_: MessageType, sender: str, recipient: str,
                   content: dict[str, Any], correlation_id: str | None = None) -> None:
        await self.log.append(AgentMessage(workflow_id=wf.id, correlation_id=correlation_id, type=type_,
                                           sender=sender, recipient=recipient, content=content))
