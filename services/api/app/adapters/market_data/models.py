"""Config and data models for plug-and-play market price sources.

See docs/design/market-price-sources.md.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.units import PriceUnit


class DataKind(StrEnum):
    OBSERVED = "observed"
    HISTORICAL = "historical"
    FORECAST = "forecast"
    SIMULATED = "simulated"


class AuthConfig(BaseModel):
    type: Literal["none", "query_param", "header", "bearer", "basic"] = "none"
    name: str | None = Field(default=None, description="Query parameter or header name")
    secret: str | None = Field(default=None, description="Name of the secret holding the value, never the value")
    username_secret: str | None = None  # basic auth

    @model_validator(mode="after")
    def _check(self) -> "AuthConfig":
        if self.type in ("query_param", "header") and not (self.name and self.secret):
            raise ValueError(f"auth type '{self.type}' needs 'name' and 'secret'")
        if self.type in ("bearer", "basic") and not self.secret:
            raise ValueError(f"auth type '{self.type}' needs 'secret'")
        if self.type == "basic" and not self.username_secret:
            raise ValueError("auth type 'basic' needs 'username_secret'")
        return self


class PaginationConfig(BaseModel):
    type: Literal["none", "offset", "page", "cursor"] = "none"
    offset_param: str = "offset"
    limit_param: str = "limit"
    page_param: str = "page"
    page_size: int = Field(default=500, gt=0)
    cursor_param: str = "cursor"
    next_cursor_path: str | None = Field(default=None, description="Path to the next cursor in the response, e.g. $.next")
    max_pages: int = Field(default=1000, gt=0, description="Safety limit")


class RequestConfig(BaseModel):
    """Connector-specific request settings. Unused fields are ignored by connectors that don't need them."""

    # http_json / http_csv
    url: str | None = None
    method: Literal["GET", "POST"] = "GET"
    params: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    pagination: PaginationConfig = Field(default_factory=PaginationConfig)
    records_path: str = "$"
    timeout_seconds: float = Field(default=30, gt=0)
    # sql
    dsn_secret: str | None = None
    query: str | None = None
    # file
    path: str | None = None
    # plugin
    plugin: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class FieldMapping(BaseModel):
    from_: str = Field(alias="from", description="Source field name; dots reach into nested objects")
    parse: Literal["str", "number", "date"] = "str"
    format: str | None = Field(default=None, description="strptime format for dates")
    unit: PriceUnit | None = Field(default=None, description="Price unit of the source field; converted to INR/kg")
    default: Any = None

    model_config = {"populate_by_name": True}


TARGET_FIELDS = {
    "state", "district", "market", "commodity", "variety", "grade", "date",
    "min_price", "max_price", "modal_price", "arrivals_qty", "arrivals_unit",
}
REQUIRED_TARGETS = {"market", "commodity", "date", "modal_price"}


class IncrementalConfig(BaseModel):
    watermark_field: str = "date"
    param: str | None = Field(default=None, description="Request parameter that receives the watermark")
    format: str = "%Y-%m-%d"


class SourceConfig(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    connector: str
    data_kind: DataKind
    priority: int = 100
    schedule: str | None = Field(default=None, description="Cron expression; None = manual only")
    enabled: bool = False
    request: RequestConfig = Field(default_factory=RequestConfig)
    mapping: dict[str, FieldMapping]
    incremental: IncrementalConfig | None = None
    max_price_per_kg: Decimal = Field(default=Decimal(1000), gt=0, description="Sanity limit; rows above it are rejected")

    @model_validator(mode="after")
    def _check_mapping(self) -> "SourceConfig":
        unknown = set(self.mapping) - TARGET_FIELDS
        if unknown:
            raise ValueError(f"unknown target fields in mapping: {sorted(unknown)}")
        missing = REQUIRED_TARGETS - set(self.mapping)
        if missing:
            raise ValueError(f"mapping must cover {sorted(missing)}")
        for target in ("min_price", "max_price", "modal_price"):
            spec = self.mapping.get(target)
            if spec is None:
                continue
            # A missing unit is the classic 100x error (quintal read as kg), so it must be explicit.
            if spec.parse != "number" or spec.unit is None:
                raise ValueError(f"{target} must use parse: number and an explicit unit (e.g. INR_per_quintal)")
        return self


class PriceObservation(BaseModel):
    """The one standard shape every source is mapped into. Prices are INR per kg."""

    source: str
    data_kind: DataKind
    state: str | None = None
    district: str | None = None
    market: str
    market_id: str | None = None
    commodity: str
    commodity_id: str | None = None
    variety: str | None = None
    grade: str | None = None
    date: date
    min_price_per_kg: Decimal | None = Field(default=None, ge=0)
    max_price_per_kg: Decimal | None = Field(default=None, ge=0)
    modal_price_per_kg: Decimal = Field(ge=0)
    arrivals_qty: Decimal | None = Field(default=None, ge=0)
    arrivals_unit: str | None = None
    fetched_at: datetime
    raw: dict[str, Any]

    @model_validator(mode="after")
    def _check_order(self) -> "PriceObservation":
        lo, hi = self.min_price_per_kg, self.max_price_per_kg
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("min price is above max price")
        if lo is not None and self.modal_price_per_kg < lo or hi is not None and self.modal_price_per_kg > hi:
            raise ValueError("modal price is outside the min-max range")
        if self.modal_price_per_kg == 0:
            raise ValueError("modal price is zero")
        return self


class RejectedRecord(BaseModel):
    raw: dict[str, Any]
    reason: str


class UnmatchedRecord(BaseModel):
    raw: dict[str, Any]
    field: Literal["market", "commodity"]
    value: str


class IngestResult(BaseModel):
    source: str
    fetched: int = 0
    observations: list[PriceObservation] = Field(default_factory=list)
    rejected: list[RejectedRecord] = Field(default_factory=list)
    unmatched: list[UnmatchedRecord] = Field(default_factory=list)
    new_watermark: date | None = None
    error: str | None = None
