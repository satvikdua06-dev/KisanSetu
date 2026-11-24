from decimal import Decimal

import pytest

from app.domain.units import to_inr_per_kg
from app.tools.net_realisation import CostBreakdown, PriceRange, SellingOption, net_realisation, rank_options


def option(name: str, price: str, cost: str) -> SellingOption:
    p = Decimal(price)
    return SellingOption(name=name, price_per_kg=PriceRange(low=p, expected=p, high=p),
                         costs_per_kg=CostBreakdown(transport=Decimal(cost)))


def test_deck_example_highest_price_is_not_highest_earning():
    # The illustrative figures from the pitch deck (slide 7).
    ranked = rank_options([option("Local", "20", "1"), option("Regional", "24", "3"), option("Distant", "27", "6")], 1000)
    nets = {r.option: r.net_per_kg.expected for r in ranked}
    assert nets == {"Local": Decimal("19.00"), "Regional": Decimal("21.00"), "Distant": Decimal("21.00")}
    assert ranked[0].net_total.expected == Decimal("21000.00")
    # Tie at 21: the cheaper-to-reach option ranks first.
    assert [r.option for r in ranked] == ["Regional", "Distant", "Local"]


def test_range_carries_through_and_all_costs_count():
    o = SellingOption(
        name="Mandi",
        price_per_kg=PriceRange(low=Decimal(18), expected=Decimal(20), high=Decimal(22)),
        costs_per_kg=CostBreakdown(transport=Decimal("1.5"), handling=Decimal("0.5"), market_fees=Decimal("0.8"),
                                   quality_deduction=Decimal("0.2")),
    )
    r = net_realisation(o, 500)
    assert r.costs_per_kg == Decimal("3.00")
    assert (r.net_per_kg.low, r.net_per_kg.expected, r.net_per_kg.high) == (Decimal("15.00"), Decimal("17.00"), Decimal("19.00"))
    assert r.net_total.expected == Decimal("8500.00")


def test_negative_net_is_reported_not_hidden():
    assert net_realisation(option("Far", "5", "6"), 100).net_per_kg.expected == Decimal("-1.00")


def test_quantity_must_be_positive():
    with pytest.raises(ValueError):
        net_realisation(option("X", "10", "1"), 0)


def test_unit_conversion():
    assert to_inr_per_kg(2400, "INR_per_quintal") == Decimal(24)
    assert to_inr_per_kg("27000", "INR_per_tonne") == Decimal(27)
