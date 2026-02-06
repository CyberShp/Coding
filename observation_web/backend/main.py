"""
Observation Web Backend - Main Entry Point

FastAPI-based backend service for storage array monitoring platform.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_config
from .core.system_alert import sys_error, sys_warning
from .db.database import init_db, create_tables
from .api import arrays_router, alerts_router, query_router, ws_router
from .api.system_alerts import router as system_alerts_router
from .api.ingest import router as ingest_router
from .core.ssh_pool import get_ssh_pool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


async def _idle_connection_cleaner():
    """Background task to clean up idle SSH connections"""
    while True:
        try:
            await asyncio.sleep(120)  # Check every 2 minutes
            ssh_pool = get_ssh_pool()
            ssh_pool.cleanup_idle_connections(max_idle_seconds=600)  # 10 min idle timeout
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Idle connection cleanup error: {e}")


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
    
    # Start background idle connection cleaner
    cleanup_task = asyncio.create_task(_idle_connection_cleaner())
    logger.info("Idle connection cleaner started")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    
    # Stop background tasks
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    
    # Close all SSH connections
    ssh_pool = get_ssh_pool()
    ssh_pool.close_all()
    logger.info("SSH connections closed")


class ErrorTrackingMiddleware(BaseHTTPMiddleware):
    """Middleware to track errors and slow requests"""
    
    async def dispatch(self, request: Request, call_next):
        import time
        start_time = time.time()
        
        try:
            response = await call_next(request)
            
            # Track slow requests (>5 seconds)
            duration = time.time() - start_time
            if duration > 5:
                sys_warning(
                    "http",
                    f"Slow request: {request.method} {request.url.path}",
                    {"duration_seconds": round(duration, 2), "status_code": response.status_code}
                )
            
            return response
            
        except Exception as e:
            # Log unhandled exceptions to system alerts
            sys_error(
                "http",
                f"Unhandled exception: {request.method} {request.url.path}",
                {"error": str(e), "path": str(request.url)},
                exception=e
            )
            raise


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
    
    # Add error tracking middleware
    app.add_middleware(ErrorTrackingMiddleware)
    
    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        sys_error(
            "api",
            f"API error: {request.method} {request.url.path}",
            {"error": str(exc), "path": str(request.url)},
            exception=exc
        )
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal server error: {str(exc)}"}
        )
    
    # Register routers
    app.include_router(arrays_router, prefix="/api")
    app.include_router(alerts_router, prefix="/api")
    app.include_router(query_router, prefix="/api")
    app.include_router(system_alerts_router, prefix="/api")
    app.include_router(ingest_router, prefix="/api")
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
            "version": "1.1.0",
            "endpoints": {
                "arrays": "/api/arrays",
                "alerts": "/api/alerts",
                "query": "/api/query",
                "system_alerts": "/api/system-alerts",
                "ingest": "/api/ingest",
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
