"""The seven specialist agents. Each has its own prompt, its own deterministic tools and its own output.

Tools here are thin wrappers over deterministic code: they read the store, compute, and return
numbers with their sources. The agents decide which tools to call and how to read the results.
"""

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.runtime.agent import AgentDefinition, SpecialistReport, ToolSpec
from app.agents.runtime.context import ToolContext
from app.domain.store import distance_km, grade_meets
from app.tools.net_realisation import CostBreakdown, PriceRange, SellingOption, rank_options

COMMON_RULES = """
Rules you must follow:
- Never invent a number. Every price, cost, quantity, distance or net figure in your answer must come from a tool result.
- Label every piece of data with its source and data kind (observed, historical, forecast, simulated, computed, reported).
- You do not commit anything on a farmer's behalf. You investigate and report; the Orchestrator proposes and the farmer decides.
- If the goal cannot be met as stated, set status to "escalated" and explain why and what would unblock it. Do not quietly return a weaker answer.
- Keep the summary short and concrete; put caveats in assumptions.
"""


# ---------------------------------------------------------------------------------------------
# Crop and Harvest Intelligence
# ---------------------------------------------------------------------------------------------
class FarmerIdInput(BaseModel):
    farmer_id: str


class RecordHarvestInput(BaseModel):
    farmer_id: str
    commodity_id: str
    quantity_kg: float = Field(gt=0)
    grade: Literal["A", "B", "C"]
    ready_date: date


class SurplusInput(BaseModel):
    commodity_id: str
    district: str
    ready_date: date
    window_days: int = Field(ge=0, le=14)


async def get_farmer_profile(ctx: ToolContext, a: FarmerIdInput) -> dict:
    f = ctx.store.farmers[a.farmer_id]
    lots = [vars(l) for l in ctx.store.lots.values() if l.farmer_id == f.id]
    return {"farmer": vars(f), "lots": lots, "data_kind": "simulated"}


async def record_harvest(ctx: ToolContext, a: RecordHarvestInput) -> dict:
    from app.domain.store import Lot

    existing = next((l for l in ctx.store.lots.values()
                     if l.farmer_id == a.farmer_id and l.commodity_id == a.commodity_id and l.status == "available"), None)
    lot = existing or Lot(ctx.store.new_id("lot"), a.farmer_id, a.commodity_id, a.quantity_kg, a.grade, a.ready_date)
    lot.quantity_kg, lot.grade, lot.ready_date = a.quantity_kg, a.grade, a.ready_date
    ctx.store.lots[lot.id] = lot
    return {"lot": vars(lot), "data_kind": "reported"}


async def detect_surplus(ctx: ToolContext, a: SurplusInput) -> dict:
    lo, hi = a.ready_date - timedelta(days=a.window_days), a.ready_date + timedelta(days=a.window_days)
    lots = [l for l in ctx.store.lots.values()
            if l.commodity_id == a.commodity_id and l.status == "available" and lo <= l.ready_date <= hi
            and ctx.store.farmers[l.farmer_id].district == a.district]
    total = sum(l.quantity_kg for l in lots)
    return {"district": a.district, "lots": len(lots), "farmers": len({l.farmer_id for l in lots}),
            "total_kg": total, "surplus_alert": len({l.farmer_id for l in lots}) >= 3,
            "rule": "alert when 3+ farmers in the district expect the same crop within the window",
            "data_kind": "computed"}


class HarvestResult(BaseModel):
    lot_id: str
    farmer_id: str
    commodity_id: str
    quantity_kg: float
    grade: str
    ready_date: date
    surplus_alert: bool
    nearby_supply_kg: float


class HarvestReport(SpecialistReport):
    result: HarvestResult | None


