"""The tomato scenario through the real multi-agent runtime, with a scripted model standing in for Claude.

Every tool call runs the real deterministic code. What's scripted is only each agent's choice of
which tool to call and what to report, so the test checks delegation, parallel work, escalation,
approval gates, guardrails and replanning without an API key.
"""

import asyncio

import pytest

from app.agents.definitions.orchestrator import ORCHESTRATOR_AGENT
from app.agents.definitions.specialists import SPECIALISTS
from app.agents.runtime.agent import SpecialistReport
from app.agents.runtime.messages import MessageType
from app.agents.runtime.model import ScriptedModelClient, call_tools, finish, last_tool_results
from app.agents.runtime.orchestrator import Runtime
from app.agents.runtime.schema import strict_schema
from app.agents.runtime.state import ApprovalRequiredError, ApprovalStatus, WorkflowStatus
from app.domain.seed import seeded_store

READY = "2026-11-29"


def report(status="completed", summary="done", result=None, escalation=None, confidence=0.8):
    return {"status": status, "summary": summary, "confidence": confidence, "assumptions": [],
            "sources": [{"name": "simulated seed", "data_kind": "simulated", "as_of": "2026-11-23"}],
            "escalation": escalation, "result": result}


def task(agent, goal):
    return {"agent": agent, "goal": goal, "constraints": [], "acceptance_criteria": []}


def proposal(farmer_kg, net_total):
    return {"summary": "Sell to processor at INR 25/kg", "sell_to": "Simulated Tomato Processor", "quantity_kg": farmer_kg,
            "expected_price_per_kg": 25.0, "net_per_kg_low": 23.4, "net_per_kg_expected": 23.4, "net_per_kg_high": 23.4,
            "expected_net_total_inr": net_total, "transport_cost_per_kg": 0.6, "deductions_note": "grade checked at pickup",
            "pickup_date": READY, "alternative_considered": "Ahmedabad APMC, about INR 22.6/kg net",
            "data_kinds": ["simulated buyer demand", "simulated mandi prices 2026-11-23"]}


def market_finish(messages):
    ranked = last_tool_results(messages)[0]["ranked"]
    rows = [{"option": r["option"], "net_per_kg_low": r["net_per_kg"]["low"], "net_per_kg_expected": r["net_per_kg"]["expected"],
             "net_per_kg_high": r["net_per_kg"]["high"], "net_total_expected": r["net_total"]["expected"],
             "costs_per_kg": r["costs_per_kg"], "source": r["sources"][0]} for r in ranked]
    return report(summary=f"Best mandi: {rows[0]['option']}",
                  result={"ranked": rows, "best_option": rows[0]["option"], "stale_data": False})


def collective_finish(messages):
    split = last_tool_results(messages)[0]["members"]
    return report(summary="Pooled 5,000 kg", result={
        "pooled_lot_ids": [m["lot_id"] for m in split], "total_kg": sum(m["quantity_kg"] for m in split), "target_kg": 5000,
        "members": [{k: m[k] for k in ("farmer_id", "lot_id", "quantity_kg", "cost_share_inr", "expected_net_inr")} for m in split]})


def logistics_finish(messages):
    r = last_tool_results(messages)[0]
    return report(summary="One vehicle, three pickups", result={
        "vehicle_id": r["vehicle_id"], "pickup_order": r["pickup_order"], "total_km": r["total_km"],
        "total_cost_inr": r["total_cost_inr"], "cost_per_kg": r["cost_per_kg"], "pickup_date": READY})


def orchestrator_status(status, summary):
    return finish({"status": status, "summary": summary, "next_steps": [], "open_risks": []})


