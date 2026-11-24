"""Net realisation: what the farmer actually earns per kg after costs.

Deterministic by design. Agents call these functions; they never compute prices themselves.
"""

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field, computed_field

_PAISE = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_PAISE, rounding=ROUND_HALF_UP)


class PriceRange(BaseModel):
    """Expected price per kg as a range, never a single guaranteed figure."""

    low: Decimal = Field(ge=0)
    expected: Decimal = Field(ge=0)
    high: Decimal = Field(ge=0)


class CostBreakdown(BaseModel):
    """Costs per kg. A component the data doesn't cover is listed in `assumptions`, not silently zero."""

    transport: Decimal = Field(default=Decimal(0), ge=0)
    handling: Decimal = Field(default=Decimal(0), ge=0)
    market_fees: Decimal = Field(default=Decimal(0), ge=0)
    quality_deduction: Decimal = Field(default=Decimal(0), ge=0)
    other: Decimal = Field(default=Decimal(0), ge=0)

    @computed_field
    @property
    def total(self) -> Decimal:
        return self.transport + self.handling + self.market_fees + self.quality_deduction + self.other


class SellingOption(BaseModel):
    name: str
    price_per_kg: PriceRange
    costs_per_kg: CostBreakdown
    sources: list[str] = Field(default_factory=list, description="e.g. 'agmarknet-datagovin, observed, 2026-11-23'")
    assumptions: list[str] = Field(default_factory=list)


class NetRealisation(BaseModel):
    option: str
    quantity_kg: Decimal
    net_per_kg: PriceRange
    net_total: PriceRange
    costs_per_kg: Decimal
    sources: list[str]
    assumptions: list[str]


def net_realisation(option: SellingOption, quantity_kg: Decimal | int | float) -> NetRealisation:
    """Net per kg = price - (transport + handling + market fees + quality deductions + other).

    Applied to the low, expected and high price so the uncertainty carries through.
    Net can be negative: that is a real outcome the farmer must see, not an error.
    """
    qty = Decimal(str(quantity_kg))
    if qty <= 0:
        raise ValueError("quantity_kg must be positive")
    cost = option.costs_per_kg.total
    p = option.price_per_kg
    per_kg = PriceRange.model_construct(
        low=_money(p.low - cost), expected=_money(p.expected - cost), high=_money(p.high - cost)
    )
    total = PriceRange.model_construct(
        low=_money(per_kg.low * qty), expected=_money(per_kg.expected * qty), high=_money(per_kg.high * qty)
    )
    return NetRealisation(
        option=option.name,
        quantity_kg=qty,
        net_per_kg=per_kg,
        net_total=total,
        costs_per_kg=_money(cost),
        sources=option.sources,
        assumptions=option.assumptions,
    )


def rank_options(options: list[SellingOption], quantity_kg: Decimal | int | float) -> list[NetRealisation]:
    """Rank options by expected net realisation, best first. Ties keep the cheaper-to-reach option first."""
    results = [net_realisation(o, quantity_kg) for o in options]
    return sorted(results, key=lambda r: (-r.net_per_kg.expected, r.costs_per_kg))
