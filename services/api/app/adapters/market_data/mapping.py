"""Turns a raw source record into a PriceObservation using the source's declarative field mapping."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from app.adapters.market_data.models import FieldMapping, PriceObservation, SourceConfig
from app.domain.units import PriceUnit, to_inr_per_kg

_PRICE_TARGETS = {"min_price", "max_price", "modal_price"}


class MappingError(ValueError):
    pass


def get_path(record: Any, path: str) -> Any:
    """Read `a.b.c` (or `$.a.b.c`) from nested dicts. `$` alone returns the record."""
    path = path.removeprefix("$").removeprefix(".")
    current = record
    if not path:
        return current
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _parse(value: Any, spec: FieldMapping, target: str) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        return spec.default
    if spec.parse == "str":
        return str(value).strip()
    if spec.parse == "number":
        try:
            number = Decimal(str(value).replace(",", "").strip())
        except InvalidOperation:
            raise MappingError(f"{target}: '{value}' is not a number") from None
        if target in _PRICE_TARGETS:
            return to_inr_per_kg(number, spec.unit or PriceUnit.INR_PER_KG)
        return number
    if spec.parse == "date":
        if isinstance(value, date):
            return value
        text = str(value).strip()
        try:
            if spec.format:
                return datetime.strptime(text, spec.format).date()
            return date.fromisoformat(text[:10])
        except ValueError:
            raise MappingError(f"{target}: '{value}' does not match date format {spec.format or 'ISO'}") from None
    raise MappingError(f"unknown parse type {spec.parse}")


def map_record(record: dict[str, Any], config: SourceConfig, fetched_at: datetime) -> PriceObservation:
    values: dict[str, Any] = {}
    for target, spec in config.mapping.items():
        values[target] = _parse(get_path(record, spec.from_), spec, target)
    try:
        return PriceObservation(
            source=config.name,
            data_kind=config.data_kind,
            state=values.get("state"),
            district=values.get("district"),
            market=values.get("market"),
            commodity=values.get("commodity"),
            variety=values.get("variety"),
            grade=values.get("grade"),
            date=values.get("date"),
            min_price_per_kg=values.get("min_price"),
            max_price_per_kg=values.get("max_price"),
            modal_price_per_kg=values.get("modal_price"),
            arrivals_qty=values.get("arrivals_qty"),
            arrivals_unit=values.get("arrivals_unit"),
            fetched_at=fetched_at,
            raw=record,
        )
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise MappingError(problems) from None