def build_script():
    return {
        "orchestrator": [
            call_tools(("update_plan", {"steps": ["compare markets", "find buyers", "pool if needed", "plan transport", "propose"]}),
                       ("delegate", {"tasks": [task("market_intelligence", "Rank mandis for 3,000 kg tomatoes"),
                                               task("buyer_matching", "Find buyers for lot-asha")]})),
            call_tools(("delegate", {"tasks": [task("collective_selling", "Fill 2,000 kg shortfall for the processor")]})),
            call_tools(("delegate", {"tasks": [task("logistics", "One vehicle for the pooled pickups to the processor")]})),
            call_tools(("request_approval", {"farmer_id": "farmer-asha", "proposal": proposal(3000, 70200)}),
                       ("request_approval", {"farmer_id": "farmer-ravi", "proposal": proposal(1200, 28080)}),
                       ("request_approval", {"farmer_id": "farmer-meena", "proposal": proposal(800, 18720)})),
            orchestrator_status("awaiting_approval", "Proposals sent to three farmers"),
            # resumed after approvals
            call_tools(("delegate", {"tasks": [task("transaction_and_trust", "Draft agreements for approved farmers")]})),
            orchestrator_status("executing", "Agreements drafted"),
            # resumed after the buyer withdraws
            call_tools(("replan", {"reason": "processor withdrew"})),
            orchestrator_status("in_progress", "Re-planning after the processor withdrew"),
        ],
        "market_intelligence": [
            call_tools(("compare_markets", {"farmer_id": "farmer-asha", "commodity_id": "tomato", "quantity_kg": 3000})),
            finish(market_finish),
        ],
        "buyer_matching": [
            call_tools(("search_buyer_requirements", {"commodity_id": "tomato", "earliest": "2026-11-28", "latest": "2026-12-02"})),
            call_tools(("match_lot_to_requirement", {"lot_id": "lot-asha", "requirement_id": "req-processor"})),
            finish(report(status="escalated", summary="Processor needs 5,000 kg; lot has 3,000 kg",
                          result={"requirement_id": "req-processor", "buyer_name": "Simulated Tomato Processor",
                                  "price_per_kg": 25.0, "required_kg": 5000, "lot_kg": 3000, "shortfall_kg": 2000},
                          escalation={"reason": "lot too small", "options": ["pool 2,000 kg from nearby farmers"]})),
        ],
        "collective_selling": [
            call_tools(("find_compatible_lots", {"anchor_lot_id": "lot-asha", "radius_km": 40, "min_grade": "B", "max_ready_gap_days": 2})),
            call_tools(("aggregate_lots", {"anchor_lot_id": "lot-asha", "candidate_lot_ids": ["lot-ravi", "lot-meena"], "target_kg": 5000})),
            call_tools(("pro_rata_split", {"members": [
                {"farmer_id": "farmer-asha", "lot_id": "lot-asha", "quantity_kg": 3000},
                {"farmer_id": "farmer-ravi", "lot_id": "lot-ravi", "quantity_kg": 1200},
                {"farmer_id": "farmer-meena", "lot_id": "lot-meena", "quantity_kg": 800}],
                "price_per_kg": 25.0, "shared_cost_inr": 3000.0})),
            finish(collective_finish),
        ],
        "logistics": [
            call_tools(("available_vehicles", {"pickup_date": READY, "min_capacity_kg": 5000})),
            call_tools(("route_pickups", {"vehicle_id": "veh-1", "lot_ids": ["lot-asha", "lot-ravi", "lot-meena"],
                                          "destination_lat": 22.31, "destination_lon": 73.18})),
            finish(logistics_finish),
        ],
        "transaction_and_trust": [
            call_tools(("create_agreement_draft", {"farmer_id": "farmer-asha", "counterparty": "Simulated Tomato Processor",
                                                   "quantity_kg": 3000, "price_per_kg": 25.0, "pickup_date": READY}),
                       ("create_agreement_draft", {"farmer_id": "farmer-ravi", "counterparty": "Simulated Tomato Processor",
                                                   "quantity_kg": 1200, "price_per_kg": 25.0, "pickup_date": READY}),
                       ("create_agreement_draft", {"farmer_id": "farmer-meena", "counterparty": "Simulated Tomato Processor",
                                                   "quantity_kg": 800, "price_per_kg": 25.0, "pickup_date": READY})),
            finish(lambda messages: report(summary="Agreements drafted", result={
                "agreement_ids": [r["agreement"]["id"] for r in last_tool_results(messages) if "agreement" in r],
                "discrepancies": [r["raw"] for r in last_tool_results(messages) if "raw" in r]})),
        ],
    }


@pytest.fixture
async def runtime():
    store = await seeded_store()
    model = ScriptedModelClient(build_script())
    return Runtime(ORCHESTRATOR_AGENT, SPECIALISTS, model, store)


