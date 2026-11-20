"""HTTP routes. Kept thin: validation in schemas, logic in services."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.schemas import AdviceRequest, AdviceResponse
from app.services.advisor import build_advice
from app.services.aqi_client import CityNotFound, UpstreamError

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/advice", response_model=AdviceResponse)
async def advice(payload: AdviceRequest, request: Request) -> AdviceResponse:
    state = request.app.state
    try:
        return await build_advice(payload, state.air_client, state.explainer)
    except CityNotFound:
        raise HTTPException(
            status_code=404,
            detail="We couldn't find that city. Check the spelling or try a larger nearby city.",
        )
    except UpstreamError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Live air-quality data is unavailable right now. Please try again "
                "in a minute, or enter a PM2.5 reading from your own monitor."
            ),
        )
