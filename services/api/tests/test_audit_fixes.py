"""Regression tests for the 2026-11-24 audit (docs/AUDIT-2026-11-24.md). One test per loophole closed."""

import asyncio
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.adapters.market_data.aliases import AliasResolver
from app.adapters.market_data.connectors import get_connector
from app.adapters.market_data.connectors.http import check_public_host
from app.adapters.market_data.engine import run_source
from app.adapters.market_data.models import SourceConfig
from app.adapters.market_data.secrets import DictSecretReader
from app.agents.definitions import specialists as sp
from app.agents.definitions.orchestrator import (
    ORCHESTRATOR_AGENT,
    ApprovalInput,
    Proposal,
    ProposalCheckError,
    ReasonInput,
    replan,
    request_approval,
)
from app.agents.definitions.specialists import SPECIALISTS
from app.agents.runtime.context import ToolContext
from app.agents.runtime.messages import MessageLog
from app.agents.runtime.model import ModelResponse, ScriptedModelClient, call_tools, finish
from app.agents.runtime.orchestrator import Runtime
from app.agents.runtime.state import ApprovalRequiredError, WorkflowState, WorkflowStatus
from app.domain.seed import seeded_store
from tests.test_agents import orchestrator_status, proposal, task

ALIASES = AliasResolver(commodities={"Tomato": "tomato"}, markets={"Anand": "anand"})


async def make_ctx(agent="orchestrator"):
    store = await seeded_store()
    wf = WorkflowState(goal="g", farmer_ids=["farmer-asha"])
    rt = Runtime(ORCHESTRATOR_AGENT, SPECIALISTS, ScriptedModelClient({}), store)
    rt.workflows[wf.id] = wf
    return ToolContext(agent=agent, workflow=wf, log=MessageLog(), store=store, runtime=rt), rt


async def approve(ctx, farmer_id, p):
    await request_approval(ctx, ApprovalInput(farmer_id=farmer_id, proposal=Proposal.model_validate(p)))
    approval = ctx.workflow.latest_approval(farmer_id)
    ctx.workflow.decide(approval.id, True, decided_by=farmer_id)
    return approval


# --- proposals can't carry invented or inconsistent numbers -------------------------------------
@pytest.mark.parametrize("override, message", [
    ({"expected_price_per_kg": 30.0, "net_per_kg_low": 28.4, "net_per_kg_expected": 28.4, "net_per_kg_high": 28.4,
      "expected_net_total_inr": 85200}, "does not match"),
    ({"net_per_kg_expected": 24.4, "net_per_kg_high": 24.4, "expected_net_total_inr": 73200}, "price - transport"),
    ({"quantity_kg": 3500, "expected_net_total_inr": 81900}, "exceeds"),
    ({"expected_net_total_inr": 99999}, "net total"),
    ({"price_basis": "buyer:req-imaginary"}, "not an active requirement"),
    ({"price_basis": "market:surat", "expected_price_per_kg": 35.0, "net_per_kg_low": 33.4, "net_per_kg_expected": 33.4,
      "net_per_kg_high": 33.4, "expected_net_total_inr": 100200}, "outside the observed range"),
    ({"lot_id": "lot-ravi"}, "does not belong"),
    ({"sell_to": "Someone Else"}, "does not match the buyer"),
])
async def test_proposal_checks_reject_bad_numbers(override, message):
    ctx, _ = await make_ctx()
    with pytest.raises(ProposalCheckError, match=message):
        await request_approval(ctx, ApprovalInput(farmer_id="farmer-asha",
                                                  proposal=Proposal.model_validate(proposal(3000, 70200, **override))))
    assert ctx.workflow.approvals == {}


async def test_proposal_on_observed_market_price_is_accepted():
    ctx, _ = await make_ctx()
    p = proposal(3000, 3000 * 25.0, price_basis="market:surat", sell_to="Surat APMC", expected_price_per_kg=27.0,
                 transport_cost_per_kg=1.0, other_costs_per_kg=1.0, net_per_kg_low=25.0, net_per_kg_expected=25.0,
                 net_per_kg_high=25.0)
    await request_approval(ctx, ApprovalInput(farmer_id="farmer-asha", proposal=Proposal.model_validate(p)))
    assert len(ctx.workflow.pending_approvals()) == 1


