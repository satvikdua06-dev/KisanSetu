# Plug-and-play market price sources

**Status:** design, 2026-11-24. Implemented as part of the backend scaffold (`services/api/app/adapters/market_data/`).

## Goal

KisanSetu must not depend on any one price feed. Adding a new source of mandi prices (a government API, a private data vendor, an FPO's own database, a CSV export) should be a **configuration step, not a code change**: register the source, map its fields once, and its prices flow into the same table every agent already reads.

## How it works

```
 any source ──> connector ──> field mapping ──> validate + normalise ──> price_observation table ──> Market Intelligence agent
 (API, DB,      (fetches      (source fields     (units to ₹/kg,          (one standard shape,
  file)          raw rows)     -> our fields)     names -> our IDs)         source + date on every row)
```

1. A **source** is a row in `market_data_source` (or a YAML file under `config/market_sources/` that is loaded into that table). It says which connector to use, where to fetch, how to authenticate, how to page through results, and how its fields map to ours.
2. A **connector** knows how to talk to one *kind* of source. Four generic connectors cover almost everything without writing code:

   | Connector | Covers |
   |---|---|
   | `http_json` | Any REST API that returns JSON: query parameters, headers, auth, pagination, a path to the records array |
   | `http_csv` | Any URL that returns CSV |
   | `sql` | A read-only connection to an external database (Postgres, MySQL, SQL Server) plus a query |
   | `file` | A CSV or Excel file uploaded by an admin or dropped in object storage |

   A source that needs real code (unusual auth, scraping a portal, a SOAP API) can use a **`plugin` connector**: a Python class implementing the same interface, registered by name. That is the only case that needs a code change.
3. The **field mapping** turns each raw record into our standard `PriceObservation`. It is declarative: source field name, optional transform (date format, unit, number parsing), target field.
4. **Validation and normalisation**: Pydantic checks every row; prices are converted to ₹/kg (sources usually publish ₹/quintal); commodity and market names are matched to our IDs through alias tables. Rows whose names don't match go to a **review queue** instead of being dropped silently.
5. **Storage**: rows are upserted into `price_observation`, unique per source, market, commodity, variety, grade and date, so re-running a fetch never creates duplicates. The raw record is kept alongside for audit.
6. **Scheduling**: each source has its own cron schedule and runs as a background job. Fetches are incremental: each source keeps a watermark (the latest date it has loaded) and asks only for newer data.

## Adding a source (the plug-and-play part)

Through the admin API or dashboard:

1. `POST /admin/market-sources` with the source config (example below). The API key itself is **not** stored in the config, only the name of the secret that holds it.
2. `POST /admin/market-sources/{id}/test`: a dry run that fetches a small sample, applies the mapping and returns a preview of the mapped rows, the rows that failed validation and the names that didn't match. Nothing is written.
3. Fix the mapping if needed, then `POST /admin/market-sources/{id}/enable`. From then on it runs on its schedule.
4. `GET /admin/market-sources` shows each source's health: last successful run, rows loaded, last error.

### Example source config

Agmarknet daily prices through the data.gov.in open-data API. The resource ID and field names below must be checked against the live dataset before enabling.

```yaml
name: agmarknet-datagovin
connector: http_json
data_kind: observed            # observed | historical | forecast | simulated
priority: 10                   # lower wins when sources disagree
schedule: "30 20 * * *"        # daily, 20:30 IST
request:
  url: https://api.data.gov.in/resource/<resource-id>
  method: GET
  params:
    format: json
    limit: 500
    filters[state]: Gujarat
  auth:
    type: query_param          # query_param | header | bearer | basic | none
    name: api-key
    secret: DATAGOVIN_API_KEY  # name of the secret, never the value
  pagination:
    type: offset               # offset | page | cursor | none
    offset_param: offset
    limit_param: limit
  records_path: $.records
mapping:
  state:        { from: state }
  district:     { from: district }
  market:       { from: market }
  commodity:    { from: commodity }
  variety:      { from: variety }
  grade:        { from: grade }
  date:         { from: arrival_date, parse: date, format: "%d/%m/%Y" }
  min_price:    { from: min_price, parse: number, unit: INR_per_quintal }
  max_price:    { from: max_price, parse: number, unit: INR_per_quintal }
  modal_price:  { from: modal_price, parse: number, unit: INR_per_quintal }
incremental:
  watermark_field: date
  param: filters[arrival_date]
```

A database source looks the same with a different connector:

```yaml
name: fpo-anand-prices
connector: sql
data_kind: observed
schedule: "0 * * * *"
request:
  dsn_secret: FPO_ANAND_DB_URL
  query: >
    SELECT mandi, crop, rate_per_kg, rate_date
    FROM daily_rates WHERE rate_date > :watermark
mapping:
  market:      { from: mandi }
  commodity:   { from: crop }
  modal_price: { from: rate_per_kg, parse: number, unit: INR_per_kg }
  date:        { from: rate_date, parse: date }
```

The prototype's **simulated** prices are just another source with `connector: file` and `data_kind: simulated`, so the UI labels them the same way.

## Data model

```
market_data_source
  id, name, connector, data_kind, priority, schedule, enabled,
  config jsonb (request, pagination, auth secret names), mapping jsonb,
  watermark, last_run_at, last_success_at, last_error, created_at, updated_at

price_observation
  id, source_id -> market_data_source,
  commodity_id, variety, grade, market_id,
  date, min_price_per_kg, max_price_per_kg, modal_price_per_kg,
  arrivals_qty, arrivals_unit,
  data_kind, fetched_at, raw jsonb
  unique (source_id, market_id, commodity_id, variety, grade, date)

commodity_alias   (source_id nullable, raw_name) -> commodity_id
market_alias      (source_id nullable, raw_name) -> market_id
unmatched_record  (source_id, raw jsonb, reason, status)   -- the review queue
source_run        (source_id, started_at, finished_at, rows_fetched, rows_loaded, rows_rejected, error)
```

## Connector interface (for plugins)

```python
class PriceSourceConnector(Protocol):
    kind: str

    def validate_config(self, config: dict) -> None:
        """Raise a clear error if the config is missing or wrong."""

    async def fetch(self, config: dict, secrets: SecretReader,
                    since: date | None) -> AsyncIterator[dict]:
        """Yield raw records newer than `since`, handling paging and retries."""
```

The mapper, validation, unit conversion, alias matching, upsert, scheduling and health tracking are shared, so a plugin only implements `fetch`.

## How the agents read prices

The Market Intelligence agent never calls a source directly. It queries `price_observation` through one service, `get_prices(commodity, markets, date_range)`, which:

- returns every source's rows, each with its source name, `data_kind` and date, so the UI can show "observed, Agmarknet, 23 Nov" or "simulated";
- when sources disagree on the same market and day, prefers the lowest `priority` number, then the most recent fetch, and reports the spread;
- flags stale data (no observation within a configurable number of days).

Swapping, adding or removing a source therefore changes nothing in the agents.

## Safety rules

- Secrets live in the secret manager or environment; configs only name them.
- `sql` connectors use read-only credentials and run with a statement timeout.
- Outbound `http_*` requests have timeouts, retries with backoff and a per-source rate limit.
- A source that fails repeatedly is marked unhealthy and paused; it never blocks other sources.
- Prices from the model are never stored as observations. The LLM reads this table; it does not write to it.
