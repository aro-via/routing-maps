import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import configure_logging, settings
from app.api.routes import router
from app.websocket.handlers import ws_router

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Log startup and shutdown events."""
    logger.info(
        "Route Optimizer starting up — ENV=%s LOG_LEVEL=%s",
        settings.ENV,
        settings.LOG_LEVEL,
    )
    yield
    logger.info("Route Optimizer shutting down")


app = FastAPI(
    title="Route Optimizer API",
    description="HIPAA-compliant NEMT route optimization using OR-Tools and Google Maps.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)
app.include_router(ws_router)
