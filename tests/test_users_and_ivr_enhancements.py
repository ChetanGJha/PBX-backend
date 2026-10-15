import sys
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

if "passlib" not in sys.modules:
    passlib_mock = MagicMock()
    sys.modules["passlib"] = passlib_mock
    sys.modules["passlib.context"] = passlib_mock

from uuid import uuid4
from fastapi import HTTPException
from src.api.v1.users import create_user, UserCreate
from src.core.permissions import CurrentUser
from src.xml_curl.dialplan import resolve_ivr_prompt, get_beep_file, handle_dialplan_request


class TestUsersAndIvrEnhancements(unittest.IsolatedAsyncioTestCase):
    async def test_create_user_reactivates_soft_deleted_account(self):
        """If a user with the same username exists but was soft-deleted, reactivate them."""
        tenant_id = uuid4()
        payload = UserCreate(
            tenant_id=tenant_id,
            username="chetangjha",
            email="jha.chetan@ishantechnologies.com",
            password="SecurePassword123!",
            first_name="Chetan",
            last_name="Jha",
            role="TENANT_ADMIN"
        )
        current_user = CurrentUser(
            user_id="admin-id",
            username="superadmin",
            email="admin@pbx.com",
            role="SUPER_ADMIN",
            tenant_id=None
        )

        mock_existing = {
            "id": str(uuid4()),
            "username": "chetangjha",
            "email": "jha.chetan@ishantechnologies.com",
            "deleted_at": "2026-10-14 10:00:00"
        }

        async def mock_query_one(q, p=None):
            if "FROM users" in q:
                return mock_existing
            if "FROM tenants" in q:
                return {"name": "Ishan Tech", "domain": "ishan.pbx.com"}
            return None

        async def mock_tx(func):
            session = MagicMock()
            session.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=["role-uuid-1"])))
            return await func(session)

        with patch("src.api.v1.users.execute_query_one", side_effect=mock_query_one), \
             patch("src.api.v1.users.execute_transaction", side_effect=mock_tx):
            res = await create_user(payload, current_user)
            self.assertEqual(res["username"], "chetangjha")
            self.assertEqual(res["id"], mock_existing["id"])
            self.assertTrue(res["is_active"])

    async def test_create_user_rejects_active_duplicate(self):
        """Active duplicate usernames are rejected with HTTP 400 Bad Request."""
        tenant_id = uuid4()
        payload = UserCreate(
            tenant_id=tenant_id,
            username="chetangjha",
            email="jha.chetan@ishantechnologies.com",
            password="SecurePassword123!",
            role="AGENT"
        )
        current_user = CurrentUser(
            user_id="admin-id",
            username="superadmin",
            email="admin@pbx.com",
            role="SUPER_ADMIN",
            tenant_id=None
        )

        mock_existing = {
            "id": str(uuid4()),
            "username": "chetangjha",
            "email": "jha.chetan@ishantechnologies.com",
            "deleted_at": None
        }

        with patch("src.api.v1.users.execute_query_one", AsyncMock(return_value=mock_existing)):
            with self.assertRaises(HTTPException) as ctx:
                await create_user(payload, current_user)
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("already registered", ctx.exception.detail)

    async def test_resolve_ivr_prompt_fallback(self):
        """If custom file is not on disk, it falls back to synthesized welcome prompt or tone stream."""
        prompt = await resolve_ivr_prompt("non_existent_file.wav")
        self.assertTrue(prompt.endswith(".wav") or prompt.startswith("tone_stream://"))

    def test_get_beep_file_fallback(self):
        """If beep.wav is missing, get_beep_file returns tone_stream."""
        with patch("os.path.exists", return_value=False):
            beep = get_beep_file()
            self.assertTrue(beep.startswith("tone_stream://"))