# --- agreements = exactly what was approved -------------------------------------------------------
async def test_agreement_copies_approved_terms_once_and_reserves_lot():
    ctx, _ = await make_ctx("transaction_and_trust")
    await approve(ctx, "farmer-asha", proposal(2000, 46800))
    first = await sp.create_agreement_draft(ctx, sp.AgreementInput(farmer_id="farmer-asha"))
    second = await sp.create_agreement_draft(ctx, sp.AgreementInput(farmer_id="farmer-asha"))
    agr = first["agreement"]
    assert (agr["quantity_kg"], agr["price_per_kg"], agr["counterparty"]) == (2000, 25.0, "Simulated Tomato Processor")
    assert second["agreement"]["id"] == agr["id"] and len(ctx.store.agreements) == 1
    assert ctx.store.lots["lot-asha"].available_kg == 1000


async def test_agreement_refused_without_consent():
    ctx, _ = await make_ctx("transaction_and_trust")
    ctx.store.farmers["farmer-asha"].consent_share_with_buyers = False
    await approve(ctx, "farmer-asha", proposal(3000, 70200))
    with pytest.raises(PermissionError, match="consented"):
        await sp.create_agreement_draft(ctx, sp.AgreementInput(farmer_id="farmer-asha"))


async def test_replan_voids_drafts_and_releases_lot():
    ctx, _ = await make_ctx()
    await approve(ctx, "farmer-asha", proposal(3000, 70200))
    await sp.create_agreement_draft(ctx, sp.AgreementInput(farmer_id="farmer-asha"))
    assert ctx.store.lots["lot-asha"].available_kg == 0
    out = await replan(ctx, ReasonInput(reason="buyer withdrew"))
    assert len(out["voided_draft_agreements"]) == 1
    assert ctx.store.lots["lot-asha"].available_kg == 3000
    assert all(a["status"] == "voided" for a in ctx.store.agreements.values())


async def test_harvest_cannot_shrink_below_committed():
    ctx, _ = await make_ctx("crop_and_harvest")
    await approve(ctx, "farmer-asha", proposal(3000, 70200))
    await sp.create_agreement_draft(ctx, sp.AgreementInput(farmer_id="farmer-asha"))
    with pytest.raises(ValueError, match="already committed"):
        await sp.record_harvest(ctx, sp.RecordHarvestInput(farmer_id="farmer-asha", commodity_id="tomato", quantity_kg=2000,
                                                           grade="A", ready_date=ctx.store.today))


# --- pooling tools validate their inputs ----------------------------------------------------------
async def test_pooling_rejects_inflated_or_foreign_lots():
    ctx, _ = await make_ctx("collective_selling")
    with pytest.raises(ValueError, match="exceeds"):
        await sp.pro_rata_split(ctx, sp.ProRataInput(members=[sp.SplitMember(farmer_id="farmer-ravi", lot_id="lot-ravi",
                                                                             quantity_kg=5000)], price_per_kg=25, shared_cost_inr=0))
    with pytest.raises(ValueError, match="does not belong"):
        await sp.pro_rata_split(ctx, sp.ProRataInput(members=[sp.SplitMember(farmer_id="farmer-asha", lot_id="lot-ravi",
                                                                             quantity_kg=10)], price_per_kg=25, shared_cost_inr=0))
    with pytest.raises(ValueError, match="invalid candidate"):
        await sp.aggregate_lots(ctx, sp.AggregateInput(anchor_lot_id="lot-asha", candidate_lot_ids=["lot-nope"], target_kg=5000))


# --- storage advice can't rest on agent-supplied forecasts ----------------------------------------
async def test_hold_vs_sell_uses_history_only():
    ctx, _ = await make_ctx("storage_decision")
    args = sp.HoldVsSellInput(quantity_kg=1000, sell_now_net_per_kg=20, storage_id="cold-anand", market_id="anand",
                              commodity_id="tomato", days=7)
    assert (await sp.hold_vs_sell(ctx, args))["enough_history"] is False

    base = ctx.store.prices[0]
    for i in range(40):  # 40 days of simulated history, rising 1% a day
        ctx.store.prices.append(base.model_copy(update={"date": base.date - timedelta(days=40 - i),
                                                        "modal_price_per_kg": Decimal(15) * Decimal("1.01") ** i,
                                                        "min_price_per_kg": None, "max_price_per_kg": None}))
    out = await sp.hold_vs_sell(ctx, args)
    assert out["enough_history"] is True and out["price_change_pct_low"] > 0
    assert "price_change_pct_low" not in sp.HoldVsSellInput.model_fields  # the agent can't supply scenarios


