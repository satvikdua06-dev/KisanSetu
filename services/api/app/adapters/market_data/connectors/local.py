"""Connectors for external databases, files, and code plugins."""

import asyncio
import csv
import os
import re
from collections.abc import AsyncIterator, Callable
from datetime import date
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from app.adapters.market_data.connectors.base import ConnectorConfigError, ConnectorContext, register
from app.adapters.market_data.models import SourceConfig

_READ_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|merge|call|exec|execute|into|copy|attach|pragma|lock)\b",
    re.IGNORECASE,
)
# Defence in depth only: the DSN must also use a read-only database user.

_API_ROOT = Path(__file__).resolve().parents[4]


def file_root() -> Path:
    """Directory file sources may read from (uploads and seeded simulations), nothing outside it."""
    return Path(os.environ.get("MARKET_DATA_FILE_ROOT", _API_ROOT / "config")).resolve()


@register("sql")
class SqlConnector:
    """Runs one read-only query against an external database. The DSN comes from a named secret."""

    def validate_config(self, config: SourceConfig) -> None:
        req = config.request
        if not req.dsn_secret or not req.query:
            raise ConnectorConfigError("sql source needs request.dsn_secret and request.query")
        query = req.query.strip().rstrip(";")
        if ";" in query or "--" in query or "/*" in query:
            raise ConnectorConfigError("sql source query must be a single read-only SELECT (no ';' or comments)")
        if not _READ_ONLY.match(query) or _WRITE_WORDS.search(query):
            raise ConnectorConfigError("sql source query must be a single read-only SELECT")

    async def fetch(
        self, config: SourceConfig, ctx: ConnectorContext, since: date | None, limit: int | None
    ) -> AsyncIterator[dict[str, Any]]:
        self.validate_config(config)
        dsn = ctx.secrets.get(config.request.dsn_secret)
        query = config.request.query
        params: dict[str, Any] = {}
        if ":watermark" in query:
            params["watermark"] = since or date(1900, 1, 1)

        def run() -> list[dict[str, Any]]:
            engine = sa.create_engine(dsn)
            try:
                with engine.connect() as conn:
                    conn = conn.execution_options(stream_results=True)
                    result = conn.execute(sa.text(query), params)
                    rows = result.mappings().fetchmany(limit) if limit else result.mappings().all()
                    return [dict(r) for r in rows]
            finally:
                engine.dispose()

        for row in await asyncio.to_thread(run):
            yield row


@register("file")
class FileConnector:
    """Reads a CSV file (an admin upload or a seeded simulation)."""

    def validate_config(self, config: SourceConfig) -> None:
        path = config.request.path
        if not path:
            raise ConnectorConfigError("file source needs request.path")
        if not path.lower().endswith(".csv"):
            raise ConnectorConfigError("file source supports .csv (Excel support is planned)")
        self._resolve(path)

    @staticmethod
    def _resolve(path: str) -> Path:
        root = file_root()
        candidate = Path(path)
        resolved = (candidate if candidate.is_absolute() else root.parent / candidate).resolve()
        if not resolved.is_relative_to(root):
            raise ConnectorConfigError(f"file sources must live under {root}")
        return resolved

    async def fetch(
        self, config: SourceConfig, ctx: ConnectorContext, since: date | None, limit: int | None
    ) -> AsyncIterator[dict[str, Any]]:
        self.validate_config(config)
        path = self._resolve(config.request.path)
        if not path.is_file():
            raise ConnectorConfigError(f"file not found: {path}")
        with path.open(newline="", encoding="utf-8-sig") as f:
            for i, row in enumerate(csv.DictReader(f)):
                if limit is not None and i >= limit:
                    return
                yield row


# --- Plugins: the one case that needs code ---------------------------------------------

PluginFetch = Callable[[SourceConfig, ConnectorContext, date | None, int | None], AsyncIterator[dict[str, Any]]]
_PLUGINS: dict[str, PluginFetch] = {}


def register_plugin(name: str) -> Callable[[PluginFetch], PluginFetch]:
    """Register an async generator `fetch(config, ctx, since, limit)` under `name`."""

    def decorator(fn: PluginFetch) -> PluginFetch:
        _PLUGINS[name] = fn
        return fn

    return decorator


@register("plugin")
class PluginConnector:
    def validate_config(self, config: SourceConfig) -> None:
        name = config.request.plugin
        if not name:
            raise ConnectorConfigError("plugin source needs request.plugin")
        if name not in _PLUGINS:
            raise ConnectorConfigError(f"unknown plugin '{name}'; registered: {sorted(_PLUGINS)}")

    async def fetch(
        self, config: SourceConfig, ctx: ConnectorContext, since: date | None, limit: int | None
    ) -> AsyncIterator[dict[str, Any]]:
        self.validate_config(config)
        async for record in _PLUGINS[config.request.plugin](config, ctx, since, limit):
            yield record
