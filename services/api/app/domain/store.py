"""Operational data the agents' tools read and write.

In-memory implementation for the prototype and tests; the Postgres repository keeps this interface.
Everything seeded here is SIMULATED and labelled so wherever it appears.
"""

import math
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.adapters.market_data.models import PriceObservation


@dataclass
class Farmer:
    id: str
    name: str
    village: str
    district: str
    lat: float
    lon: float
    language: str
    fpo_id: str | None
    consent_share_with_buyers: bool = False


@dataclass
class Lot:
    id: str
    farmer_id: str
    commodity_id: str
    quantity_kg: float
    grade: str
    ready_date: date
    status: str = "available"  # available | committed | delivered


@dataclass
class Market:
    id: str
    name: str
    district: str
    lat: float
    lon: float
    fees_per_kg: float  # market fee + commission, INR/kg
    handling_per_kg: float


@dataclass
class BuyerRequirement:
    id: str
    buyer_name: str
    buyer_type: str
    commodity_id: str
    quantity_kg: float
    min_grade: str
    window_start: date
    window_end: date
    price_per_kg: float
    delivery_lat: float
    delivery_lon: float
    data_kind: str = "simulated"
    active: bool = True


@dataclass
class Vehicle:
    id: str
    operator: str
    capacity_kg: float
    rate_per_km: float  # INR per km for the whole vehicle
    base_lat: float
    base_lon: float
    available_dates: list[date]
    data_kind: str = "simulated"


@dataclass
class StorageOption:
    id: str
    name: str
    lat: float
    lon: float
    cost_per_kg_per_day: float
    spoilage_pct_per_day: float  # for the commodity it's configured for
    commodity_id: str
    data_kind: str = "simulated"


@dataclass
class Store:
    today: date = field(default_factory=date.today)
    source_priorities: dict[str, int] = field(default_factory=dict)  # price source name -> priority
    farmers: dict[str, Farmer] = field(default_factory=dict)
    lots: dict[str, Lot] = field(default_factory=dict)
    markets: dict[str, Market] = field(default_factory=dict)
    buyer_requirements: dict[str, BuyerRequirement] = field(default_factory=dict)
    vehicles: dict[str, Vehicle] = field(default_factory=dict)
    storage: dict[str, StorageOption] = field(default_factory=dict)
    prices: list[PriceObservation] = field(default_factory=list)
    agreements: dict[str, dict[str, Any]] = field(default_factory=dict)
    deliveries: dict[str, dict[str, Any]] = field(default_factory=dict)
    notifications: list[dict[str, Any]] = field(default_factory=list)

    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:8]}"


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance. The production routing tool uses OSRM road distances instead."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


GRADE_ORDER = {"C": 0, "B": 1, "A": 2}


def grade_meets(grade: str, minimum: str) -> bool:
    return GRADE_ORDER.get(grade, -1) >= GRADE_ORDER.get(minimum, 99)
