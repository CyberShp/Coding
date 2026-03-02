"""API routes"""
from .arrays import router as arrays_router
from .alerts import router as alerts_router
from .query import router as query_router
from .websocket import router as ws_router
from .tags import router as tags_router
from .alert_rules import router as alert_rules_router
from .audit import router as audit_router
