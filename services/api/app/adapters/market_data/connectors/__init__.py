"""Importing this package registers every built-in connector."""

from app.adapters.market_data.connectors import http, local  # noqa: F401
from app.adapters.market_data.connectors.base import (
    ConnectorConfigError,
    ConnectorContext,
    available_connectors,
    get_connector,
)
from app.adapters.market_data.connectors.local import register_plugin

__all__ = ["ConnectorConfigError", "ConnectorContext", "available_connectors", "get_connector", "register_plugin"]
