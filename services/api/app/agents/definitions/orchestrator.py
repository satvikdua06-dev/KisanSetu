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
    sell_to: str = Field(description="Buyer or market name, exactly as in the specialist's report")
    price_basis: str = Field(description="Where the price comes from: 'buyer:<requirement_id>' or 'market:<market_id>'")
    lot_id: str = Field(description="The farmer's lot this sale draws from")
    quantity_kg: float = Field(gt=0)
    expected_price_per_kg: float = Field(ge=0)
    net_per_kg_low: float
    net_per_kg_expected: float
    net_per_kg_high: float
    expected_net_total_inr: float
    transport_cost_per_kg: float = Field(ge=0)
    other_costs_per_kg: float = Field(ge=0, description="Handling, fees, expected deductions, per kg")
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


_PRICE_TOL = 0.01  # INR/kg
_NET_TOL = 0.05  # INR/kg, rounding in reports


class ProposalCheckError(ValueError):
    pass


def check_proposal(ctx: ToolContext, farmer_id: str, p: Proposal) -> None:
    """Deterministic checks so a proposal can't carry invented or inconsistent numbers.

    - the lot is this farmer's and has the quantity available;
    - the price is traceable to a real buyer requirement or a market observation in the store;
    - net = price - transport - other costs, low <= expected <= high, total = net x quantity.
    """
    store = ctx.store
    if farmer_id not in store.farmers:
        raise ProposalCheckError(f"unknown farmer {farmer_id}")
    lot = store.lots.get(p.lot_id)
    if lot is None or lot.farmer_id != farmer_id:
        raise ProposalCheckError(f"lot {p.lot_id} does not belong to {farmer_id}")
    if p.quantity_kg > lot.available_kg + 1e-6:
        raise ProposalCheckError(f"quantity {p.quantity_kg} kg exceeds the {lot.available_kg} kg available in {lot.id}")
    if p.pickup_date < store.today:
        raise ProposalCheckError("pickup date is in the past")

    kind, _, ref = p.price_basis.partition(":")
    if kind == "buyer":
        req = store.buyer_requirements.get(ref)
        if req is None or not req.active or req.commodity_id != lot.commodity_id:
            raise ProposalCheckError(f"price basis {p.price_basis} is not an active requirement for this crop")
        if abs(req.price_per_kg - p.expected_price_per_kg) > _PRICE_TOL:
            raise ProposalCheckError(f"price {p.expected_price_per_kg} does not match {req.buyer_name}'s {req.price_per_kg}")
        if p.sell_to != req.buyer_name:
            raise ProposalCheckError(f"sell_to '{p.sell_to}' does not match the buyer '{req.buyer_name}'")
    elif kind == "market":
        obs = [o for o in store.prices if o.market_id == ref and o.commodity_id == lot.commodity_id]
        if not obs:
            raise ProposalCheckError(f"no price observations for market {ref}")
        latest = max(obs, key=lambda o: o.date)
        lo = float(latest.min_price_per_kg if latest.min_price_per_kg is not None else latest.modal_price_per_kg)
        hi = float(latest.max_price_per_kg if latest.max_price_per_kg is not None else latest.modal_price_per_kg)
        if not lo - _PRICE_TOL <= p.expected_price_per_kg <= hi + _PRICE_TOL:
            raise ProposalCheckError(f"price {p.expected_price_per_kg} is outside the observed range {lo}-{hi} at {ref}")
    else:
        raise ProposalCheckError("price_basis must be 'buyer:<requirement_id>' or 'market:<market_id>'")

    expected_net = p.expected_price_per_kg - p.transport_cost_per_kg - p.other_costs_per_kg
    if abs(expected_net - p.net_per_kg_expected) > _NET_TOL:
        raise ProposalCheckError(f"net per kg {p.net_per_kg_expected} != price - transport - other costs = {expected_net:.2f}")
    if not p.net_per_kg_low <= p.net_per_kg_expected <= p.net_per_kg_high:
        raise ProposalCheckError("net per kg must satisfy low <= expected <= high")
    if abs(p.net_per_kg_expected * p.quantity_kg - p.expected_net_total_inr) > max(1.0, 0.001 * abs(p.expected_net_total_inr)):
        raise ProposalCheckError(f"expected net total {p.expected_net_total_inr} != net per kg x quantity")


async def request_approval(ctx: ToolContext, a: ApprovalInput) -> dict:
    check_proposal(ctx, a.farmer_id, a.proposal)
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


def void_workflow_agreements(store, workflow_id: str, reason: str) -> list[str]:
    """Void draft agreements of a workflow and release the lot quantities they reserved."""
    voided = []
    for agr in store.agreements.values():
        if agr["workflow_id"] == workflow_id and agr["status"] == "draft":
            agr["status"], agr["void_reason"] = "voided", reason
            lot = store.lots.get(agr["lot_id"])
            if lot is not None:
                lot.committed_kg = max(0.0, lot.committed_kg - agr["quantity_kg"])
                if lot.committed_kg == 0 and lot.status == "committed":
                    lot.status = "available"
            voided.append(agr["id"])
    return voided


async def replan(ctx: ToolContext, a: ReasonInput) -> dict:
    ctx.workflow.supersede_all()
    voided = void_workflow_agreements(ctx.store, ctx.workflow.id, a.reason)
    await ctx.log.append(AgentMessage(workflow_id=ctx.workflow.id, type=MessageType.NOTE, sender="orchestrator",
                                      recipient="workflow",
                                      content={"summary": f"Re-planning: {a.reason}", "voided_agreements": voided}))
    return {"superseded": "all earlier proposals; every affected farmer must approve the new one",
            "voided_draft_agreements": voided}


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
5. When you have a concrete, costed option, send each affected farmer their own proposal with request_approval, including the best alternative they are giving up and which data is simulated. Set price_basis to the buyer requirement or market the price came from, and lot_id to the farmer's lot. request_approval checks the numbers against the data and rejects inconsistent proposals; fix the proposal rather than arguing with the check. Then finish your turn: the workflow waits.
6. When resumed with approvals, delegate the agreements to transaction_and_trust. When resumed with an outside event (a buyer withdrew, a vehicle cancelled, a harvest came in short), call replan, re-investigate what changed, and send fresh proposals.
7. If the agents cannot find a workable option, or something needs human judgement, use escalate_to_coordinator.

Never invent numbers: every figure in a proposal must come from a specialist's report. Never commit a sale yourself; only farmers approve.
Your final answer each turn is a short status report.""",
)
