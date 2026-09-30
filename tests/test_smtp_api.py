import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from src.main import app
from src.core.permissions import get_current_user, CurrentUser

client = TestClient(app)

# Helper mock current user
def mock_super_admin():
    return CurrentUser(
        user_id="00000000-0000-0000-0000-000000000001",
        tenant_id=None,
        username="superadmin",
        email="superadmin@pbx.local",
        role="SUPER_ADMIN"
    )

def mock_tenant_admin():
    return CurrentUser(
        user_id="00000000-0000-0000-0000-000000000002",
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        username="tenantadmin",
        email="admin@aikyam.com",
        role="TENANT_ADMIN"
    )


def test_get_smtp_settings_unconfigured():
    app.dependency_overrides[get_current_user] = mock_tenant_admin
    with patch("src.api.v1.smtp.get_smtp_settings", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = (None, False)
        resp = client.get("/api/v1/settings/smtp")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert data["is_using_global_fallback"] is False
    app.dependency_overrides.clear()


def test_get_smtp_settings_admin_password():
    app.dependency_overrides[get_current_user] = mock_tenant_admin
    fake_settings = {
        "id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "smtp_host": "smtp.sendgrid.net",
        "smtp_port": 587,
        "smtp_username": "apikey",
        "smtp_password": "supersecretpassword",
        "from_email": "alerts@aikyam.com",
        "from_name": "Aikyam Voicemail",
        "use_tls": True,
        "updated_at": "2026-09-30T10:00:00Z"
    }
    with patch("src.api.v1.smtp.get_smtp_settings", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = (fake_settings, False)
        resp = client.get("/api/v1/settings/smtp")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["smtp_password"] == "supersecretpassword"
        assert data["is_using_global_fallback"] is False
    app.dependency_overrides.clear()


def test_put_smtp_settings_preserves_password():
    app.dependency_overrides[get_current_user] = mock_tenant_admin
    existing = {
        "id": "11111111-1111-1111-1111-111111111111",
        "smtp_password": "existingpassword123"
    }
    with patch("src.api.v1.smtp.execute_query_one", new_callable=AsyncMock) as mock_query_one, \
         patch("src.api.v1.smtp.execute_query", new_callable=AsyncMock) as mock_query:
        
        mock_query_one.return_value = existing
        mock_query.return_value = []

        payload = {
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_username": "user@gmail.com",
            "smtp_password": "••••••••",
            "from_email": "user@gmail.com",
            "from_name": "PBX",
            "use_tls": True
        }
        resp = client.put("/api/v1/settings/smtp", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        # Verify query was called with the existing password
        call_args = mock_query.call_args[0]
        params = call_args[1]
        assert params["password"] == "existingpassword123"
    app.dependency_overrides.clear()


def test_test_smtp_connection_endpoint():
    app.dependency_overrides[get_current_user] = mock_super_admin
    with patch("src.api.v1.smtp.send_email_smtp", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = (True, "")

        payload = {
            "to_email": "test@destination.com",
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "from_email": "pbx@example.com"
        }
        resp = client.post("/api/v1/settings/smtp/test", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
    app.dependency_overrides.clear()
