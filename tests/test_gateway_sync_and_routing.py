import pytest
from xml.etree import ElementTree as ET
from unittest.mock import patch, AsyncMock
from src.services.gateway_sync import (
    generate_gateway_xml,
    generate_sofia_conf_xml,
    sync_gateway_file,
    remove_gateway_file
)
from src.xml_curl.dialplan import handle_dialplan_request


def test_generate_gateway_xml_with_credentials():
    gw = {
        "name": "carrier_alpha",
        "proxy": "sip.carrier-alpha.com:5060",
        "username": "alpharoute",
        "password": "SecretPassword123",
        "realm": "carrier-alpha.com",
        "from_domain": "carrier-alpha.com",
        "codecs": "PCMU,PCMA,G722",
        "register": True,
        "caller_id_in_from": True
    }
    xml_str = generate_gateway_xml(gw)
    root = ET.fromstring(xml_str)
    
    assert root.tag == "include"
    gw_elem = root.find("gateway")
    assert gw_elem is not None
    assert gw_elem.attrib.get("name") == "carrier_alpha"
    
    params = {p.attrib.get("name"): p.attrib.get("value") for p in gw_elem.findall("param")}
    assert params.get("proxy") == "sip.carrier-alpha.com:5060"
    assert params.get("username") == "alpharoute"
    assert params.get("password") == "SecretPassword123"
    assert params.get("realm") == "carrier-alpha.com"
    assert params.get("from-domain") == "carrier-alpha.com"
    assert params.get("register") == "true"
    assert params.get("caller-id-in-from") == "true"
    assert params.get("codec-prefs") == "PCMU,PCMA,G722"


def test_generate_gateway_xml_ip_based():
    gw = {
        "name": "carrier_ip_auth",
        "proxy": "198.51.100.20",
        "username": None,
        "password": None,
        "realm": None,
        "from_domain": None,
        "codecs": "PCMU,PCMA",
        "register": False,
        "caller_id_in_from": False
    }
    xml_str = generate_gateway_xml(gw)
    root = ET.fromstring(xml_str)
    gw_elem = root.find("gateway")
    assert gw_elem is not None
    params = {p.attrib.get("name"): p.attrib.get("value") for p in gw_elem.findall("param")}
    assert params.get("proxy") == "198.51.100.20"
    assert params.get("register") == "false"
    assert "username" not in params
    assert "password" not in params


def test_generate_sofia_conf_xml():
    gateways = [
        {
            "name": "gw_tenant1",
            "proxy": "sip.provider1.com",
            "username": "user1",
            "password": "pass1",
            "realm": "provider1.com",
            "from_domain": "provider1.com",
            "codecs": "PCMU,PCMA",
            "register": True,
            "caller_id_in_from": False
        },
        {
            "name": "gw_tenant2",
            "proxy": "sip.provider2.com",
            "username": None,
            "password": None,
            "realm": None,
            "from_domain": None,
            "codecs": "PCMU,PCMA",
            "register": False,
            "caller_id_in_from": True
        }
    ]
    xml_str = generate_sofia_conf_xml(gateways)
    root = ET.fromstring(xml_str)
    
    # Check document structure
    assert root.tag == "document"
    config = root.find(".//configuration[@name='sofia.conf']")
    assert config is not None
    
    # Check external profile contains gateways
    ext_profile = config.find(".//profile[@name='external']")
    assert ext_profile is not None
    gw_elements = ext_profile.findall(".//gateway")
    assert len(gw_elements) == 2
    gw_names = [g.attrib.get("name") for g in gw_elements]
    assert "gw_tenant1" in gw_names
    assert "gw_tenant2" in gw_names


@pytest.mark.asyncio
async def test_dialplan_outbound_routes_via_assigned_tenant_gateway():
    form_data = {
        "Caller-Context": "tenant-11111111-1111-1111-1111-111111111111",
        "Caller-Destination-Number": "918005551234",
        "Caller-Caller-ID-Number": "1001",
        "Caller-Caller-ID-Name": "Alice",
        "variable_tenant_id": "11111111-1111-1111-1111-111111111111",
        "domain": "tenant1.pbx.local"
    }

    # Mock execute_query_one to return the tenant's assigned gateway
    mock_gw = {
        "id": "22222222-2222-2222-2222-222222222222",
        "name": "tenant1_dedicated_gw",
        "priority": 1,
        "allow_international": True,
        "caller_id_policy": "tenant_default"
    }

    async def mock_query_one(query, params=None):
        if "tenant_gateways" in query or "gateways" in query:
            return mock_gw
        return None

    with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_query_one):
        xml_response = await handle_dialplan_request(form_data)
        assert xml_response != ""
        root = ET.fromstring(xml_response)
        
        # Check bridge action data points to the assigned gateway
        bridge_action = root.find(".//action[@application='bridge']")
        assert bridge_action is not None
        bridge_data = bridge_action.attrib.get("data", "")
        assert "sofia/gateway/tenant1_dedicated_gw/18005551234" in bridge_data