CROP_AND_HARVEST = AgentDefinition(
    name="crop_and_harvest",
    role="Structures harvest reports (crop, quantity, grade, ready date, location) and detects local surpluses early.",
    model="claude-haiku-5-5",
    effort="low",
    output_model=HarvestReport,
    tools=[
        ToolSpec("get_farmer_profile", "Farmer profile and their existing lots.", FarmerIdInput, get_farmer_profile),
        ToolSpec("record_harvest", "Create or update the farmer's available lot for a crop.", RecordHarvestInput, record_harvest),
        ToolSpec("detect_surplus", "Total expected supply of a crop in a district around a date.", SurplusInput, detect_surplus),
    ],
    system_prompt=f"""You are the Crop and Harvest Intelligence agent in KisanSetu, a market-access network for small farmers in India.
Your job: turn what a farmer reported into a clean harvest record, and warn early when many nearby farmers will harvest the same crop at the same time (a surplus that pushes prices down).
Use get_farmer_profile, record the harvest with record_harvest, then check detect_surplus for the farmer's district (window of 3 days).
{COMMON_RULES}""",
)


# ---------------------------------------------------------------------------------------------
# Market Intelligence
# ---------------------------------------------------------------------------------------------
class PricesInput(BaseModel):
    commodity_id: str
    market_ids: list[str] = Field(description="Empty list for all markets")


class CompareMarketsInput(BaseModel):
    farmer_id: str
    commodity_id: str
    quantity_kg: float = Field(gt=0)


async def get_prices(ctx: ToolContext, a: PricesInput) -> dict:
    rows = [p for p in ctx.store.prices
            if p.commodity_id == a.commodity_id and (not a.market_ids or p.market_id in a.market_ids)]
    return {"prices": [p.model_dump(mode="json", exclude={"raw"}) for p in rows]}


def _latest_by_market(prices, commodity_id, priorities: dict[str, int]):
    """Latest observation per market; on the same day, the source with the lower priority number wins."""
    latest = {}
    for p in prices:
        if p.commodity_id != commodity_id:
            continue
        cur = latest.get(p.market_id)
        rank = (p.date, -priorities.get(p.source, 100))
        if cur is None or rank > (cur.date, -priorities.get(cur.source, 100)):
            latest[p.market_id] = p
    return latest


async def compare_markets(ctx: ToolContext, a: CompareMarketsInput) -> dict:
    farmer = ctx.store.farmers[a.farmer_id]
    vehicles = list(ctx.store.vehicles.values())
    if not vehicles:
        raise ValueError("no vehicle rates available to estimate transport")
    rate_per_km = min(v.rate_per_km for v in vehicles)
    options, stale = [], []
    for market_id, p in _latest_by_market(ctx.store.prices, a.commodity_id, ctx.store.source_priorities).items():
        market = ctx.store.markets.get(market_id)
        if market is None:
            continue
        km = distance_km(farmer.lat, farmer.lon, market.lat, market.lon)
        transport = rate_per_km * km / a.quantity_kg
        low = p.min_price_per_kg if p.min_price_per_kg is not None else p.modal_price_per_kg
        high = p.max_price_per_kg if p.max_price_per_kg is not None else p.modal_price_per_kg
        options.append(SellingOption(
            name=market.name,
            price_per_kg=PriceRange(low=low, expected=p.modal_price_per_kg, high=high),
            costs_per_kg=CostBreakdown(transport=round(transport, 2), handling=market.handling_per_kg,
                                       market_fees=market.fees_per_kg),
            sources=[f"{p.source}, {p.data_kind}, {p.date.isoformat()}"],
            assumptions=[f"transport at INR {rate_per_km}/km for {km:.0f} km straight-line distance",
                         "no quality deduction data for this market"],
        ))
        if (ctx.store.today - p.date).days > 3:
            stale.append(market.name)
    ranked = rank_options(options, a.quantity_kg)
    return {"ranked": [r.model_dump(mode="json") for r in ranked], "stale_markets": stale, "data_kind": "computed"}


class RankedOption(BaseModel):
    option: str
    net_per_kg_low: float
    net_per_kg_expected: float
    net_per_kg_high: float
    net_total_expected: float
    costs_per_kg: float
    source: str


