import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("pbx.websocket.manager")

class ConnectionManager:
    def __init__(self):
        # Maps WebSocket -> dict(tenant_id=..., is_admin=...)
        self.active_connections: Dict[Any, Dict[str, Any]] = {}

    async def connect(self, websocket: Any, tenant_id: Optional[str] = None, is_admin: bool = False):
        try:
            if hasattr(websocket, "accept"):
                await websocket.accept()
        except Exception as e:
            logger.debug(f"Socket accept: {e}")
        self.active_connections[websocket] = {
            "tenant_id": str(tenant_id) if tenant_id else None,
            "is_admin": is_admin
        }
        logger.info(f"WebSocket client connected. Active: {len(self.active_connections)} (admin={is_admin}, tenant={tenant_id})")

    async def disconnect(self, websocket: Any):
        if websocket in self.active_connections:
            del self.active_connections[websocket]
            logger.info(f"WebSocket client disconnected. Active: {len(self.active_connections)}")

    async def broadcast(self, event: dict, tenant_id: Optional[str] = None):
        """
        Broadcasts event to clients.
        If tenant_id is specified: sends to super-admins and clients belonging to tenant_id.
        """
        stale = []
        for ws, meta in list(self.active_connections.items()):
            try:
                if meta["is_admin"] or not tenant_id or meta["tenant_id"] == str(tenant_id):
                    await ws.send_json(event)
            except Exception as e:
                logger.warning(f"Error sending event to websocket: {e}")
                stale.append(ws)

        for ws in stale:
            await self.disconnect(ws)

    async def broadcast_cdr_created(self, cdr_data: dict):
        event = {
            "event": "cdr.created",
            "type": "cdr.created",
            "data": cdr_data
        }
        target_tenant = cdr_data.get("tenant_id")
        await self.broadcast(event, tenant_id=target_tenant)

ws_manager = ConnectionManager()
