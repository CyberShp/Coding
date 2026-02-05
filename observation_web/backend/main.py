"""
Observation Web Backend - Main Entry Point

FastAPI-based backend service for storage array monitoring platform.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_config
from .db.database import init_db, create_tables
from .api import arrays_router, alerts_router, query_router, ws_router
from .api.system_alerts import router as system_alerts_router
from .core.ssh_pool import get_ssh_pool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    # Startup
    logger.info("Starting Observation Web Backend...")
    
    # Initialize database
    init_db()
    await create_tables()
    logger.info("Database initialized")
    
    # Initialize SSH pool
    get_ssh_pool()
    logger.info("SSH pool initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    
    # Close all SSH connections
    ssh_pool = get_ssh_pool()
    ssh_pool.close_all()
    logger.info("SSH connections closed")


def create_app() -> FastAPI:
    """Create and configure FastAPI application"""
    config = get_config()
    
    app = FastAPI(
        title="Observation Web API",
        description="Storage Array Monitoring Platform API",
        version="1.0.0",
        lifespan=lifespan,
    )
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Register routers
    app.include_router(arrays_router, prefix="/api")
    app.include_router(alerts_router, prefix="/api")
    app.include_router(query_router, prefix="/api")
    app.include_router(system_alerts_router, prefix="/api")
    app.include_router(ws_router)
    
    # Health check endpoint
    @app.get("/health")
    async def health_check():
        return {"status": "healthy"}
    
    # API info endpoint
    @app.get("/api")
    async def api_info():
        return {
            "name": "Observation Web API",
            "version": "1.0.0",
            "endpoints": {
                "arrays": "/api/arrays",
                "alerts": "/api/alerts",
                "query": "/api/query",
                "system_alerts": "/api/system-alerts",
                "websocket_alerts": "/ws/alerts",
                "websocket_status": "/ws/status",
            }
        }
    
    return app


# Create application instance
app = create_app()


def main():
    """Run the server"""
    import uvicorn
    
    config = get_config()
    
    uvicorn.run(
        "backend.main:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.server.debug,
    )


if __name__ == "__main__":
    main()
