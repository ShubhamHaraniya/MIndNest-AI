"""Liveness and readiness probes."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadyResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness: the process is up. Does not touch any dependency."""
    return HealthResponse(status="ok", service="mindnest-api", version="0.1.0")


@router.get("/ready", response_model=ReadyResponse)
async def ready(request: Request) -> ReadyResponse:
    """Readiness: the database accepts connections."""
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database is not reachable.") from exc
    return ReadyResponse(status="ok", database="ok")
