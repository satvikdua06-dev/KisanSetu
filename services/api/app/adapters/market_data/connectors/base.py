"""Connector interface and registry.

A connector knows how to talk to one kind of source and yields raw records.
Mapping, validation, normalisation and storage are shared and live in the engine.
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import httpx

from app.adapters.market_data.models import SourceConfig
from app.adapters.market_data.secrets import SecretReader


class ConnectorConfigError(ValueError):
    pass


@dataclass
class ConnectorContext:
    secrets: SecretReader
    http_transport: httpx.AsyncBaseTransport | None = None  # injected in tests

    def http_client(self, timeout: float) -> httpx.AsyncClient:
        # No redirects: a redirect could point an admin-approved URL at an internal address.
        return httpx.AsyncClient(transport=self.http_transport, timeout=timeout, follow_redirects=False)


class Connector(Protocol):
    kind: str

    def validate_config(self, config: SourceConfig) -> None:
        """Raise ConnectorConfigError with a clear message if the config can't work."""

    def fetch(
        self, config: SourceConfig, ctx: ConnectorContext, since: date | None, limit: int | None
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield raw records newer than `since` (if the source supports it), at most `limit`."""


_REGISTRY: dict[str, Callable[[], Connector]] = {}


def register(kind: str) -> Callable[[type], type]:
    def decorator(cls: type) -> type:
        cls.kind = kind
        _REGISTRY[kind] = cls
        return cls

    return decorator


def get_connector(kind: str) -> Connector:
    try:
        return _REGISTRY[kind]()
    except KeyError:
        raise ConnectorConfigError(f"unknown connector '{kind}'; available: {sorted(_REGISTRY)}") from None


def available_connectors() -> list[str]:
    return sorted(_REGISTRY)