class MarketResult(BaseModel):
    ranked: list[RankedOption]
    best_option: str
    stale_data: bool


class MarketReport(SpecialistReport):
    result: MarketResult | None


MARKET_INTELLIGENCE = AgentDefinition(
    name="market_intelligence",
    role="Ranks mandi selling options by expected net realisation (price minus transport, handling, fees), with ranges and dated sources.",
    model="claude-sonnet-5-5",
    effort="medium",
    output_model=MarketReport,
    tools=[
        ToolSpec("get_prices", "Price observations for a commodity, with source, data kind and date.", PricesInput, get_prices),
        ToolSpec("compare_markets", "Rank markets by net realisation for a farmer's quantity.", CompareMarketsInput, compare_markets),
    ],
    system_prompt=f"""You are the Market Intelligence agent in KisanSetu.
Your job: tell the Orchestrator where this farmer would actually earn the most, ranked by expected net realisation, not headline price.
Call compare_markets for the farmer and quantity. Report the ranking with ranges, the best option, and whether any price data is stale or simulated.
Point out when a higher quoted price does not mean higher earnings.
{COMMON_RULES}""",
)


# ---------------------------------------------------------------------------------------------
# Buyer Matching
# ---------------------------------------------------------------------------------------------
class BuyerSearchInput(BaseModel):
    commodity_id: str
    earliest: date
    latest: date


class MatchInput(BaseModel):
    lot_id: str
    requirement_id: str


async def search_buyer_requirements(ctx: ToolContext, a: BuyerSearchInput) -> dict:
    reqs = [vars(r) for r in ctx.store.buyer_requirements.values()
            if r.active and r.commodity_id == a.commodity_id and r.window_end >= a.earliest and r.window_start <= a.latest]
    return {"requirements": reqs}


async def match_lot_to_requirement(ctx: ToolContext, a: MatchInput) -> dict:
    lot = ctx.store.lots[a.lot_id]
    req = ctx.store.buyer_requirements[a.requirement_id]
    farmer = ctx.store.farmers[lot.farmer_id]
    km = distance_km(farmer.lat, farmer.lon, req.delivery_lat, req.delivery_lon)
    return {
        "requirement_id": req.id, "buyer_name": req.buyer_name, "price_per_kg": req.price_per_kg,
        "required_kg": req.quantity_kg, "lot_kg": lot.quantity_kg,
        "shortfall_kg": max(0.0, req.quantity_kg - lot.quantity_kg),
        "grade_ok": grade_meets(lot.grade, req.min_grade),
        "window_ok": req.window_start <= lot.ready_date <= req.window_end,
        "delivery_distance_km": round(km, 1),
        "farmer_consented_to_share": farmer.consent_share_with_buyers,
        "data_kind": req.data_kind,
    }


class BuyerResult(BaseModel):
    requirement_id: str | None
    buyer_name: str | None
    price_per_kg: float | None
    required_kg: float
    lot_kg: float
    shortfall_kg: float


class BuyerReport(SpecialistReport):
    result: BuyerResult | None


BUYER_MATCHING = AgentDefinition(
    name="buyer_matching",
    role="Finds buyer demand (processors, wholesalers, institutions) that fits the lot's crop, grade, quantity and delivery window.",
    model="claude-sonnet-5-5",
    effort="medium",
    output_model=BuyerReport,
    tools=[
        ToolSpec("search_buyer_requirements", "Active buyer requirements for a crop in a date window.", BuyerSearchInput, search_buyer_requirements),
        ToolSpec("match_lot_to_requirement", "Check a lot against a requirement: quantity, grade, window, distance, consent.", MatchInput, match_lot_to_requirement),
    ],
    system_prompt=f"""You are the Buyer Matching agent in KisanSetu.
Your job: find buyer demand that fits the farmer's lot. Search requirements in the delivery window, check the best ones with match_lot_to_requirement.
If the best buyer needs more than the lot holds, escalate with the shortfall and suggest pooling with nearby farmers.
Never share a farmer's identity or location with a buyer unless farmer_consented_to_share is true; if it is false, escalate.
{COMMON_RULES}""",
)


