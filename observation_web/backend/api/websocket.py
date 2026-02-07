"""
WebSocket endpoints for real-time updates.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manages WebSocket connections"""
    
    def __init__(self):
        # Active connections by channel
        self._connections: Dict[str, Set[WebSocket]] = {
            'alerts': set(),
            'status': set(),
        }
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, channel: str = 'alerts'):
        """Accept and register a new connection"""
        await websocket.accept()
        
        async with self._lock:
            if channel not in self._connections:
                self._connections[channel] = set()
            self._connections[channel].add(websocket)
        
        logger.info(f"WebSocket connected to channel: {channel}")
    
    async def disconnect(self, websocket: WebSocket, channel: str = 'alerts'):
        """Remove a connection"""
        async with self._lock:
            if channel in self._connections:
                self._connections[channel].discard(websocket)
        
        logger.info(f"WebSocket disconnected from channel: {channel}")
    
    async def broadcast(self, channel: str, message: dict):
        """Broadcast message to all connections in a channel"""
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
        
        # Clean up dead connections
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
    """
    await manager.broadcast('status', {
        'type': 'status_update',
        'array_id': array_id,
        'data': status,
        'timestamp': datetime.now().isoformat(),
    })


def get_manager() -> ConnectionManager:
    """Get the global connection manager"""
    return manager
