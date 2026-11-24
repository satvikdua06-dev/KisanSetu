"""Simulated seed data for the Gujarat tomato scenario. Not real farmers, buyers or vehicles."""

from datetime import date, timedelta
from pathlib import Path

from app.adapters.market_data.aliases import AliasResolver
from app.adapters.market_data.engine import load_source_file, run_source
from app.domain.store import (
    BuyerRequirement,
    Farmer,
    Lot,
    Market,
    StorageOption,
    Store,
    Vehicle,
)

API_ROOT = Path(__file__).resolve().parents[2]

ALIASES = AliasResolver(
    commodities={"Tomato": "tomato"},
    markets={"Anand": "anand", "Ahmedabad": "ahmedabad", "Surat": "surat"},
)


async def seeded_store(today: date | None = None) -> Store:
    today = today or date(2026, 11, 24)
    ready = today + timedelta(days=5)
    s = Store(today=today)

    for f in [
        Farmer("farmer-asha", "Asha Patel (simulated)", "Boriavi", "Anand", 22.60, 72.94, "gu", "fpo-anand", True),
        Farmer("farmer-ravi", "Ravi Solanki (simulated)", "Vasad", "Anand", 22.45, 73.07, "gu", "fpo-anand", True),
        Farmer("farmer-meena", "Meena Parmar (simulated)", "Ode", "Anand", 22.62, 73.11, "gu", "fpo-anand", True),
        Farmer("farmer-far", "Far Away Farmer (simulated)", "Bhuj", "Kutch", 23.25, 69.67, "gu", None, True),
    ]:
        s.farmers[f.id] = f

    for lot in [
        Lot("lot-asha", "farmer-asha", "tomato", 3000, "A", ready),
        Lot("lot-ravi", "farmer-ravi", "tomato", 1200, "A", ready),
        Lot("lot-meena", "farmer-meena", "tomato", 1000, "B", ready + timedelta(days=1)),
        Lot("lot-far", "farmer-far", "tomato", 5000, "A", ready),
    ]:
        s.lots[lot.id] = lot

    for m in [
        Market("anand", "Anand APMC", "Anand", 22.56, 72.95, 0.6, 0.4),
        Market("ahmedabad", "Ahmedabad APMC", "Ahmedabad", 23.02, 72.57, 0.8, 0.5),
        Market("surat", "Surat APMC", "Surat", 21.17, 72.83, 0.9, 0.6),
    ]:
        s.markets[m.id] = m

    s.buyer_requirements["req-processor"] = BuyerRequirement(
        "req-processor", "Simulated Tomato Processor", "food_processor", "tomato", 5000, "B",
        ready - timedelta(days=1), ready + timedelta(days=3), 25.0, 22.31, 73.18,
    )

    s.vehicles["veh-1"] = Vehicle(
        "veh-1", "Simulated Transporter", 7000, 28.0, 22.56, 72.95, [ready, ready + timedelta(days=1)]
    )

    s.storage["cold-anand"] = StorageOption("cold-anand", "Simulated Cold Store, Anand", 22.55, 72.96, 0.25, 0.5, "tomato")

    config = load_source_file(API_ROOT / "config/market_sources/simulated-gujarat-tomato.yaml")
    config.request.path = str(API_ROOT / config.request.path)
    result = await run_source(config, aliases=ALIASES)
    if result.error:
        raise RuntimeError(f"seed price load failed: {result.error}")
    s.prices.extend(result.observations)
    s.source_priorities[config.name] = config.priority
    return s