# ---------------------------------------------------------------------------------------------
# Collective Selling
# ---------------------------------------------------------------------------------------------
class CompatibleLotsInput(BaseModel):
    anchor_lot_id: str
    radius_km: float = Field(gt=0, le=200)
    min_grade: Literal["A", "B", "C"]
    max_ready_gap_days: int = Field(ge=0, le=7)


class AggregateInput(BaseModel):
    anchor_lot_id: str
    candidate_lot_ids: list[str]
    target_kg: float = Field(gt=0)


class SplitMember(BaseModel):
    farmer_id: str
    lot_id: str
    quantity_kg: float = Field(gt=0)


class ProRataInput(BaseModel):
    members: list[SplitMember]
    price_per_kg: float = Field(ge=0)
    shared_cost_inr: float = Field(ge=0)


async def find_compatible_lots(ctx: ToolContext, a: CompatibleLotsInput) -> dict:
    anchor = ctx.store.lots[a.anchor_lot_id]
    af = ctx.store.farmers[anchor.farmer_id]
    out = []
    for lot in ctx.store.lots.values():
        if lot.id == anchor.id or lot.status != "available" or lot.commodity_id != anchor.commodity_id:
            continue
        f = ctx.store.farmers[lot.farmer_id]
        km = distance_km(af.lat, af.lon, f.lat, f.lon)
        if km <= a.radius_km and grade_meets(lot.grade, a.min_grade) and abs((lot.ready_date - anchor.ready_date).days) <= a.max_ready_gap_days:
            out.append({"lot_id": lot.id, "farmer_id": f.id, "quantity_kg": lot.quantity_kg, "grade": lot.grade,
                        "ready_date": lot.ready_date.isoformat(), "distance_km": round(km, 1)})
    return {"compatible_lots": sorted(out, key=lambda x: x["distance_km"]), "data_kind": "simulated"}


async def aggregate_lots(ctx: ToolContext, a: AggregateInput) -> dict:
    """Greedy nearest-first fill. Production replaces this with the OR-Tools CP-SAT model."""
    anchor = ctx.store.lots[a.anchor_lot_id]
    af = ctx.store.farmers[anchor.farmer_id]
    selected = [{"lot_id": anchor.id, "farmer_id": anchor.farmer_id, "quantity_kg": anchor.quantity_kg}]
    total = anchor.quantity_kg
    cands = sorted((ctx.store.lots[i] for i in a.candidate_lot_ids),
                   key=lambda l: distance_km(af.lat, af.lon, ctx.store.farmers[l.farmer_id].lat, ctx.store.farmers[l.farmer_id].lon))
    for lot in cands:
        if total >= a.target_kg:
            break
        take = min(lot.quantity_kg, a.target_kg - total)
        selected.append({"lot_id": lot.id, "farmer_id": lot.farmer_id, "quantity_kg": take})
        total += take
    return {"selected": selected, "total_kg": total, "target_kg": a.target_kg,
            "shortfall_kg": max(0.0, a.target_kg - total), "method": "greedy nearest-first", "data_kind": "computed"}


async def pro_rata_split(ctx: ToolContext, a: ProRataInput) -> dict:
    total = sum(m.quantity_kg for m in a.members)
    rows = []
    for m in a.members:
        share = m.quantity_kg / total
        gross = m.quantity_kg * a.price_per_kg
        cost = a.shared_cost_inr * share
        rows.append({"farmer_id": m.farmer_id, "lot_id": m.lot_id, "quantity_kg": m.quantity_kg,
                     "gross_inr": round(gross, 2), "cost_share_inr": round(cost, 2), "expected_net_inr": round(gross - cost, 2)})
    return {"members": rows, "rule": "proceeds by accepted weight; shared costs by weight carried", "data_kind": "computed"}