# --- approvals: who may decide, and resuming once --------------------------------------------------
async def test_only_the_farmer_or_their_coordinator_with_proof_can_decide():
    ctx, _ = await make_ctx()
    await request_approval(ctx, ApprovalInput(farmer_id="farmer-asha", proposal=Proposal.model_validate(proposal(3000, 70200))))
    a = ctx.workflow.latest_approval("farmer-asha")
    with pytest.raises(ApprovalRequiredError, match="may not decide"):
        ctx.workflow.decide(a.id, True, decided_by="farmer-ravi")
    with pytest.raises(ApprovalRequiredError, match="may not decide"):
        ctx.workflow.decide(a.id, True, decided_by="coordinator:fpo-other", coordinator_for="fpo-anand")
    with pytest.raises(ApprovalRequiredError, match="confirmation_ref"):
        ctx.workflow.decide(a.id, True, decided_by="coordinator:fpo-anand", coordinator_for="fpo-anand")
    ctx.workflow.decide(a.id, True, decided_by="coordinator:fpo-anand", coordinator_for="fpo-anand",
                        confirmation_ref="ivr-call-123")
    assert a.decided_by == "coordinator:fpo-anand" and a.confirmation_ref == "ivr-call-123"


async def test_simultaneous_decisions_resume_orchestrator_once():
    store = await seeded_store()
    script = {"orchestrator": [
        call_tools(("request_approval", {"farmer_id": "farmer-asha", "proposal": proposal(3000, 70200)}),
                   ("request_approval", {"farmer_id": "farmer-ravi", "proposal": proposal(1200, 28080, "lot-ravi")})),
        orchestrator_status("awaiting_approval", "sent"),
        orchestrator_status("executing", "resumed once"),
    ]}
    model = ScriptedModelClient(script)
    rt = Runtime(ORCHESTRATOR_AGENT, SPECIALISTS, model, store)
    wf = await rt.start("Sell", "farmer-asha")
    approvals = list(wf.pending_approvals())
    await asyncio.gather(*(rt.decide_approval(wf.id, a.id, True, decided_by=a.farmer_id) for a in approvals))
    assert [c[0] for c in model.calls].count("orchestrator") == 3  # start (2 turns) + one resume


# --- runaway protection ----------------------------------------------------------------------------
async def test_delegation_cap_and_token_budget():
    store = await seeded_store()
    eight = [task("market_intelligence", f"g{i}") for i in range(8)]
    script = {"orchestrator": [call_tools(("delegate", {"tasks": eight})), orchestrator_status("in_progress", "x")]}
    rt = Runtime(ORCHESTRATOR_AGENT, SPECIALISTS, ScriptedModelClient(script), store)
    wf = await rt.start("Sell", "farmer-asha")
    assert wf.tasks == {}  # rejected as a whole; the error went back to the Orchestrator

    def expensive(agent, messages):
        r = finish({"status": "in_progress", "summary": "s", "next_steps": [], "open_risks": []})(agent, messages)
        return ModelResponse(r.stop_reason, r.text, r.tool_uses, r.assistant_content, usage={"input_tokens": 10, "output_tokens": 10})

    rt2 = Runtime(ORCHESTRATOR_AGENT, SPECIALISTS, ScriptedModelClient({"orchestrator": [expensive]}), store, token_budget=15)
    wf2 = await rt2.start("Sell", "farmer-asha")
    await rt2.handle_event(wf2.id, {"summary": "ping"})
    assert wf2.status == WorkflowStatus.ESCALATED_TO_COORDINATOR


async def test_start_rejects_unknown_farmer():
    store = await seeded_store()
    rt = Runtime(ORCHESTRATOR_AGENT, SPECIALISTS, ScriptedModelClient({}), store)
    with pytest.raises(ValueError, match="unknown farmer"):
        await rt.start("Sell", "farmer-ghost")


# --- price sources -------------------------------------------------------------------------------
def base_config(**overrides):
    data = {
        "name": "src", "connector": "http_json", "data_kind": "observed",
        "request": {"url": "https://prices.example.test/r", "records_path": "$.records",
                    "auth": {"type": "query_param", "name": "api-key", "secret": "KEY"}},
        "mapping": {"market": {"from": "m"}, "commodity": {"from": "c"}, "date": {"from": "d", "parse": "date"},
                    "modal_price": {"from": "p", "parse": "number", "unit": "INR_per_quintal"}},
    }
    data.update(overrides)
    return SourceConfig.model_validate(data)


