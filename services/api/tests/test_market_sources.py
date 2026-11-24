import sqlite3
from datetime import date
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from app.adapters.market_data.aliases import AliasResolver
from app.adapters.market_data.connectors import ConnectorConfigError, register_plugin
from app.adapters.market_data.engine import dry_run, run_source
from app.adapters.market_data.models import SourceConfig
from app.adapters.market_data.secrets import DictSecretReader

ALIASES = AliasResolver(commodities={"Tomato": "tomato"}, markets={"Anand": "anand", "Surat": "surat"})

ROWS = [
    {"market": "Anand", "commodity": "Tomato", "arrival_date": "22/11/2026", "min_price": "1800", "max_price": "2200", "modal_price": "2000"},
    {"market": "Surat", "commodity": "Tomato (Hybrid)", "arrival_date": "22/11/2026", "min_price": "2400", "max_price": "3000", "modal_price": "2700"},
    {"market": "Unknown Mandi", "commodity": "Tomato", "arrival_date": "22/11/2026", "modal_price": "2100"},
    {"market": "Anand", "commodity": "Tomato", "arrival_date": "not a date", "modal_price": "2000"},
    {"market": "Anand", "commodity": "Tomato", "arrival_date": "23/11/2026", "min_price": "2500", "max_price": "2000", "modal_price": "2200"},
]


def json_api_config(**overrides) -> SourceConfig:
    data = {
        "name": "test-json-api",
        "connector": "http_json",
        "data_kind": "observed",
        "request": {
            "url": "https://prices.example.test/resource",
            "params": {"format": "json"},
            "auth": {"type": "query_param", "name": "api-key", "secret": "PRICE_KEY"},
            "pagination": {"type": "offset", "page_size": 2},
            "records_path": "$.records",
        },
        "mapping": {
            "market": {"from": "market"},
            "commodity": {"from": "commodity"},
            "date": {"from": "arrival_date", "parse": "date", "format": "%d/%m/%Y"},
            "min_price": {"from": "min_price", "parse": "number", "unit": "INR_per_quintal"},
            "max_price": {"from": "max_price", "parse": "number", "unit": "INR_per_quintal"},
            "modal_price": {"from": "modal_price", "parse": "number", "unit": "INR_per_quintal"},
        },
        "incremental": {"param": "filters[arrival_date]", "format": "%d/%m/%Y"},
    }
    data.update(overrides)
    return SourceConfig.model_validate(data)


def paged_api(requests: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("api-key") != "secret-123":
            return httpx.Response(401)
        offset, limit = int(request.url.params["offset"]), int(request.url.params["limit"])
        return httpx.Response(200, json={"records": ROWS[offset:offset + limit]})

    return httpx.MockTransport(handler)


async def test_json_api_source_end_to_end():
    requests: list[httpx.Request] = []
    result = await run_source(json_api_config(), aliases=ALIASES, secrets=DictSecretReader({"PRICE_KEY": "secret-123"}),
                              http_transport=paged_api(requests))
    assert result.error is None
    assert result.fetched == 5
    assert len(requests) == 3  # paged 2 + 2 + 1, stops on a short page

    assert [(o.market_id, o.modal_price_per_kg) for o in result.observations] == [("anand", Decimal(20)), ("surat", Decimal(27))]
    surat = result.observations[1]
    assert surat.commodity_id == "tomato"  # "Tomato (Hybrid)" matched through aliases
    assert surat.data_kind == "observed" and surat.source == "test-json-api" and surat.raw["market"] == "Surat"

    assert [u.value for u in result.unmatched] == ["Unknown Mandi"]  # goes to review, not silently dropped
    reasons = " | ".join(r.reason for r in result.rejected)
    assert "does not match date format" in reasons and "min price is above max price" in reasons
    assert result.new_watermark == date(2026, 11, 22)


async def test_incremental_fetch_sends_watermark_and_skips_old_rows():
    requests: list[httpx.Request] = []
    result = await run_source(json_api_config(), aliases=ALIASES, secrets=DictSecretReader({"PRICE_KEY": "secret-123"}),
                              since=date(2026, 11, 22), http_transport=paged_api(requests))
    assert requests[0].url.params["filters[arrival_date]"] == "22/11/2026"
    assert result.observations == []  # nothing newer than the watermark passed validation


async def test_dry_run_limits_sample_and_missing_secret_is_reported():
    sample = await dry_run(json_api_config(), aliases=ALIASES, secrets=DictSecretReader({"PRICE_KEY": "secret-123"}),
                           sample_size=1, http_transport=paged_api([]))
    assert sample.fetched == 1

    failed = await run_source(json_api_config(), aliases=ALIASES, secrets=DictSecretReader({}), http_transport=paged_api([]))
    assert failed.error and "PRICE_KEY" in failed.error


async def test_sql_source_reads_external_database(tmp_path):
    db = tmp_path / "fpo.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE daily_rates (mandi TEXT, crop TEXT, rate_per_kg REAL, rate_date TEXT)")
        conn.executemany("INSERT INTO daily_rates VALUES (?,?,?,?)",
                         [("Anand", "Tomato", 21.5, "2026-11-20"), ("Anand", "Tomato", 22.0, "2026-11-23")])
    config = SourceConfig.model_validate({
        "name": "fpo-db", "connector": "sql", "data_kind": "observed",
        "request": {"dsn_secret": "FPO_DB", "query": "SELECT mandi, crop, rate_per_kg, rate_date FROM daily_rates WHERE rate_date > :watermark"},
        "mapping": {"market": {"from": "mandi"}, "commodity": {"from": "crop"},
                    "modal_price": {"from": "rate_per_kg", "parse": "number"}, "date": {"from": "rate_date", "parse": "date"}},
    })
    result = await run_source(config, aliases=ALIASES, secrets=DictSecretReader({"FPO_DB": f"sqlite:///{db}"}),
                              since=date(2026, 11, 21))
    assert result.error is None
    assert [(o.date, o.modal_price_per_kg) for o in result.observations] == [(date(2026, 11, 23), Decimal("22.0"))]


