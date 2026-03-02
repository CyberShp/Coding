"""
WebSocket endpoints for real-time updates.

Features:
- Message batching for high-frequency updates
- Request deduplication for status updates
- Connection health monitoring
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Set, Optional, Any
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])

# Batch settings
BATCH_INTERVAL_MS = 100  # Batch messages every 100ms
MAX_BATCH_SIZE = 50  # Max messages per batch


class MessageBatcher:
    """Batches messages for efficient WebSocket transmission"""

    def __init__(self, channel: str, send_callback):
        self._channel = channel
        self._send_callback = send_callback
        self._queue: List[dict] = []
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Start the batcher background task"""
        self._running = True
        self._task = asyncio.create_task(self._batch_loop())

    async def stop(self):
        """Stop the batcher"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def add(self, message: dict):
        """Add a message to the batch queue"""
        async with self._lock:
            self._queue.append(message)

    async def _batch_loop(self):
        """Background loop that sends batched messages"""
        while self._running:
            try:
                await asyncio.sleep(BATCH_INTERVAL_MS / 1000)
                await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Batch loop error: {e}")

    async def _flush(self):
        """Flush queued messages as a batch"""
        async with self._lock:
            if not self._queue:
                return

            # Limit batch size
            batch = self._queue[:MAX_BATCH_SIZE]
            self._queue = self._queue[MAX_BATCH_SIZE:]

        if len(batch) == 1:
            # Single message, send directly
            await self._send_callback(self._channel, batch[0])
        else:
            # Multiple messages, send as batch
            await self._send_callback(self._channel, {
                'type': 'batch',
                'messages': batch,
                'count': len(batch),
                'timestamp': datetime.now().isoformat(),
            })


class ConnectionManager:
    """Manages WebSocket connections with batching support"""

    def __init__(self):
        self._connections: Dict[str, Set[WebSocket]] = {
            'alerts': set(),
            'status': set(),
        }
        self._lock = asyncio.Lock()
        self._batchers: Dict[str, MessageBatcher] = {}
        self._status_cache: Dict[str, Dict] = {}  # Cache for deduplication
        self._last_status_time: Dict[str, float] = {}  # Throttle status updates

    async def connect(self, websocket: WebSocket, channel: str = 'alerts'):
        """Accept and register a new connection"""
        await websocket.accept()

        async with self._lock:
            if channel not in self._connections:
                self._connections[channel] = set()
            self._connections[channel].add(websocket)

            # Start batcher if not running
            if channel not in self._batchers:
                batcher = MessageBatcher(channel, self._do_broadcast)
                self._batchers[channel] = batcher
                await batcher.start()

        logger.info(f"WebSocket connected to channel: {channel}")

    async def disconnect(self, websocket: WebSocket, channel: str = 'alerts'):
        """Remove a connection"""
        async with self._lock:
            if channel in self._connections:
                self._connections[channel].discard(websocket)

        logger.info(f"WebSocket disconnected from channel: {channel}")

    async def broadcast(self, channel: str, message: dict):
        """Queue message for batched broadcast"""
        if channel in self._batchers:
            await self._batchers[channel].add(message)
        else:
            await self._do_broadcast(channel, message)

    async def _do_broadcast(self, channel: str, message: dict):
        """Actually send message to all connections"""
        if channel not in self._connections:
            return

        dead_connections = set()

        async with self._lock:
            connections = self._connections[channel].copy()

        for websocket in connections:
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to websocket: {e}")
                dead_connections.add(websocket)

        if dead_connections:
            async with self._lock:
                self._connections[channel] -= dead_connections

    async def send_personal(self, websocket: WebSocket, message: dict):
        """Send message to a specific connection"""
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json(message)
        except Exception as e:
            logger.warning(f"Failed to send personal message: {e}")

    def get_connection_count(self, channel: str = 'alerts') -> int:
        """Get number of connections in a channel"""
        return len(self._connections.get(channel, set()))

    def should_send_status(self, array_id: str, status: Dict, throttle_ms: int = 500) -> bool:
        """Check if status update should be sent (deduplication + throttling)"""
        import time
        now = time.time() * 1000

        # Throttle check
        last_time = self._last_status_time.get(array_id, 0)
        if now - last_time < throttle_ms:
            return False

        # Deduplication check - compare with cached status
        cached = self._status_cache.get(array_id)
        if cached and cached == status:
            return False

        # Update cache
        self._status_cache[array_id] = status.copy() if isinstance(status, dict) else status
        self._last_status_time[array_id] = now
        return True


# Global connection manager
manager = ConnectionManager()


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """
    WebSocket endpoint for real-time alerts.
    
    Clients connect here to receive alert notifications as they occur.
    """
    await manager.connect(websocket, 'alerts')
    
    try:
        # Send welcome message
        await manager.send_personal(websocket, {
            'type': 'connected',
            'channel': 'alerts',
            'timestamp': datetime.now().isoformat(),
        })
        
        # Keep connection alive and handle messages
        missed_heartbeats = 0
        while True:
            try:
                # Wait for client messages (heartbeat, etc.)
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=30.0  # 30-second heartbeat interval
                )
                missed_heartbeats = 0  # Reset on any client message
                
                # Handle client messages
                if data.get('type') == 'ping':
                    await manager.send_personal(websocket, {
                        'type': 'pong',
                        'timestamp': datetime.now().isoformat(),
                    })
                    
            except asyncio.TimeoutError:
                missed_heartbeats += 1
                # Tolerate up to 3 consecutive missed heartbeats (90s total)
                if missed_heartbeats >= 3:
                    logger.warning("WebSocket alerts: client unresponsive after 90s, disconnecting")
                    break
                # Send heartbeat
                try:
                    await manager.send_personal(websocket, {
                        'type': 'heartbeat',
                        'timestamp': datetime.now().isoformat(),
                    })
                except Exception:
                    break
                
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket, 'alerts')


@router.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """
    WebSocket endpoint for array status updates.
    """
    await manager.connect(websocket, 'status')
    
    try:
        await manager.send_personal(websocket, {
            'type': 'connected',
            'channel': 'status',
            'timestamp': datetime.now().isoformat(),
        })
        
        missed_heartbeats = 0
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=30.0  # 30-second heartbeat interval
                )
                missed_heartbeats = 0
                
                if data.get('type') == 'ping':
                    await manager.send_personal(websocket, {
                        'type': 'pong',
                        'timestamp': datetime.now().isoformat(),
                    })
                    
            except asyncio.TimeoutError:
                missed_heartbeats += 1
                if missed_heartbeats >= 3:
                    logger.warning("WebSocket status: client unresponsive after 90s, disconnecting")
                    break
                try:
                    await manager.send_personal(websocket, {
                        'type': 'heartbeat',
                        'timestamp': datetime.now().isoformat(),
                    })
                except Exception:
                    break
                
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket, 'status')


async def broadcast_alert(alert: dict):
    """
    Broadcast a new alert to all connected clients.
    
    Call this function when a new alert is received.
    """
    await manager.broadcast('alerts', {
        'type': 'alert',
        'data': alert,
        'timestamp': datetime.now().isoformat(),
    })


async def broadcast_status_update(array_id: str, status: dict):
    """
    Broadcast array status update to all connected clients.
    Uses deduplication and throttling to reduce unnecessary updates.
    """
    if not manager.should_send_status(array_id, status):
        return

    await manager.broadcast('status', {
        'type': 'status_update',
        'array_id': array_id,
        'data': status,
        'timestamp': datetime.now().isoformat(),
    })


def get_manager() -> ConnectionManager:
    """Get the global connection manager"""
    return manager