class PoolMember(BaseModel):
    farmer_id: str
    lot_id: str
    quantity_kg: float
    cost_share_inr: float
    expected_net_inr: float


class CollectiveResult(BaseModel):
    pooled_lot_ids: list[str]
    total_kg: float
    target_kg: float
    members: list[PoolMember]


class CollectiveReport(SpecialistReport):
    result: CollectiveResult | None


COLLECTIVE_SELLING = AgentDefinition(
    name="collective_selling",
    role="Pools compatible lots from nearby farmers into quantities larger buyers will take, and splits proceeds and costs fairly.",
    model="claude-opus-5-5",
    effort="medium",
    output_model=CollectiveReport,
    tools=[
        ToolSpec("find_compatible_lots", "Nearby available lots of the same crop with an acceptable grade and ready date.", CompatibleLotsInput, find_compatible_lots),
        ToolSpec("aggregate_lots", "Fill a target quantity from candidate lots.", AggregateInput, aggregate_lots),
        ToolSpec("pro_rata_split", "Each member's gross, cost share and expected net.", ProRataInput, pro_rata_split),
    ],
    system_prompt=f"""You are the Collective Selling agent in KisanSetu.
Your job: help small farmers reach buyers they couldn't supply alone, fairly.
Find compatible lots near the anchor lot (start with a 40 km radius), fill the target with aggregate_lots, then compute each member's share with pro_rata_split.
Fairness rules: each lot keeps its own weight and grade; proceeds follow accepted weight; shared costs follow weight carried; one farmer's shortfall is never passed to others.
If the target can't be filled, escalate with the shortfall.
{COMMON_RULES}""",
)


# ---------------------------------------------------------------------------------------------
# Logistics
# ---------------------------------------------------------------------------------------------
class VehiclesInput(BaseModel):
    pickup_date: date
    min_capacity_kg: float = Field(gt=0)


class RouteInput(BaseModel):
    vehicle_id: str
    lot_ids: list[str]
    destination_lat: float
    destination_lon: float


async def available_vehicles(ctx: ToolContext, a: VehiclesInput) -> dict:
    vs = [vars(v) for v in ctx.store.vehicles.values() if a.pickup_date in v.available_dates and v.capacity_kg >= a.min_capacity_kg]
    return {"vehicles": vs}


async def route_pickups(ctx: ToolContext, a: RouteInput) -> dict:
    """Nearest-neighbour route. Production uses the OR-Tools routing solver on OSRM road distances."""
    v = ctx.store.vehicles[a.vehicle_id]
    lots = [ctx.store.lots[i] for i in a.lot_ids]
    load = sum(l.quantity_kg for l in lots)
    if load > v.capacity_kg:
        raise ValueError(f"load {load} kg exceeds vehicle capacity {v.capacity_kg} kg")
    pos, order, km = (v.base_lat, v.base_lon), [], 0.0
    remaining = lots[:]
    while remaining:
        nxt = min(remaining, key=lambda l: distance_km(*pos, ctx.store.farmers[l.farmer_id].lat, ctx.store.farmers[l.farmer_id].lon))
        f = ctx.store.farmers[nxt.farmer_id]
        km += distance_km(*pos, f.lat, f.lon)
        pos = (f.lat, f.lon)
        order.append(nxt.id)
        remaining.remove(nxt)
    km += distance_km(*pos, a.destination_lat, a.destination_lon)
    cost = km * v.rate_per_km
    return {"vehicle_id": v.id, "pickup_order": order, "total_km": round(km, 1), "total_cost_inr": round(cost, 2),
            "load_kg": load, "cost_per_kg": round(cost / load, 2), "method": "nearest-neighbour, straight-line km",
            "data_kind": v.data_kind}


class LogisticsResult(BaseModel):
    vehicle_id: str | None
    pickup_order: list[str]
    total_km: float
    total_cost_inr: float
    cost_per_kg: float
    pickup_date: date | None


class LogisticsReport(SpecialistReport):
    result: LogisticsResult | None