async def test_sql_source_refuses_write_queries():
    config = SourceConfig.model_validate({
        "name": "bad-db", "connector": "sql", "data_kind": "observed",
        "request": {"dsn_secret": "X", "query": "DELETE FROM daily_rates"},
        "mapping": {"market": {"from": "a"}, "commodity": {"from": "b"}, "modal_price": {"from": "c"}, "date": {"from": "d"}},
    })
    result = await run_source(config, aliases=ALIASES, secrets=DictSecretReader({"X": "sqlite://"}))
    assert result.error and "read-only" in result.error


async def test_plugin_source():
    @register_plugin("test-portal")
    async def fetch(config, ctx, since, limit):
        yield {"m": "Anand", "c": "Tomato", "p": "19.5", "d": "2026-11-23"}

    config = SourceConfig.model_validate({
        "name": "portal", "connector": "plugin", "data_kind": "observed", "request": {"plugin": "test-portal"},
        "mapping": {"market": {"from": "m"}, "commodity": {"from": "c"}, "modal_price": {"from": "p", "parse": "number"},
                    "date": {"from": "d", "parse": "date"}},
    })
    result = await run_source(config, aliases=ALIASES)
    assert result.observations[0].modal_price_per_kg == Decimal("19.5")


def test_config_must_map_required_fields_and_known_targets():
    with pytest.raises(ValidationError, match="modal_price"):
        json_api_config(mapping={"market": {"from": "m"}, "commodity": {"from": "c"}, "date": {"from": "d"}})
    with pytest.raises(ValidationError, match="unknown target"):
        json_api_config(mapping={"market": {"from": "m"}, "commodity": {"from": "c"}, "date": {"from": "d"},
                                 "modal_price": {"from": "p"}, "colour": {"from": "x"}})


async def test_unknown_connector_is_a_clear_error():
    config = json_api_config(connector="ftp")
    result = await run_source(config, aliases=ALIASES)
    assert result.error and "unknown connector 'ftp'" in result.error


async def test_simulated_seed_source_matches_deck_prices():
    from app.domain.seed import seeded_store

    store = await seeded_store()
    modal = {p.market_id: p.modal_price_per_kg for p in store.prices}
    assert modal == {"anand": Decimal(20), "ahmedabad": Decimal(24), "surat": Decimal(27)}
    assert {p.data_kind for p in store.prices} == {"simulated"}


def test_http_connector_rejects_bad_url():
    from app.adapters.market_data.connectors import get_connector

    with pytest.raises(ConnectorConfigError):
        get_connector("http_json").validate_config(json_api_config(request={"url": "ftp://x"}))
