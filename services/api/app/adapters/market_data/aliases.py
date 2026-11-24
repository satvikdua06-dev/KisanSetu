"""Match the names a source uses ("Tomato", "TOMATO (Hybrid)", "Ahmedabad APMC") to our IDs.

Names that don't match are not dropped: the engine sends them to the review queue.
Backed by in-memory dicts here; the database-backed version reads commodity_alias / market_alias.
"""

import re


def normalise_name(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"\(.*?\)", "", name)  # drop bracketed qualifiers
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


class AliasResolver:
    def __init__(
        self,
        commodities: dict[str, str] | None = None,
        markets: dict[str, str] | None = None,
        *,
        accept_unknown: bool = False,
    ):
        """`commodities` and `markets` map raw names to IDs. With `accept_unknown`, unmatched names
        become their normalised form (useful for dry runs before aliases are set up)."""
        self._commodities = {normalise_name(k): v for k, v in (commodities or {}).items()}
        self._markets = {normalise_name(k): v for k, v in (markets or {}).items()}
        self.accept_unknown = accept_unknown

    def commodity_id(self, raw: str) -> str | None:
        return self._resolve(self._commodities, raw)

    def market_id(self, raw: str) -> str | None:
        return self._resolve(self._markets, raw)

    def _resolve(self, table: dict[str, str], raw: str) -> str | None:
        key = normalise_name(raw)
        if key in table:
            return table[key]
        return key.replace(" ", "-") if self.accept_unknown else None
