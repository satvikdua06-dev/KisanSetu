"""Admin endpoints for plug-and-play price sources: list connectors, validate and dry-run a source.

Saving and enabling sources needs the database layer (next step); the dry run works now.
"""

from fastapi import APIRouter, HTTPException

from app.adapters.market_data.aliases import AliasResolver
from app.adapters.market_data.connectors import ConnectorConfigError, available_connectors
from app.adapters.market_data.engine import dry_run, validate_source
from app.adapters.market_data.models import IngestResult, SourceConfig

router = APIRouter(prefix="/admin/market-sources", tags=["market sources"])


@router.get("/connectors")
async def list_connectors() -> list[str]:
    return available_connectors()


@router.post("/test", response_model=IngestResult)
async def test_source(config: SourceConfig, sample_size: int = 20) -> IngestResult:
    """Fetch a small sample with this config and show mapped rows, rejected rows and unmatched names.
    Nothing is stored. Secrets are read from the server's environment by name."""
    try:
        validate_source(config)
    except ConnectorConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return await dry_run(config, aliases=AliasResolver(accept_unknown=True), sample_size=min(sample_size, 100))
