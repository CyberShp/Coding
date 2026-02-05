"""FastAPI application factory for Packet Storm Web UI."""

from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..utils.logging import get_logger

logger = get_logger("web.app")


def create_app(
    engine=None,
    config_manager=None,
    stats_collector=None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        engine: PacketStormEngine instance (shared with CLI).
        config_manager: ConfigManager instance.
        stats_collector: StatsCollector instance.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(
        title="Packet Storm",
        description="Storage Protocol Abnormal Packet Testing Tool - Web API",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )

    # CORS for Vue frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store shared instances in app state
    app.state.engine = engine
    app.state.config_manager = config_manager
    app.state.stats_collector = stats_collector

    # Register API routers
    from .api.config import router as config_router
    from .api.session import router as session_router
    from .api.anomaly import router as anomaly_router
    from .api.monitor import router as monitor_router
    from .api.dpdk import router as dpdk_router

    app.include_router(config_router, prefix="/api/config", tags=["Configuration"])
    app.include_router(session_router, prefix="/api/session", tags=["Session"])
    app.include_router(anomaly_router, prefix="/api/anomaly", tags=["Anomaly"])
    app.include_router(monitor_router, prefix="/api/monitor", tags=["Monitor"])
    app.include_router(dpdk_router, prefix="/api/dpdk", tags=["DPDK"])

    # WebSocket
    from .ws import setup_websocket
    setup_websocket(app)

    @app.get("/api/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/status")
    async def get_status():
        """Get overall system status."""
        result = {"status": "running"}
        if app.state.engine:
            result["engine"] = app.state.engine.get_status()
        if app.state.stats_collector:
            result["stats"] = app.state.stats_collector.get_snapshot()
        return result

    logger.info("FastAPI application created")
    return app


def run_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    engine=None,
    config_manager=None,
    stats_collector=None,
) -> None:
    """Run the web server.

    Args:
        host: Bind address.
        port: Bind port.
        engine: PacketStormEngine instance.
        config_manager: ConfigManager instance.
        stats_collector: StatsCollector instance.
    """
    import uvicorn

    app = create_app(engine, config_manager, stats_collector)
    uvicorn.run(app, host=host, port=port, log_level="info")
