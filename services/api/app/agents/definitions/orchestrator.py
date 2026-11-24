"""The Orchestrator agent: owns the farmer's goal, delegates goals to specialists, evaluates their
results, handles escalations, re-plans, and asks farmers for approval. It never commits a sale itself."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.definitions.specialists import SPECIALISTS
from app.agents.runtime.agent import AgentDefinition, ToolSpec
from app.agents.runtime.context import ToolContext
from app.agents.runtime.messages import AgentMessage, MessageType
from app.agents.runtime.state import AgentTask, WorkflowStatus


class DelegateTask(BaseModel):
    agent: Literal[
        "crop_and_harvest", "market_intelligence", "buyer_matching", "collective_selling",
        "logistics", "storage_decision", "transaction_and_trust",
    ]
    goal: str = Field(description="What to achieve, not how")
    constraints: list[str]
    acceptance_criteria: list[str]


class DelegateInput(BaseModel):
    tasks: list[DelegateTask] = Field(description="Independent tasks run in parallel")


class EmptyInput(BaseModel):
    pass


class PlanInput(BaseModel):
    steps: list[str]


class Proposal(BaseModel):
    summary: str = Field(description="Plain-language summary the farmer will hear or read")
    sell_to: str = Field(description="Buyer or market")
    quantity_kg: float = Field(gt=0)
    expected_price_per_kg: float = Field(ge=0)
    net_per_kg_low: float
    net_per_kg_expected: float
    net_per_kg_high: float
    expected_net_total_inr: float
    transport_cost_per_kg: float = Field(ge=0)
    deductions_note: str
    pickup_date: date
    alternative_considered: str = Field(description="The best option the farmer is giving up, with its net")
    data_kinds: list[str] = Field(description="e.g. ['simulated buyer demand', 'observed mandi prices 2026-11-23']")


class ApprovalInput(BaseModel):
    farmer_id: str
    proposal: Proposal


class ReasonInput(BaseModel):
    reason: str


async def delegate(ctx: ToolContext, a: DelegateInput) -> dict:
    tasks = [AgentTask(agent=t.agent, goal=t.goal, constraints=t.constraints, acceptance_criteria=t.acceptance_criteria)
             for t in a.tasks]
    return {"results": await ctx.runtime.delegate(ctx.workflow, tasks)}


async def read_workflow(ctx: ToolContext, a: EmptyInput) -> dict:
    wf = ctx.workflow
    return {"id": wf.id, "goal": wf.goal, "status": wf.status, "plan": wf.plan, "farmer_ids": wf.farmer_ids,
            "sections": wf.sections, "approvals": [ap.model_dump(mode="json") for ap in wf.approvals.values()]}


async def update_plan(ctx: ToolContext, a: PlanInput) -> dict:
    ctx.workflow.plan = a.steps
    return {"plan": a.steps}


async def request_approval(ctx: ToolContext, a: ApprovalInput) -> dict:
    if a.farmer_id not in ctx.store.farmers:
        raise ValueError(f"unknown farmer {a.farmer_id}")
    approval = ctx.workflow.request_approval(a.farmer_id, a.proposal.model_dump(mode="json"))
    farmer = ctx.store.farmers[a.farmer_id]
    ctx.store.notifications.append({"farmer_id": a.farmer_id, "language": farmer.language, "approval_id": approval.id,
                                    "channel": "app+sms+voice", "text": a.proposal.summary})
    await ctx.log.append(AgentMessage(workflow_id=ctx.workflow.id, type=MessageType.APPROVAL_REQUEST,
                                      sender="orchestrator", recipient=a.farmer_id,
                                      content={"summary": a.proposal.summary, "approval_id": approval.id,
                                               "proposal": a.proposal.model_dump(mode="json")}))
    return {"approval_id": approval.id, "status": "pending",
            "note": "The workflow now waits for this farmer. Finish your turn; you will be resumed with the decision."}


async def replan(ctx: ToolContext, a: ReasonInput) -> dict:
    ctx.workflow.supersede_all()
    await ctx.log.append(AgentMessage(workflow_id=ctx.workflow.id, type=MessageType.NOTE, sender="orchestrator",
                                      recipient="workflow", content={"summary": f"Re-planning: {a.reason}"}))
    return {"superseded": "all earlier proposals; every affected farmer must approve the new one"}


async def escalate_to_coordinator(ctx: ToolContext, a: ReasonInput) -> dict:
    ctx.workflow.status = WorkflowStatus.ESCALATED_TO_COORDINATOR
    ctx.store.notifications.append({"to": "fpo_coordinator", "workflow_id": ctx.workflow.id, "text": a.reason})
    return {"status": "escalated_to_coordinator"}


class OrchestratorReport(BaseModel):
    status: Literal["in_progress", "awaiting_approval", "executing", "completed", "escalated_to_coordinator"]
    summary: str
    next_steps: list[str]
    open_risks: list[str]


ROSTER = "\n".join(f"- {name}: {a.role}" for name, a in SPECIALISTS.items())

ORCHESTRATOR_AGENT = AgentDefinition(
    name="orchestrator",
    role="Owns the farmer's selling goal, delegates to specialists, re-plans, and asks farmers for approval.",
    model="claude-opus-5-5",
    effort="high",
    max_turns=20,
    output_model=OrchestratorReport,
    tools=[
        ToolSpec("delegate", "Give one or more specialists a goal each. Independent tasks run in parallel. Returns their reports.", DelegateInput, delegate),
        ToolSpec("read_workflow", "Current workflow state: plan, every agent's findings, approvals.", EmptyInput, read_workflow),
        ToolSpec("update_plan", "Record the current plan.", PlanInput, update_plan),
        ToolSpec("request_approval", "Send one farmer a proposal to approve. The workflow then waits for them.", ApprovalInput, request_approval),
        ToolSpec("replan", "Invalidate earlier proposals after something changed; farmers must approve again.", ReasonInput, replan),
        ToolSpec("escalate_to_coordinator", "Hand the workflow to the FPO coordinator when agents can't resolve it.", ReasonInput, escalate_to_coordinator),
    ],
    system_prompt=f"""You are the Orchestrator of KisanSetu, a multi-agent market-access network that helps small and marginal farmers in India sell at the right time, place and price.

You own the farmer's goal. You do not do the specialists' work yourself: you delegate goals to them, judge their reports, and decide what happens next.

Your specialists:
{ROSTER}

How to work:
1. Make a short plan with update_plan.
2. Delegate goals, not steps. Give each task clear constraints and acceptance criteria. Delegate independent tasks together so they run in parallel (for example market_intelligence and buyer_matching).
3. Read every report critically. If a specialist escalates, decide how to resolve it, usually by bringing in another specialist (for example a buyer needs more than the farmer has: ask collective_selling to pool nearby lots, then logistics to plan pickups). If a report has low confidence or stale data, say so or ask again with tighter constraints.
4. Compare the best options on expected net realisation for the farmer, never on headline price.
5. When you have a concrete, costed option, send each affected farmer their own proposal with request_approval, including the best alternative they are giving up and which data is simulated. Then finish your turn: the workflow waits.
6. When resumed with approvals, delegate the agreements to transaction_and_trust. When resumed with an outside event (a buyer withdrew, a vehicle cancelled, a harvest came in short), call replan, re-investigate what changed, and send fresh proposals.
7. If the agents cannot find a workable option, or something needs human judgement, use escalate_to_coordinator.

Never invent numbers: every figure in a proposal must come from a specialist's report. Never commit a sale yourself; only farmers approve.
Your final answer each turn is a short status report.""",
)
