"""Generic HTTP connectors: any JSON or CSV API, configured, not coded."""

import asyncio
import csv
import io
import ipaddress
import os
import socket
from collections.abc import AsyncIterator
from datetime import date
from typing import Any
from urllib.parse import urlsplit

import httpx

_BLOCKED_SUFFIXES = (".local", ".internal", ".localhost")


def _private_hosts_allowed() -> bool:
    return os.environ.get("MARKET_SOURCES_ALLOW_PRIVATE_HOSTS") == "1"


def _is_internal(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast or addr.is_unspecified


async def check_public_host(url: str) -> None:
    """Refuse URLs that point inside our network (cloud metadata, databases, admin ports).

    Set MARKET_SOURCES_ALLOW_PRIVATE_HOSTS=1 only for a source deliberately hosted on a private network.
    """
    if _private_hosts_allowed():
        return
    host = (urlsplit(url).hostname or "").lower()
    if not host or host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        raise ConnectorConfigError(f"host '{host}' is not allowed")
    try:
        if _is_internal(host):
            raise ConnectorConfigError(f"address {host} is internal and not allowed")
        return  # a public IP literal
    except ValueError:
        pass  # a name, resolve it below
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return  # unresolvable: the request itself will fail
    for info in infos:
        if _is_internal(info[4][0]):
            raise ConnectorConfigError(f"host '{host}' resolves to an internal address and is not allowed")

from app.adapters.market_data.connectors.base import ConnectorConfigError, ConnectorContext, register
from app.adapters.market_data.mapping import get_path
from app.adapters.market_data.models import SourceConfig


def _auth(config: SourceConfig, ctx: ConnectorContext) -> tuple[dict[str, Any], dict[str, str], httpx.Auth | None]:
    auth = config.request.auth
    params: dict[str, Any] = {}
    headers: dict[str, str] = {}
    basic: httpx.Auth | None = None
    if auth.type == "query_param":
        params[auth.name] = ctx.secrets.get(auth.secret)
    elif auth.type == "header":
        headers[auth.name] = ctx.secrets.get(auth.secret)
    elif auth.type == "bearer":
        headers["Authorization"] = f"Bearer {ctx.secrets.get(auth.secret)}"
    elif auth.type == "basic":
        basic = httpx.BasicAuth(ctx.secrets.get(auth.username_secret), ctx.secrets.get(auth.secret))
    return params, headers, basic


def _base_params(config: SourceConfig, since: date | None) -> dict[str, Any]:
    params = dict(config.request.params)
    inc = config.incremental
    if since is not None and inc is not None and inc.param:
        params[inc.param] = since.strftime(inc.format)
    return params


class _HttpConnector:
    kind = "http"

    def validate_config(self, config: SourceConfig) -> None:
        if not config.request.url:
            raise ConnectorConfigError(f"{self.kind} source needs request.url")
        if not config.request.url.startswith(("https://", "http://")):
            raise ConnectorConfigError("request.url must be http(s)")

    def _records(self, response: httpx.Response, config: SourceConfig) -> tuple[list[dict[str, Any]], Any]:
        raise NotImplementedError

    async def fetch(
        self, config: SourceConfig, ctx: ConnectorContext, since: date | None, limit: int | None
    ) -> AsyncIterator[dict[str, Any]]:
        self.validate_config(config)
        req = config.request
        await check_public_host(req.url)
        pag = req.pagination
        auth_params, auth_headers, basic = _auth(config, ctx)
        params = {**_base_params(config, since), **auth_params}
        headers = {**req.headers, **auth_headers}
        yielded = 0
        offset, page, cursor = 0, 1, None

        async with ctx.http_client(req.timeout_seconds) as client:
            for _ in range(pag.max_pages):
                page_params = dict(params)
                if pag.type == "offset":
                    page_params[pag.offset_param] = offset
                    page_params[pag.limit_param] = pag.page_size
                elif pag.type == "page":
                    page_params[pag.page_param] = page
                    page_params[pag.limit_param] = pag.page_size
                elif pag.type == "cursor" and cursor is not None:
                    page_params[pag.cursor_param] = cursor

                response = await client.request(req.method, req.url, params=page_params, headers=headers, auth=basic)
                if response.is_redirect:
                    raise ConnectorConfigError(f"source answered with a redirect ({response.status_code}); "
                                               "put the final URL in the config")
                response.raise_for_status()
                records, body = self._records(response, config)

                for record in records:
                    yield record
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return

                if pag.type == "none" or not records:
                    return
                if pag.type == "offset":
                    if len(records) < pag.page_size:
                        return
                    offset += len(records)
                elif pag.type == "page":
                    if len(records) < pag.page_size:
                        return
                    page += 1
                elif pag.type == "cursor":
                    cursor = get_path(body, pag.next_cursor_path) if pag.next_cursor_path else None
                    if not cursor:
                        return


@register("http_json")
class HttpJsonConnector(_HttpConnector):
    def _records(self, response: httpx.Response, config: SourceConfig) -> tuple[list[dict[str, Any]], Any]:
        body = response.json()
        records = get_path(body, config.request.records_path)
        if records is None:
            raise ConnectorConfigError(f"records_path '{config.request.records_path}' not found in response")
        if not isinstance(records, list):
            raise ConnectorConfigError(f"records_path '{config.request.records_path}' is not a list")
        return [r for r in records if isinstance(r, dict)], body


@register("http_csv")
class HttpCsvConnector(_HttpConnector):
    def _records(self, response: httpx.Response, config: SourceConfig) -> tuple[list[dict[str, Any]], Any]:
        return list(csv.DictReader(io.StringIO(response.text))), None
