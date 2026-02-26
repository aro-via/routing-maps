import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.models.schemas import OptimizeRouteRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


@router.post("/optimize-route")
async def optimize_route(request: OptimizeRouteRequest) -> JSONResponse:
    logger.info("optimize-route called for driver_id=%s", request.driver_id)
    return JSONResponse({"status": "not implemented"}, status_code=200)


@router.get("/health")
async def health_check() -> JSONResponse:
    return JSONResponse({"status": "healthy"})