@pytest.mark.asyncio
async def test_xml_curl_sofia_conf_configuration():
    from httpx import AsyncClient, ASGITransport
    from src.main import app
    
    mock_gws = [
        {
            "name": "acme_sip_gateway",
            "proxy": "10.0.0.50:5060",
            "username": "acme_user",
            "password": "secret_password",
            "realm": "10.0.0.50",
            "from_domain": "10.0.0.50",
            "codecs": "PCMU,PCMA",
            "register": True,
            "caller_id_in_from": True
        }
    ]
    
    async def mock_execute_query(query, params=None):
        return mock_gws

    with patch("src.xml_curl.router.execute_query", side_effect=mock_execute_query):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/freeswitch/xml", data={
                "section": "configuration",
                "key_name": "name",
                "key_value": "sofia.conf"
            })
            assert resp.status_code == 200
            assert "text/xml" in resp.headers.get("content-type", "")
            root = ET.fromstring(resp.text)
            assert root.tag == "document"
            gw_node = root.find(".//profile[@name='external']//gateway[@name='acme_sip_gateway']")
            assert gw_node is not None
            params = {p.attrib.get("name"): p.attrib.get("value") for p in gw_node.findall("param")}
            assert params.get("proxy") == "10.0.0.50:5060"
            assert params.get("username") == "acme_user"
            assert params.get("caller-id-in-from") == "true"


@pytest.mark.asyncio
async def test_create_gateway_api_triggers_sync():
    from httpx import AsyncClient, ASGITransport
    from src.main import app
    from src.core.permissions import get_current_user, CurrentUser
    from uuid import uuid4

    test_user = CurrentUser(
        user_id=str(uuid4()),
        tenant_id=None,
        username="superadmin",
        email="admin@pbx.local",
        role="SUPER_ADMIN"
    )

    app.dependency_overrides[get_current_user] = lambda: test_user

    created_row = {
        "id": str(uuid4()),
        "name": "new_carrier_gw",
        "proxy": "10.0.0.99",
        "username": "user99",
        "password": "pwd",
        "realm": "10.0.0.99",
        "from_domain": "10.0.0.99",
        "codecs": "PCMU,PCMA",
        "register": True,
        "caller_id_in_from": True,
        "enabled": True,
        "created_at": "2026-10-13 12:00:00"
    }

    with patch("src.api.v1.gateways.execute_query_one", AsyncMock(return_value=created_row)), \
         patch("src.api.v1.gateways.sync_gateway_file") as mock_sync, \
         patch("src.api.v1.gateways.reload_freeswitch_gateways") as mock_reload:
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post("/api/v1/gateways", json={
                "name": "new_carrier_gw",
                "proxy": "10.0.0.99",
                "username": "user99",
                "password": "pwd",
                "caller_id_in_from": True
            })
            assert res.status_code == 201
            assert mock_sync.called
            assert mock_reload.called

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_gateway_api_removes_file_and_rescans():
    from httpx import AsyncClient, ASGITransport
    from src.main import app
    from src.core.permissions import get_current_user, CurrentUser
    from uuid import uuid4

    test_user = CurrentUser(
        user_id=str(uuid4()),
        tenant_id=None,
        username="superadmin",
        email="admin@pbx.local",
        role="SUPER_ADMIN"
    )

    app.dependency_overrides[get_current_user] = lambda: test_user
    gw_id = uuid4()
    existing_row = {"id": str(gw_id), "name": "gw_to_delete"}

    with patch("src.api.v1.gateways.execute_query_one", AsyncMock(return_value=existing_row)), \
         patch("src.api.v1.gateways.execute_query", AsyncMock(return_value=None)), \
         patch("src.api.v1.gateways.remove_gateway_file") as mock_remove, \
         patch("src.api.v1.gateways.reload_freeswitch_gateways") as mock_reload:

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.delete(f"/api/v1/gateways/{gw_id}")
            assert res.status_code == 204
            mock_remove.assert_called_once_with("gw_to_delete")
            assert mock_reload.called

    app.dependency_overrides.clear()



