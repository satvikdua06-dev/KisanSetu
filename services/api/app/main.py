"""KisanSetu API entry point."""

from fastapi import FastAPI

from app.api.market_sources import router as market_sources_router

app = FastAPI(title="KisanSetu API", version="0.1.0")
app.include_router(market_sources_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