LOGISTICS = AgentDefinition(
    name="logistics",
    role="Finds a vehicle and plans pickups and delivery at the lowest sensible cost per kg, including shared loads.",
    model="claude-sonnet-5-5",
    effort="medium",
    output_model=LogisticsReport,
    tools=[
        ToolSpec("available_vehicles", "Vehicles free on a date with enough capacity.", VehiclesInput, available_vehicles),
        ToolSpec("route_pickups", "Pickup order, distance and cost for a vehicle, lots and destination.", RouteInput, route_pickups),
    ],
    system_prompt=f"""You are the Logistics agent in KisanSetu.
Your job: get the produce from the farms to the buyer or market at the lowest sensible cost per kg.
Find vehicles for the pickup date with enough capacity, then route the pickups. If no vehicle fits, escalate with options (another date, splitting the load).
{COMMON_RULES}""",
)


# ---------------------------------------------------------------------------------------------
# Storage Decision
# ---------------------------------------------------------------------------------------------
class StorageOptionsInput(BaseModel):
    commodity_id: str
    farmer_id: str


class PriceTrendInput(BaseModel):
    commodity_id: str
    market_id: str


class HoldVsSellInput(BaseModel):
    quantity_kg: float = Field(gt=0)
    sell_now_net_per_kg: float
    storage_id: str
    days: int = Field(ge=1, le=60)
    price_change_pct_low: float
    price_change_pct_high: float


async def storage_options(ctx: ToolContext, a: StorageOptionsInput) -> dict:
    f = ctx.store.farmers[a.farmer_id]
    out = [{**vars(s), "distance_km": round(distance_km(f.lat, f.lon, s.lat, s.lon), 1)}
           for s in ctx.store.storage.values() if s.commodity_id == a.commodity_id]
    return {"storage": out}


async def price_trend(ctx: ToolContext, a: PriceTrendInput) -> dict:
    rows = sorted((p for p in ctx.store.prices if p.commodity_id == a.commodity_id and p.market_id == a.market_id), key=lambda p: p.date)
    if len(rows) < 10:
        return {"enough_history": False, "observations": len(rows),
                "note": "fewer than 10 observations: no trend can be estimated; do not recommend storage on a forecast"}
    first, last = rows[0], rows[-1]
    change = float((last.modal_price_per_kg - first.modal_price_per_kg) / first.modal_price_per_kg * 100)
    return {"enough_history": True, "observations": len(rows), "change_pct_over_period": round(change, 1),
            "from": first.date.isoformat(), "to": last.date.isoformat(), "data_kind": "historical"}


async def hold_vs_sell(ctx: ToolContext, a: HoldVsSellInput) -> dict:
    s = ctx.store.storage[a.storage_id]
    kept = a.quantity_kg * (1 - s.spoilage_pct_per_day / 100) ** a.days
    cost = a.quantity_kg * s.cost_per_kg_per_day * a.days
    sell_now = a.quantity_kg * a.sell_now_net_per_kg
    low = kept * a.sell_now_net_per_kg * (1 + a.price_change_pct_low / 100) - cost
    high = kept * a.sell_now_net_per_kg * (1 + a.price_change_pct_high / 100) - cost
    return {"sell_now_net_inr": round(sell_now, 2), "store_net_inr_low": round(low, 2), "store_net_inr_high": round(high, 2),
            "kg_left_after_spoilage": round(kept, 1), "storage_cost_inr": round(cost, 2), "data_kind": "computed"}


class StorageResult(BaseModel):
    recommendation: Literal["sell_now", "store", "insufficient_data"]
    days: int | None
    sell_now_net_inr: float | None
    store_net_inr_low: float | None
    store_net_inr_high: float | None


class StorageReport(SpecialistReport):
    result: StorageResult | None