def test_price_fields_need_an_explicit_unit():
    with pytest.raises(ValidationError, match="explicit unit"):
        base_config(mapping={"market": {"from": "m"}, "commodity": {"from": "c"}, "date": {"from": "d", "parse": "date"},
                             "modal_price": {"from": "p", "parse": "number"}})


async def test_sanity_limit_and_modal_range():
    rows = [{"m": "Anand", "c": "Tomato", "d": "2026-11-23", "p": "250000"},  # 2,500 INR/kg: unit mistake
            {"m": "Anand", "c": "Tomato", "d": "2026-11-23", "p": "2000", "lo": "2100", "hi": "2500"}]
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"records": rows}))
    cfg = base_config()
    cfg.mapping["min_price"] = cfg.mapping["modal_price"].model_copy(update={"from_": "lo"})
    cfg.mapping["max_price"] = cfg.mapping["modal_price"].model_copy(update={"from_": "hi"})
    result = await run_source(cfg, aliases=ALIASES, secrets=DictSecretReader({"KEY": "k"}), http_transport=transport)
    reasons = [r.reason for r in result.rejected]
    assert any("sanity limit" in r for r in reasons) and any("outside the min-max" in r for r in reasons)
    assert result.observations == []


async def test_http_errors_never_leak_the_api_key():
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    result = await run_source(base_config(), aliases=ALIASES, secrets=DictSecretReader({"KEY": "TOP-SECRET-KEY"}),
                              http_transport=transport)
    assert result.error and "TOP-SECRET-KEY" not in result.error and "***" in result.error


async def test_redirects_are_refused():
    transport = httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": "http://169.254.169.254/"}))
    result = await run_source(base_config(), aliases=ALIASES, secrets=DictSecretReader({"KEY": "k"}), http_transport=transport)
    assert result.error and "redirect" in result.error


@pytest.mark.parametrize("url", ["http://localhost/x", "http://127.0.0.1/x", "http://169.254.169.254/latest",
                                 "http://10.0.0.5/x", "http://db.internal/x", "http://[::1]/x"])
async def test_internal_addresses_blocked(url):
    with pytest.raises(Exception, match="not allowed"):
        await check_public_host(url)


async def test_file_source_cannot_escape_its_folder(tmp_path):
    outside = tmp_path / "secrets.csv"
    outside.write_text("a,b\n1,2\n")
    cfg = SourceConfig.model_validate({
        "name": "file-src", "connector": "file", "data_kind": "simulated", "request": {"path": str(outside)},
        "mapping": {"market": {"from": "a"}, "commodity": {"from": "b"}, "date": {"from": "a"},
                    "modal_price": {"from": "b", "parse": "number", "unit": "INR_per_kg"}},
    })
    result = await run_source(cfg, aliases=ALIASES)
    assert result.error and "must live under" in result.error


@pytest.mark.parametrize("query", ["SELECT * FROM t; DROP TABLE t", "SELECT * INTO backup FROM t",
                                   "SELECT 1 -- comment", "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x"])
def test_sql_must_be_a_single_read_only_select(query):
    cfg = SourceConfig.model_validate({
        "name": "sql-src", "connector": "sql", "data_kind": "observed", "request": {"dsn_secret": "D", "query": query},
        "mapping": {"market": {"from": "a"}, "commodity": {"from": "b"}, "date": {"from": "d"},
                    "modal_price": {"from": "c", "parse": "number", "unit": "INR_per_kg"}},
    })
    with pytest.raises(Exception, match="read-only"):
        get_connector("sql").validate_config(cfg)


def test_admin_endpoints_need_the_admin_key(monkeypatch):
    from app.main import app

    client = TestClient(app)
    monkeypatch.delenv("KISANSETU_ADMIN_KEY", raising=False)
    assert client.get("/admin/market-sources/connectors").status_code == 503
    monkeypatch.setenv("KISANSETU_ADMIN_KEY", "admin-secret")
    assert client.get("/admin/market-sources/connectors").status_code == 401
    assert client.get("/admin/market-sources/connectors", headers={"X-Admin-Key": "wrong"}).status_code == 401
    ok = client.get("/admin/market-sources/connectors", headers={"X-Admin-Key": "admin-secret"})
    assert ok.status_code == 200 and "http_json" in ok.json()
    assert client.get("/health").status_code == 200
