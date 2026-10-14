import unittest
from unittest.mock import AsyncMock
from src.core.websocket_manager import ConnectionManager

class TestWebSocketBroadcaster(unittest.IsolatedAsyncioTestCase):
    async def test_broadcast_filters_tenant(self):
        manager = ConnectionManager()
        mock_ws_admin = AsyncMock()
        mock_ws_tenant1 = AsyncMock()
        mock_ws_tenant2 = AsyncMock()

        # Connect admin (all tenants)
        await manager.connect(mock_ws_admin, tenant_id=None, is_admin=True)
        # Connect tenant 1
        await manager.connect(mock_ws_tenant1, tenant_id="tid-1", is_admin=False)
        # Connect tenant 2
        await manager.connect(mock_ws_tenant2, tenant_id="tid-2", is_admin=False)

        # Broadcast event for tenant 1
        event = {"event": "cdr.created", "data": {"call_uuid": "c-1", "tenant_id": "tid-1"}}
        await manager.broadcast(event, tenant_id="tid-1")

        mock_ws_admin.send_json.assert_called_once_with(event)
        mock_ws_tenant1.send_json.assert_called_once_with(event)
        mock_ws_tenant2.send_json.assert_not_called()

    async def test_disconnect_removes_socket(self):
        manager = ConnectionManager()
        mock_ws = AsyncMock()
        await manager.connect(mock_ws, tenant_id="tid-1", is_admin=False)
        self.assertEqual(len(manager.active_connections), 1)

        await manager.disconnect(mock_ws)
        self.assertEqual(len(manager.active_connections), 0)

    async def test_broadcast_cdr_created(self):
        manager = ConnectionManager()
        mock_ws = AsyncMock()
        await manager.connect(mock_ws, tenant_id="tid-99", is_admin=False)

        cdr = {"call_uuid": "call-123", "tenant_id": "tid-99", "direction": "inbound"}
        await manager.broadcast_cdr_created(cdr)

        mock_ws.send_json.assert_called_once_with({"event": "cdr.created", "type": "cdr.created", "data": cdr})

if __name__ == "__main__":
    unittest.main()
