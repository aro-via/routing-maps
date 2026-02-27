import logging

import redis
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.config import settings
from app.models.schemas import OptimizeRouteRequest, OptimizeRouteResponse
from app.optimizer.pipeline import run_optimization

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


@router.post("/optimize-route", response_model=OptimizeRouteResponse)
async def optimize_route(request: OptimizeRouteRequest) -> OptimizeRouteResponse:
    """Optimise a multi-stop pickup route using VRPTW and real-time traffic data.

    Delegates entirely to run_optimization(); translates pipeline exceptions
    into appropriate HTTP status codes.
    Returns HTTP 503 if Google Maps is unavailable, 422 if no feasible route exists.
    """
    logger.info("optimize-route: driver_id=%s stops=%d", request.driver_id, len(request.stops))
    try:
        return await run_optimization(
            driver_id=request.driver_id,
            driver_location=request.driver_location,
            stops=request.stops,
            departure_time=request.departure_time,
        )
    except ValueError as exc:
        logger.warning("VRP no feasible solution: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("Optimization pipeline failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Failed to fetch travel times from Google Maps API. Try again shortly.",
        )


@router.get("/health")
async def health_check() -> JSONResponse:
    """Return service health: Redis connectivity and Maps API key presence."""
    # Redis connectivity
    redis_status = "unavailable"
    try:
        r = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            socket_connect_timeout=1,
        )
        r.ping()
        redis_status = "ok"
    except Exception:
        pass

    # Google Maps API key presence (do not make a live call on health check)
    maps_status = "configured" if settings.GOOGLE_MAPS_API_KEY else "missing"

    return JSONResponse(
        {"status": "healthy", "redis": redis_status, "maps_api": maps_status}
    )
