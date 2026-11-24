# KisanSetu API

FastAPI backend: the multi-agent runtime, the deterministic tools the agents call, and plug-and-play market price sources.

## Run

```bash
uv sync
uv run pytest          # 57 tests, no API key or network needed
uv run uvicorn app.main:app --reload
```

Live agent runs call Claude and need `ANTHROPIC_API_KEY` (or `ant auth login`). Tests use a scripted model that drives the same runtime and the same real tools.

Settings (environment variables):

| Variable | Purpose |
|---|---|
| `KISANSETU_ADMIN_KEY` | Enables `/admin/*` endpoints; send it as `X-Admin-Key`. Unset = admin endpoints disabled |
| `MARKET_DATA_FILE_ROOT` | Folder file price sources may read from (default `config/`) |
| `MARKET_SOURCES_ALLOW_PRIVATE_HOSTS` | `1` only for a price API deliberately on a private network |
| Secret names in source configs (e.g. `DATAGOVIN_API_KEY`) | Read from the environment by name |

## Layout

| Path | What it is |
|---|---|
| `app/agents/runtime/` | Agent loop, Orchestrator runtime (delegation, parallel tasks, escalation, approvals, events), shared workflow state, message log, Claude client |
| `app/agents/definitions/` | The Orchestrator and the seven specialist agents: prompt, tools, output schema, model tier |
| `app/tools/` | Deterministic calculations (net realisation) |
| `app/adapters/market_data/` | Plug-and-play price sources: config models, connectors (`http_json`, `http_csv`, `sql`, `file`, `plugin`), mapping, aliases, engine |
| `app/domain/` | Units, the operational store (in-memory for now), simulated seed data |
| `config/market_sources/` | Source configs. `agmarknet-datagovin.yaml` is disabled until its resource ID is verified |
| `tests/` | Net realisation, price sources, the full tomato scenario through all agents, Claude request shape, audit regressions |

## Not built yet

- Postgres models and migrations (the store is in-memory), ARQ workers, Docker Compose.
- OR-Tools for pooling and routing: `aggregate_lots` and `route_pickups` use simple greedy and nearest-neighbour methods for now, and say so in their output.
- Speech, SMS and voice-call adapters; the mobile and web apps.
- Phone OTP login and role-based access (admin endpoints use a shared key until then); long-term agent memory; OpenTelemetry.