async def test_tomato_scenario_multi_agent(runtime: Runtime):
    wf = await runtime.start("Sell 3,000 kg of tomatoes ready in five days", "farmer-asha")
    log = runtime.log.for_workflow(wf.id)

    # Goals were delegated to specialists, and the first two ran in the same delegation (parallel).
    tasks = [m for m in log if m.type == MessageType.TASK]
    assert [m.recipient for m in tasks] == ["market_intelligence", "buyer_matching", "collective_selling", "logistics"]

    # Market Intelligence ranked by net realisation from real tool output, not by headline price.
    market = next(m for m in log if m.sender == "market_intelligence" and m.type == MessageType.RESULT)
    ranked = market.content["result"]["ranked"]
    assert [r["net_per_kg_expected"] for r in ranked] == sorted((r["net_per_kg_expected"] for r in ranked), reverse=True)
    assert all("simulated" in r["source"] for r in ranked)

    # Buyer Matching escalated, and the Orchestrator brought in Collective Selling and Logistics.
    esc = next(m for m in log if m.type == MessageType.ESCALATION)
    assert esc.sender == "buyer_matching" and esc.content["result"]["shortfall_kg"] == 2000
    pooled = next(m for m in log if m.sender == "collective_selling" and m.type == MessageType.RESULT)
    assert pooled.content["result"]["total_kg"] == 5000
    route = next(m for m in log if m.sender == "logistics" and m.type == MessageType.RESULT)
    assert route.content["result"]["vehicle_id"] == "veh-1" and route.content["result"]["cost_per_kg"] > 0

    # Each specialist wrote only to its own section of the blackboard.
    assert set(wf.sections) == {"market_intelligence", "buyer_matching", "collective_selling", "logistics", "orchestrator"}

    # The workflow is waiting on three farmers; nothing is committed.
    assert wf.status == WorkflowStatus.AWAITING_APPROVAL
    assert len(wf.pending_approvals()) == 3
    assert runtime.store.agreements == {}
    assert len([n for n in runtime.store.notifications if "approval_id" in n]) == 3

    # Farmers approve; the Orchestrator resumes and Transaction and Trust drafts the agreements.
    for a in list(wf.pending_approvals()):
        await runtime.decide_approval(wf.id, a.id, approved=True)
    assert len(runtime.store.agreements) == 3
    assert all(a["approval_id"] for a in runtime.store.agreements.values())

    # The processor withdraws: the Orchestrator re-plans and earlier approvals no longer count.
    await runtime.handle_event(wf.id, {"source": "buyer", "summary": "Processor withdrew", "requirement_id": "req-processor"})
    assert all(a.status == ApprovalStatus.SUPERSEDED for a in wf.approvals.values())
    with pytest.raises(ApprovalRequiredError):
        wf.require_approved("farmer-asha")

    trace = "\n".join(runtime.log.trace(wf.id))
    assert "escalation" in trace and "approval_request" in trace and "Re-planning" in trace


async def test_agreement_tool_refuses_without_approval():
    """Guardrail: even if an agent tries, no agreement is drafted before the farmer approves."""
    store = await seeded_store()
    script = {
        "orchestrator": [
            call_tools(("delegate", {"tasks": [task("transaction_and_trust", "Draft an agreement now")]})),
            orchestrator_status("in_progress", "tried"),
        ],
        "transaction_and_trust": [
            call_tools(("create_agreement_draft", {"farmer_id": "farmer-asha", "counterparty": "X", "quantity_kg": 100,
                                                   "price_per_kg": 20.0, "pickup_date": READY})),
            finish(lambda messages: report(status="failed", summary="Refused: farmer has not approved",
                                           result={"agreement_ids": [], "discrepancies": []})),
        ],
    }
    rt = Runtime(ORCHESTRATOR_AGENT, SPECIALISTS, ScriptedModelClient(script), store)
    await rt.start("Sell 100 kg", "farmer-asha")
    assert store.agreements == {}
    tool_result = rt.model.calls  # both agents ran
    assert ("transaction_and_trust", 3) in tool_result


async def test_bad_output_gets_one_correction_then_fails_to_coordinator():
    store = await seeded_store()
    bad = finish({"status": "completed"})  # missing required fields
    script = {"orchestrator": [bad, bad]}
    rt = Runtime(ORCHESTRATOR_AGENT, SPECIALISTS, ScriptedModelClient(script), store)
    wf = await rt.start("Sell", "farmer-asha")
    assert wf.status == WorkflowStatus.ESCALATED_TO_COORDINATOR


def test_every_agent_is_distinct_and_schemas_are_strict():
    names = {a.name for a in SPECIALISTS.values()}
    assert names == {"crop_and_harvest", "market_intelligence", "buyer_matching", "collective_selling",
                     "logistics", "storage_decision", "transaction_and_trust"}
    prompts = {a.system_prompt for a in SPECIALISTS.values()} | {ORCHESTRATOR_AGENT.system_prompt}
    assert len(prompts) == 8  # eight separate agents, eight separate instructions
    for agent in [*SPECIALISTS.values(), ORCHESTRATOR_AGENT]:
        assert issubclass(agent.output_model, SpecialistReport) or agent is ORCHESTRATOR_AGENT
        assert agent.tools, agent.name
        for spec in [strict_schema(agent.output_model), *(t.to_api()["input_schema"] for t in agent.tools)]:
            _assert_strict(spec)


def _assert_strict(node):
    if isinstance(node, dict):
        assert "$ref" not in node
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
        for v in node.values():
            _assert_strict(v)
    elif isinstance(node, list):
        for v in node:
            _assert_strict(v)


async def test_storage_agent_tools_refuse_to_forecast_without_history():
    from app.agents.definitions.specialists import PriceTrendInput, price_trend
    from app.agents.runtime.context import ToolContext
    from app.agents.runtime.messages import MessageLog
    from app.agents.runtime.state import WorkflowState

    store = await seeded_store()
    ctx = ToolContext(agent="storage_decision", workflow=WorkflowState(goal="g", farmer_ids=[]), log=MessageLog(),
                      store=store, runtime=None)  # type: ignore[arg-type]
    out = await price_trend(ctx, PriceTrendInput(commodity_id="tomato", market_id="anand"))
    assert out["enough_history"] is False