STORAGE_DECISION = AgentDefinition(
    name="storage_decision",
    role="Compares selling now with storing and selling later, honest about spoilage, storage cost and price uncertainty.",
    model="claude-opus-5-5",
    effort="medium",
    output_model=StorageReport,
    tools=[
        ToolSpec("storage_options", "Storage facilities for a crop near the farmer.", StorageOptionsInput, storage_options),
        ToolSpec("price_trend", "Historical price change for a crop at a market, if there is enough history.", PriceTrendInput, price_trend),
        ToolSpec("hold_vs_sell", "Net from selling now versus storing for N days under a price-change range.", HoldVsSellInput, hold_vs_sell),
    ],
    system_prompt=f"""You are the Storage Decision agent in KisanSetu.
Your job: decide whether the farmer should sell now or store and sell later.
Check storage options and price history. Only use price-change scenarios that come from price_trend; if there isn't enough history, recommend selling now with recommendation "insufficient_data" rather than guessing.
Recommend storing only if even the low scenario beats selling now.
{COMMON_RULES}""",
)


# ---------------------------------------------------------------------------------------------
# Transaction and Trust
# ---------------------------------------------------------------------------------------------
class AgreementInput(BaseModel):
    farmer_id: str
    counterparty: str
    quantity_kg: float = Field(gt=0)
    price_per_kg: float = Field(ge=0)
    pickup_date: date


class DeliveryInput(BaseModel):
    agreement_id: str
    delivered_kg: float = Field(ge=0)
    accepted_kg: float = Field(ge=0)
    accepted_grade: Literal["A", "B", "C"]


async def create_agreement_draft(ctx: ToolContext, a: AgreementInput) -> dict:
    approval = ctx.workflow.require_approved(a.farmer_id)  # guardrail: no approval, no agreement
    agreement_id = ctx.store.new_id("agr")
    ctx.store.agreements[agreement_id] = {**a.model_dump(mode="json"), "id": agreement_id, "approval_id": approval.id,
                                          "workflow_id": ctx.workflow.id, "status": "draft"}
    return {"agreement": ctx.store.agreements[agreement_id]}


async def record_delivery(ctx: ToolContext, a: DeliveryInput) -> dict:
    agr = ctx.store.agreements[a.agreement_id]
    rec = {**a.model_dump(mode="json"), "agreed_kg": agr["quantity_kg"],
           "shortfall_kg": round(agr["quantity_kg"] - a.delivered_kg, 2),
           "rejected_kg": round(a.delivered_kg - a.accepted_kg, 2),
           "amount_due_inr": round(a.accepted_kg * agr["price_per_kg"], 2)}
    ctx.store.deliveries[a.agreement_id] = rec
    agr["status"] = "delivered"
    return {"delivery": rec, "data_kind": "reported"}


class TransactionResult(BaseModel):
    agreement_ids: list[str]
    discrepancies: list[str]


class TransactionReport(SpecialistReport):
    result: TransactionResult | None


TRANSACTION_AND_TRUST = AgentDefinition(
    name="transaction_and_trust",
    role="Drafts agreements for approved proposals and records dispatch, delivery, quantity discrepancies and payment status.",
    model="claude-sonnet-5-5",
    effort="low",
    output_model=TransactionReport,
    tools=[
        ToolSpec("create_agreement_draft", "Draft an agreement for a farmer whose proposal is approved. Fails without approval.", AgreementInput, create_agreement_draft),
        ToolSpec("record_delivery", "Record delivered and accepted quantities against an agreement.", DeliveryInput, record_delivery),
    ],
    system_prompt=f"""You are the Transaction and Trust agent in KisanSetu.
Your job: make every agreed term, delivery and payment traceable. Draft agreements only for farmers whose proposal is approved; if the tool refuses, report that, never work around it.
Record every discrepancy between agreed, delivered and accepted quantities.
{COMMON_RULES}""",
)


SPECIALISTS: dict[str, AgentDefinition] = {a.name: a for a in [
    CROP_AND_HARVEST, MARKET_INTELLIGENCE, BUYER_MATCHING, COLLECTIVE_SELLING,
    LOGISTICS, STORAGE_DECISION, TRANSACTION_AND_TRUST,
]}
