"""
Backend Startup Tests

验证后端模块能够正确导入和启动。
运行方式: python -m pytest tests/test_startup.py -v
或者直接: python tests/test_startup.py
"""

import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_config_import():
    """Test: 配置模块可以正确导入"""
    try:
        from backend.config import get_config, AppConfig
        config = get_config()
        assert config is not None
        assert hasattr(config, 'server')
        assert hasattr(config, 'ssh')
        assert hasattr(config, 'database')
        assert hasattr(config, 'remote')
        print("✓ Config module import OK")
        return True
    except Exception as e:
        print(f"✗ Config import failed: {e}")
        return False


def test_models_import():
    """Test: 数据模型可以正确导入"""
    try:
        from backend.models.alert import Alert, AlertCreate, AlertResponse
        from backend.models.array import Array, ArrayCreate
        from backend.models.query import QueryTemplate, QueryTemplateCreate
        from backend.models.lifecycle import SyncState, ImportRequest
        from backend.models.scheduler import ScheduledTaskModel, ScheduledTaskResponse
        print("✓ Models import OK")
        return True
    except Exception as e:
        print(f"✗ Models import failed: {e}")
        return False


def test_core_modules_import():
    """Test: 核心模块可以正确导入"""
    try:
        from backend.core.ssh_pool import SSHPool, SSHConnection, get_ssh_pool
        from backend.core.agent_deployer import AgentDeployer
        from backend.core.system_alert import sys_error, sys_warning
        from backend.core.alert_store import AlertStore, get_alert_store
        from backend.core.query_engine import QueryEngine
        from backend.core.data_lifecycle import DataLifecycleManager
        from backend.core.scheduler import get_scheduler
        print("✓ Core modules import OK")
        return True
    except Exception as e:
        print(f"✗ Core modules import failed: {e}")
        return False


def test_api_routers_import():
    """Test: API 路由器可以正确导入"""
    try:
        from backend.api.arrays import router as arrays_router
        from backend.api.alerts import router as alerts_router
        from backend.api.query import router as query_router
        from backend.api.ingest import router as ingest_router
        from backend.api.data_lifecycle import router as data_lifecycle_router
        from backend.api.scheduler import router as scheduler_router
        from backend.api.system_alerts import router as system_alerts_router
        from backend.api.websocket import router as ws_router
        print("✓ API routers import OK")
        return True
    except Exception as e:
        print(f"✗ API routers import failed: {e}")
        return False


def test_database_import():
    """Test: 数据库模块可以正确导入"""
    try:
        from backend.db.database import get_database_url, init_db, get_db
        url = get_database_url()
        assert url is not None
        assert "sqlite" in url
        print("✓ Database module import OK")
        return True
    except Exception as e:
        print(f"✗ Database import failed: {e}")
        return False


def test_main_app_import():
    """Test: 主应用可以正确导入"""
    try:
        from backend.main import create_app, app
        assert app is not None
        assert hasattr(app, 'routes')
        print("✓ Main app import OK")
        return True
    except Exception as e:
        print(f"✗ Main app import failed: {e}")
        return False


def test_fastapi_app_routes():
    """Test: FastAPI 应用路由已注册"""
    try:
        from backend.main import app
        
        # Check that key routes exist
        route_paths = [str(route.path) for route in app.routes if hasattr(route, 'path')]
        
        expected_routes = [
            '/health',
            '/api',
        ]
        
        for route in expected_routes:
            if route not in route_paths:
                print(f"✗ Missing route: {route}")
                return False
        
        # Check API prefix routes exist
        api_routes = [r for r in route_paths if r.startswith('/api/')]
        if len(api_routes) < 5:
            print(f"✗ Too few API routes: {len(api_routes)}")
            return False
        
        print(f"✓ FastAPI routes registered ({len(api_routes)} API routes)")
        return True
    except Exception as e:
        print(f"✗ Route check failed: {e}")
        return False


def test_ssh_pool_functionality():
    """Test: SSH 连接池基本功能"""
    try:
        from backend.core.ssh_pool import SSHPool
        
        pool = SSHPool()
        
        # Test that pool methods exist
        assert hasattr(pool, 'get_connection')
        assert hasattr(pool, 'add_connection')
        assert hasattr(pool, 'close_all')
        assert hasattr(pool, 'batch_execute')
        assert hasattr(pool, 'cleanup_idle_connections')
        assert hasattr(pool, 'get_stats')
        
        # Test get_stats
        stats = pool.get_stats()
        assert 'total_connections' in stats
        
        print("✓ SSH pool functionality OK")
        return True
    except Exception as e:
        print(f"✗ SSH pool test failed: {e}")
        return False


def test_agent_deployer_functionality():
    """Test: Agent 部署器基本功能"""
    try:
        from backend.core.agent_deployer import AgentDeployer, AGENT_PID_FILE, AGENT_START_LOG
        
        # Check constants are defined
        assert AGENT_PID_FILE is not None
        assert AGENT_START_LOG is not None
        
        # Check class methods
        assert hasattr(AgentDeployer, 'deploy')
        assert hasattr(AgentDeployer, 'start_agent')
        assert hasattr(AgentDeployer, 'stop_agent')
        assert hasattr(AgentDeployer, 'check_running')
        assert hasattr(AgentDeployer, 'get_agent_status')
        
        print("✓ Agent deployer functionality OK")
        return True
    except Exception as e:
        print(f"✗ Agent deployer test failed: {e}")
        return False


def test_ingest_api():
    """Test: Ingest API 模块"""
    try:
        from backend.api.ingest import router, get_metrics_for_ip, get_all_metrics_sources
        
        # Test helper functions
        sources = get_all_metrics_sources()
        assert isinstance(sources, list)
        
        metrics = get_metrics_for_ip("test_ip")
        assert isinstance(metrics, list)
        
        print("✓ Ingest API OK")
        return True
    except Exception as e:
        print(f"✗ Ingest API test failed: {e}")
        return False


def run_all_tests():
    """运行所有测试"""
    print("=" * 50)
    print("Observation Web Backend - Startup Tests")
    print("=" * 50)
    print()
    
    tests = [
        test_config_import,
        test_models_import,
        test_core_modules_import,
        test_api_routers_import,
        test_database_import,
        test_main_app_import,
        test_fastapi_app_routes,
        test_ssh_pool_functionality,
        test_agent_deployer_functionality,
        test_ingest_api,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} crashed: {e}")
            failed += 1
    
    print()
    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
