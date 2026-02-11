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
from .core.system_alert import sys_error, sys_warning, sys_info
from .db.database import init_db, create_tables
from .api import arrays_router, alerts_router, query_router, ws_router
from .api.system_alerts import router as system_alerts_router
from .api.data_lifecycle import router as data_lifecycle_router
from .api.scheduler import router as scheduler_router
from .api.ingest import router as ingest_router
from .api.traffic import router as traffic_router
from .api.task_session import router as task_session_router
from .api.timeline import router as timeline_router
from .api.snapshot import router as snapshot_router
from .api.acknowledgements import router as ack_router
from .core.ssh_pool import get_ssh_pool
from .core.scheduler import get_scheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


async def _idle_connection_cleaner():
    """Background task to clean up idle SSH connections and check agent health"""
    from .core.agent_deployer import AgentDeployer
    from .core.ssh_pool import tcp_probe
    check_count = 0
    while True:
        try:
            await asyncio.sleep(120)  # Check every 2 minutes
            ssh_pool = get_ssh_pool()
            ssh_pool.cleanup_idle_connections(max_idle_seconds=600)  # 10 min idle timeout

            # Every cycle: cleanup expired traffic data
            try:
                from .core.traffic_store import get_traffic_store
                from .db.database import AsyncSessionLocal
                if AsyncSessionLocal:
                    async with AsyncSessionLocal() as session:
                        store = get_traffic_store()
                        await store.cleanup_expired(session)
            except Exception as e:
                logger.debug(f"Traffic cleanup error: {e}")

            # Every cycle: cleanup expired alert acknowledgements
            try:
                from .db.database import AsyncSessionLocal
                from .models.alert import AlertAckModel
                from sqlalchemy import delete as sa_delete
                from datetime import datetime as _dt
                if AsyncSessionLocal:
                    async with AsyncSessionLocal() as session:
                        result = await session.execute(
                            sa_delete(AlertAckModel).where(
                                AlertAckModel.ack_expires_at.isnot(None),
                                AlertAckModel.ack_expires_at <= _dt.now(),
                            )
                        )
                        if result.rowcount > 0:
                            await session.commit()
                            logger.info(f"Cleaned up {result.rowcount} expired alert acknowledgements")
                        else:
                            await session.commit()
            except Exception as e:
                logger.debug(f"Expired ack cleanup error: {e}")

            # Every 5 minutes (3rd iteration), check agent health on connected arrays
            check_count += 1
            if check_count % 3 == 0:  # 120s * 3 = ~360s ≈ 5 minutes
                config = get_config()
                from .api.arrays import _array_status_cache
                for array_id, status_obj in list(_array_status_cache.items()):
                    try:
                        conn = ssh_pool.get_connection(array_id)
                        if not conn:
                            continue

                        # TCP pre-check: skip SSH entirely if host unreachable
                        reachable = await asyncio.get_event_loop().run_in_executor(
                            None, tcp_probe, conn.host, conn.port, 2.0
                        )
                        if not reachable:
                            if conn.state.value == 'connected':
                                conn._mark_disconnected()
                                status_obj.state = conn.state
                                logger.info(f"Array {array_id} ({conn.host}) unreachable (TCP), marked disconnected")
                            continue

                        # TCP OK → single SSH probe (no reconnect attempts)
                        alive = conn.check_alive()
                        if not alive:
                            status_obj.state = conn.state
                            logger.info(f"SSH probe failed for {array_id} despite TCP success")
                            continue

                        # SSH alive → check agent health
                        if status_obj.agent_running:
                            deployer = AgentDeployer(conn, config)
                            still_running = deployer.check_running()
                            if not still_running:
                                status_obj.agent_running = False
                                logger.warning(f"Agent on {array_id} is no longer running")
                                sys_warning(
                                    "health_check",
                                    f"Agent stopped unexpectedly on {array_id}",
                                    {"array_id": array_id, "host": status_obj.host}
                                )

                                # Auto-redeploy if enabled
                                if config.remote.auto_redeploy:
                                    try:
                                        logger.info(f"Attempting auto-redeploy for {array_id}")
                                        # Try start first (files may still exist)
                                        if deployer.check_deployed():
                                            result = deployer.start_agent()
                                        else:
                                            # Files missing (reboot cleared them) → full deploy
                                            result = deployer.deploy()
                                        if result.get("ok"):
                                            status_obj.agent_running = True
                                            status_obj.agent_deployed = True
                                            logger.info(f"Auto-redeploy succeeded for {array_id}")
                                            sys_info(
                                                "health_check",
                                                f"Agent auto-redeployed on {array_id}",
                                                {"array_id": array_id, "host": status_obj.host}
                                            )
                                        else:
                                            logger.warning(f"Auto-redeploy failed for {array_id}: {result.get('error')}")
                                            sys_warning(
                                                "health_check",
                                                f"Agent auto-redeploy failed on {array_id}",
                                                {"array_id": array_id, "error": result.get("error", "unknown")}
                                            )
                                    except Exception as e:
                                        logger.warning(f"Auto-redeploy error for {array_id}: {e}")
                    except Exception as e:
                        logger.debug(f"Agent health check failed for {array_id}: {e}")
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
    
    # Start task scheduler
    scheduler = get_scheduler()
    await scheduler.start()
    logger.info("Task scheduler started")
    
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
    
    # Stop scheduler
    scheduler = get_scheduler()
    scheduler.stop()
    logger.info("Task scheduler stopped")
    
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
    app.include_router(data_lifecycle_router, prefix="/api")
    app.include_router(scheduler_router, prefix="/api")
    app.include_router(ingest_router, prefix="/api")
    app.include_router(traffic_router, prefix="/api")
    app.include_router(task_session_router, prefix="/api")
    app.include_router(timeline_router, prefix="/api")
    app.include_router(snapshot_router, prefix="/api")
    app.include_router(ack_router, prefix="/api")
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
        "version": "2.1.0",
        "endpoints": {
            "arrays": "/api/arrays",
            "alerts": "/api/alerts",
            "alerts_aggregated": "/api/alerts/aggregated",
            "query": "/api/query",
            "system_alerts": "/api/system-alerts",
            "data_lifecycle": "/api/data",
            "tasks": "/api/tasks",
            "test_tasks": "/api/test-tasks",
            "timeline": "/api/timeline",
            "snapshots": "/api/snapshots",
            "ingest": "/api/ingest",
            "traffic": "/api/traffic",
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
