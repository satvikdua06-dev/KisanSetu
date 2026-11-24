"""Price unit conversion. Everything inside KisanSetu is stored and compared in INR per kg."""

from decimal import Decimal
from enum import StrEnum


class PriceUnit(StrEnum):
    INR_PER_KG = "INR_per_kg"
    INR_PER_QUINTAL = "INR_per_quintal"  # 100 kg, the usual mandi unit
    INR_PER_TONNE = "INR_per_tonne"  # 1,000 kg


_KG_PER_UNIT: dict[PriceUnit, Decimal] = {
    PriceUnit.INR_PER_KG: Decimal(1),
    PriceUnit.INR_PER_QUINTAL: Decimal(100),
    PriceUnit.INR_PER_TONNE: Decimal(1000),
}


def to_inr_per_kg(value: Decimal | float | int | str, unit: PriceUnit | str) -> Decimal:
    """Convert a price quoted in `unit` to INR per kg."""
    unit = PriceUnit(unit)
    return Decimal(str(value)) / _KG_PER_UNIT[unit]
