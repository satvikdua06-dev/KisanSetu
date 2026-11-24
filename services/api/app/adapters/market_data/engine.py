"""Runs a source end to end: fetch -> map -> validate/normalise -> result.

`dry_run` is the "test" step of adding a source: same pipeline, small sample, nothing stored.
Storage (upsert into price_observation) is done by the caller with the returned observations.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import yaml

from app.adapters.market_data.aliases import AliasResolver
from app.adapters.market_data.connectors import ConnectorConfigError, ConnectorContext, get_connector
from app.adapters.market_data.mapping import MappingError, map_record
from app.adapters.market_data.models import (
    IngestResult,
    RejectedRecord,
    SourceConfig,
    UnmatchedRecord,
)
from app.adapters.market_data.secrets import EnvSecretReader, MissingSecretError, SecretReader


def load_source_file(path: str | Path) -> SourceConfig:
    with open(path, encoding="utf-8") as f:
        return SourceConfig.model_validate(yaml.safe_load(f))


def validate_source(config: SourceConfig) -> None:
    get_connector(config.connector).validate_config(config)


async def run_source(
    config: SourceConfig,
    *,
    aliases: AliasResolver,
    secrets: SecretReader | None = None,
    since: date | None = None,
    limit: int | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> IngestResult:
    result = IngestResult(source=config.name)
    ctx = ConnectorContext(secrets=secrets or EnvSecretReader(), http_transport=http_transport)
    fetched_at = datetime.now(UTC)
    try:
        connector = get_connector(config.connector)
        connector.validate_config(config)
        async for record in connector.fetch(config, ctx, since, limit):
            result.fetched += 1
            try:
                obs = map_record(record, config, fetched_at)
            except MappingError as exc:
                result.rejected.append(RejectedRecord(raw=record, reason=str(exc)))
                continue

            commodity_id = aliases.commodity_id(obs.commodity)
            market_id = aliases.market_id(obs.market)
            if commodity_id is None:
                result.unmatched.append(UnmatchedRecord(raw=record, field="commodity", value=obs.commodity))
            if market_id is None:
                result.unmatched.append(UnmatchedRecord(raw=record, field="market", value=obs.market))
            if commodity_id is None or market_id is None:
                continue

            obs.commodity_id, obs.market_id = commodity_id, market_id
            if since is not None and obs.date <= since:
                continue  # source ignored the watermark; keep loads incremental anyway
            result.observations.append(obs)
            if result.new_watermark is None or obs.date > result.new_watermark:
                result.new_watermark = obs.date
    except (ConnectorConfigError, MissingSecretError, httpx.HTTPError) as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    return result


async def dry_run(
    config: SourceConfig,
    *,
    aliases: AliasResolver,
    secrets: SecretReader | None = None,
    sample_size: int = 20,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> IngestResult:
    """Fetch a small sample and show what would be loaded, rejected and left unmatched. Writes nothing."""
    return await run_source(
        config, aliases=aliases, secrets=secrets, limit=sample_size, http_transport=http_transport
    )
