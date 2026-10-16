import unittest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from fastapi import HTTPException
from src.api.v1.conferences import (
    list_live_conferences,
    get_conference_live,
    terminate_conference_endpoint,
    kick_conference_member_endpoint
)
from src.core.permissions import CurrentUser


class TestConferenceLiveAndControl(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tenant_id = str(uuid4())
        self.conf_id = uuid4()
        self.tenant_admin = CurrentUser(
            user_id=str(uuid4()),
            tenant_id=self.tenant_id,
            username="tadmin",
            email="tadmin@test.com",
            role="TENANT_ADMIN"
        )
        self.super_admin = CurrentUser(
            user_id=str(uuid4()),
            tenant_id=None,
            username="sadmin",
            email="sadmin@test.com",
            role="SUPER_ADMIN"
        )

    async def test_list_live_conferences(self):
        mock_confs = [
            {
                "id": self.conf_id,
                "tenant_id": self.tenant_id,
                "name": "LiveRoom1",
                "extension_number": "3001",
                "pin": "1234",
                "moderator_pin": "9999",
                "max_members": 50,
                "record_conference": False,
                "enabled": True,
                "tenant_name": "Test Tenant"
            }
        ]
        mock_live_status = {
            "name": "LiveRoom1",
            "active": True,
            "member_count": 2,
            "has_moderator": True,
            "members": [
                {"id": "1", "uuid": "u1", "caller_id_number": "1001", "is_moderator": True},
                {"id": "2", "uuid": "u2", "caller_id_number": "1002", "is_moderator": False}
            ]
        }

        with patch("src.api.v1.conferences.execute_query", return_value=mock_confs), \
             patch("src.api.v1.conferences.get_conference_live_status", return_value=mock_live_status):
            res = await list_live_conferences(tenant_id=None, current_user=self.tenant_admin)
            self.assertEqual(len(res), 1)
            self.assertTrue(res[0]["live"]["active"])
            self.assertEqual(res[0]["live"]["member_count"], 2)
            self.assertTrue(res[0]["live"]["has_moderator"])

    async def test_terminate_conference_success(self):
        mock_conf = {
            "id": self.conf_id,
            "tenant_id": self.tenant_id,
            "name": "LiveRoom1",
            "extension_number": "3001"
        }

        with patch("src.api.v1.conferences.execute_query_one", return_value=mock_conf), \
             patch("src.api.v1.conferences.terminate_conference", return_value=True) as mock_term:
            res = await terminate_conference_endpoint(self.conf_id, self.tenant_admin)
            self.assertEqual(res["status"], "terminated")
            mock_term.assert_called_once_with("LiveRoom1")

    async def test_terminate_conference_access_denied_other_tenant(self):
        mock_conf = {
            "id": self.conf_id,
            "tenant_id": str(uuid4()), # different tenant
            "name": "OtherRoom",
            "extension_number": "3002"
        }

        with patch("src.api.v1.conferences.execute_query_one", return_value=mock_conf):
            with self.assertRaises(HTTPException) as ctx:
                await terminate_conference_endpoint(self.conf_id, self.tenant_admin)
            self.assertEqual(ctx.exception.status_code, 403)

    async def test_kick_conference_member_success(self):
        mock_conf = {
            "id": self.conf_id,
            "tenant_id": self.tenant_id,
            "name": "LiveRoom1",
            "extension_number": "3001"
        }

        with patch("src.api.v1.conferences.execute_query_one", return_value=mock_conf), \
             patch("src.api.v1.conferences.kick_conference_member", return_value=True) as mock_kick:
            res = await kick_conference_member_endpoint(self.conf_id, "2", self.tenant_admin)
            self.assertEqual(res["status"], "kicked")
            mock_kick.assert_called_once_with("LiveRoom1", "2")


if __name__ == "__main__":
    unittest.main()
