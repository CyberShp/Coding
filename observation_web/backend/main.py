"""
Observation Web Backend - Main Entry Point

FastAPI-based backend service for storage array monitoring platform.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_config, __version__
from .core.system_alert import sys_error, sys_warning, sys_info
from .db.database import init_db, create_tables, Base, get_async_engine
from .api import arrays_router, alerts_router, query_router, ws_router, tags_router, alert_rules_router, audit_router
from .api.auth import router as auth_router
from .api.issues import router as issues_router
from .api.system_alerts import router as system_alerts_router
from .api.data_lifecycle import router as data_lifecycle_router
from .api.scheduler import router as scheduler_router
from .api.ingest import router as ingest_router
from .api.traffic import router as traffic_router
from .api.task_session import router as task_session_router
from .api.timeline import router as timeline_router
from .api.snapshot import router as snapshot_router
from .api.acknowledgements import router as ack_router
from .api.monitor_templates import router as monitor_templates_router
from .api.observer_configs import router as observer_configs_router
from .api.observer_templates import router as observer_templates_router
from .api.users import router as users_router
from .api.ai import router as ai_router
from .api.card_inventory import router as card_inventory_router
from .api.agent_package import router as agent_package_router
from .middleware.user_session import UserSessionMiddleware
from .core.ssh_pool import get_ssh_pool
from .core.scheduler import get_scheduler
from .core.alert_sync import start_alert_sync, stop_alert_sync
from .models.array import ArrayModel
from sqlalchemy import select

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

# Tracks the previous health state per array so we only broadcast on change
_prev_health_state: dict = {}


async def _idle_connection_cleaner():
    """Background task to clean up idle SSH connections and expired DB records."""
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
                logger.warning(f"Traffic cleanup error: {e}")

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
            except Exception as e:
                logger.warning(f"Expired ack cleanup error: {e}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Idle connection cleanup error: {e}")


async def _health_checker():
    """Lightweight health checker with faster cadence for status freshness."""
    from .core.agent_deployer import AgentDeployer
    from .core.ssh_pool import tcp_probe
    from .api.arrays import _array_status_cache
    from .api.websocket import broadcast_status_update

    check_count = 0
    while True:
        try:
            await asyncio.sleep(30)
            check_count += 1
            ssh_pool = get_ssh_pool()
            config = get_config()

            for array_id, status_obj in list(_array_status_cache.items()):
                try:
                    prev = _prev_health_state.get(array_id, {})
                    conn = ssh_pool.get_connection(array_id)
                    if not conn:
                        continue

                    reachable = await asyncio.wait_for(
                        asyncio.get_running_loop().run_in_executor(None, tcp_probe, conn.host, conn.port, 2.0),
                        timeout=3,
                    )
                    if not reachable:
                        conn._mark_disconnected()
                        status_obj.state = conn.state
                        logger.info("Health check: %s (%s) unreachable, marked disconnected", array_id, status_obj.host)
                        curr = {"state": status_obj.state.value, "agent_running": status_obj.agent_running}
                        if curr != prev:
                            _prev_health_state[array_id] = curr
                            await broadcast_status_update(array_id, {
                                "array_id": array_id,
                                "state": status_obj.state.value,
                                "agent_running": status_obj.agent_running,
                                "agent_deployed": status_obj.agent_deployed,
                                "event": "health_check",
                            })
                        continue

                    alive = await asyncio.wait_for(
                        asyncio.get_running_loop().run_in_executor(None, conn.check_alive),
                        timeout=3,
                    )
                    status_obj.state = conn.state
                    if not alive:
                        curr = {"state": status_obj.state.value, "agent_running": status_obj.agent_running}
                        if curr != prev:
                            _prev_health_state[array_id] = curr
                            await broadcast_status_update(array_id, {
                                "array_id": array_id,
                                "state": status_obj.state.value,
                                "agent_running": status_obj.agent_running,
                                "agent_deployed": status_obj.agent_deployed,
                                "event": "health_check",
                            })
                        continue

                    # Run heavier agent health checks every 10 cycles (~5 min)
                    if check_count % 10 == 0 and status_obj.agent_running:
                        deployer = AgentDeployer(conn, config)
                        still_running = await asyncio.wait_for(
                            asyncio.get_running_loop().run_in_executor(None, deployer.check_running),
                            timeout=10,
                        )
                        if not still_running:
                            status_obj.agent_running = False
                            sys_warning(
                                "health_check",
                                f"Agent stopped unexpectedly on {array_id}",
                                {"array_id": array_id, "host": status_obj.host},
                            )
                            if config.remote.auto_redeploy:
                                if await asyncio.wait_for(
                                    asyncio.get_running_loop().run_in_executor(None, deployer.check_deployed),
                                    timeout=10,
                                ):
                                    ready = await asyncio.wait_for(
                                        deployer.wait_for_ready(),
                                        timeout=1210,
                                    )
                                    if ready:
                                        result = {"ok": True, "message": "Agent became ready after SSH recovery"}
                                    else:
                                        result = await asyncio.wait_for(
                                            asyncio.get_running_loop().run_in_executor(None, deployer.start_agent),
                                            timeout=60,
                                        )
                                else:
                                    result = await asyncio.wait_for(
                                        asyncio.get_running_loop().run_in_executor(None, deployer.deploy),
                                        timeout=120,
                                    )
                                if result.get("ok"):
                                    status_obj.agent_running = True
                                    status_obj.agent_deployed = True
                                    sys_info(
                                        "health_check",
                                        f"Agent auto-redeployed on {array_id}",
                                        {"array_id": array_id, "host": status_obj.host},
                                    )

                    curr = {"state": status_obj.state.value, "agent_running": status_obj.agent_running}
                    if curr != prev:
                        _prev_health_state[array_id] = curr
                        await broadcast_status_update(array_id, {
                            "array_id": array_id,
                            "state": status_obj.state.value,
                            "agent_running": status_obj.agent_running,
                            "agent_deployed": status_obj.agent_deployed,
                            "event": "health_check",
                        })
                except Exception as e:
                    logger.warning(f"Agent health check failed for {array_id}: {e}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Health checker error: {e}")


async def _auto_reconnect_saved_arrays():
    """Try to reconnect arrays that have saved passwords after backend restart."""
    from .db.database import AsyncSessionLocal
    from .api.arrays import _get_array_status

    if AsyncSessionLocal is None:
        logger.warning("AsyncSessionLocal is unavailable, skip auto reconnect")
        return

    ssh_pool = get_ssh_pool()
    semaphore = asyncio.Semaphore(10)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ArrayModel).where(ArrayModel.saved_password.is_not(None))
        )
        candidates = [
            arr for arr in result.scalars().all()
            if (arr.saved_password or "").strip()
        ]

    if not candidates:
        logger.info("Auto reconnect: no arrays with saved password")
        return

    async def _connect_one(array: ArrayModel):
        async with semaphore:
            def _do_connect():
                conn = ssh_pool.add_connection(
                    array_id=array.array_id,
                    host=array.host,
                    port=array.port,
                    username=array.username,
                    password=array.saved_password or "",
                    key_path=array.key_path or None,
                )
                return conn.connect(), conn

            ok, conn = await asyncio.get_running_loop().run_in_executor(None, _do_connect)
            status_obj = _get_array_status(array.array_id)
            status_obj.state = conn.state
            status_obj.last_refresh = datetime.now()
            if ok:
                logger.info("Auto reconnect success: %s (%s)", array.name, array.host)
            else:
                logger.info("Auto reconnect skipped/failed: %s (%s): %s", array.name, array.host, conn.last_error)

    await asyncio.gather(*[_connect_one(arr) for arr in candidates], return_exceptions=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    # Startup
    logger.info("Starting Observation Web Backend...")
    
    # Initialize database
    init_db()
    try:
        await create_tables()
        logger.info("Database initialized")
    except Exception as e:
        logger.error("create_tables failed: %s", e, exc_info=True)
        # Fallback: create tables only (skip migrations)
        try:
            from .models import array, alert, query, lifecycle, scheduler, traffic, task_session, snapshot, tag, user_session, array_lock, alert_rule, audit_log, issue, ai_interpretation, card_inventory  # noqa: F401
            async with get_async_engine().begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Fallback: tables created without migrations")
        except Exception as e2:
            logger.critical("Cannot create database tables: %s", e2)
            raise
    
    # Initialize SSH pool
    get_ssh_pool()
    logger.info("SSH pool initialized")

    # Auto reconnect arrays that have saved password
    try:
        await _auto_reconnect_saved_arrays()
    except Exception as e:
        logger.warning("Auto reconnect on startup failed: %s", e)
    
    # Start task scheduler
    scheduler = get_scheduler()
    await scheduler.start()
    logger.info("Task scheduler started")
    
    # Start background tasks
    cleanup_task = asyncio.create_task(_idle_connection_cleaner())
    health_task = asyncio.create_task(_health_checker())
    logger.info("Idle connection cleaner started")
    logger.info("Health checker started")

    # F202: Register baseline computation job (runs every 6 hours)
    from .core.baseline import compute_baselines
    from apscheduler.triggers.interval import IntervalTrigger
    scheduler.scheduler.add_job(
        compute_baselines,
        trigger=IntervalTrigger(hours=6),
        id="baseline_computation",
        name="Adaptive Baseline Computation",
        replace_existing=True,
    )
    logger.info("Baseline computation job registered (every 6h)")

    # F202: Run baseline computation immediately on startup (don't wait 6h)
    asyncio.create_task(compute_baselines())

    # F200: Register causal rule mining job (runs every 6 hours, after baseline)
    from .core.causal import mine_causal_rules
    scheduler.scheduler.add_job(
        mine_causal_rules,
        trigger=IntervalTrigger(hours=6),
        id="causal_mining",
        name="Causal Rule Mining",
        replace_existing=True,
    )
    logger.info("Causal rule mining job registered (every 6h)")
    asyncio.create_task(mine_causal_rules())

    # Start alert sync (periodic SSH pull of alerts from connected arrays)
    start_alert_sync()
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    
    # Stop background tasks
    cleanup_task.cancel()
    health_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    try:
        await health_task
    except asyncio.CancelledError:
        pass
    
    # Stop alert sync
    stop_alert_sync()
    logger.info("Alert sync stopped")

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
        version=__version__,
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

    # Add user session tracking middleware
    app.add_middleware(UserSessionMiddleware)
    
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
    app.include_router(tags_router, prefix="/api")
    app.include_router(users_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(issues_router, prefix="/api")
    app.include_router(alert_rules_router, prefix="/api")
    app.include_router(system_alerts_router, prefix="/api")
    app.include_router(data_lifecycle_router, prefix="/api")
    app.include_router(scheduler_router, prefix="/api")
    app.include_router(ingest_router, prefix="/api")
    app.include_router(traffic_router, prefix="/api")
    app.include_router(task_session_router, prefix="/api")
    app.include_router(timeline_router, prefix="/api")
    app.include_router(snapshot_router, prefix="/api")
    app.include_router(ack_router, prefix="/api")
    app.include_router(monitor_templates_router, prefix="/api")
    app.include_router(observer_configs_router, prefix="/api")
    app.include_router(observer_templates_router, prefix="/api")
    app.include_router(ai_router, prefix="/api")
    app.include_router(card_inventory_router, prefix="/api")
    app.include_router(agent_package_router, prefix="/api")
    app.include_router(audit_router, prefix="/api")
    app.include_router(ws_router)
    
    # Health check endpoint
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "version": __version__}
    
    # API info endpoint
    @app.get("/api")
    async def api_info():
        return {
            "name": "Observation Web API",
            "version": __version__,
            "endpoints": {
                "arrays": "/api/arrays",
                "arrays_search": "/api/arrays/search",
                "tags": "/api/tags",
                "users": "/api/users",
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
                "ai_status": "/api/ai/status",
                "ai_interpret": "/api/ai/interpret-alert",
                "ai_config": "/api/ai/config",
                "ai_models": "/api/ai/models",
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
    
    configured_workers = max(1, int(getattr(config.server, "workers", 1)))
    if configured_workers > 1:
        logger.warning(
            "server.workers=%s requested, but this deployment currently uses in-memory SSH/status caches; forcing single worker",
            configured_workers,
        )

    uvicorn.run(
        "backend.main:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.server.debug,
        workers=1,
    )


if __name__ == "__main__":
    main()
