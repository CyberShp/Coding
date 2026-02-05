"""WebSocket endpoint for real-time statistics streaming."""

import asyncio
import json
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from ..utils.logging import get_logger

logger = get_logger("web.ws")


class ConnectionManager:
    """Manages WebSocket connections for real-time stats broadcasting."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket client connected (%d total)", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a disconnected WebSocket."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("WebSocket client disconnected (%d remaining)", len(self.active_connections))

    async def broadcast(self, data: dict) -> None:
        """Broadcast data to all connected clients."""
        message = json.dumps(data)
        disconnected = []

        for conn in self.active_connections:
            try:
                await conn.send_text(message)
            except Exception:
                disconnected.append(conn)

        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


def setup_websocket(app: FastAPI) -> None:
    """Setup WebSocket endpoint on the FastAPI app.

    Args:
        app: FastAPI application instance.
    """

    @app.websocket("/ws/stats")
    async def stats_websocket(websocket: WebSocket):
        """WebSocket endpoint streaming real-time statistics.

        Sends stats snapshots every second to connected clients.
        """
        await manager.connect(websocket)
        try:
            while True:
                # Get stats from the engine
                stats = {}
                if app.state.stats_collector:
                    stats = app.state.stats_collector.get_snapshot()
                elif app.state.engine and app.state.engine.session:
                    stats = app.state.engine.session.stats.to_dict()

                await websocket.send_json({
                    "type": "stats_update",
                    "data": stats,
                })

                # Wait for 1 second or client message
                try:
                    # Non-blocking check for client messages
                    data = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=1.0,
                    )
                    # Handle client commands if any
                    await _handle_client_message(app, websocket, data)
                except asyncio.TimeoutError:
                    pass  # Normal: just send next update

        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception as e:
            logger.debug("WebSocket error: %s", e)
            manager.disconnect(websocket)


async def _handle_client_message(app: FastAPI, websocket: WebSocket, message: str) -> None:
    """Handle incoming WebSocket messages from clients.

    Supports commands like:
    - {"action": "start"}: Start sending
    - {"action": "stop"}: Stop sending
    - {"action": "pause"}: Pause
    - {"action": "resume"}: Resume
    """
    try:
        data = json.loads(message)
        action = data.get("action")
        engine = app.state.engine

        if engine is None:
            await websocket.send_json({"type": "error", "message": "Engine not initialized"})
            return

        if action == "start":
            engine.setup()
            engine.start()
            await websocket.send_json({"type": "ack", "action": "started"})
        elif action == "stop":
            engine.stop()
            await websocket.send_json({"type": "ack", "action": "stopped"})
        elif action == "pause":
            engine.pause()
            await websocket.send_json({"type": "ack", "action": "paused"})
        elif action == "resume":
            engine.resume()
            await websocket.send_json({"type": "ack", "action": "resumed"})
        else:
            await websocket.send_json({"type": "error", "message": f"Unknown action: {action}"})

    except json.JSONDecodeError:
        await websocket.send_json({"type": "error", "message": "Invalid JSON"})
