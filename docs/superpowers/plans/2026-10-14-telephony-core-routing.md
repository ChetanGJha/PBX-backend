# Sub-Project 1: Core Telephony, Dialplan & Call Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix FreeSWITCH internal extension calling, preload `mod_callcenter` with Music on Hold, fix inbound DID routing (to extensions, queues, and hunt groups), and implement conference PIN-authenticated dialplans.

**Architecture:** Use FreeSWITCH native Sofia registration bridging and module preloading (`mod_callcenter` and `mod_conference`). Generate dynamic XML dialplans via FastAPI `xml_curl` for internal calls, inbound DIDs, and interactive conference PIN authentication. Add tenant-level internal calling policy toggle in backend and frontend.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy / asyncpg, PostgreSQL, FreeSWITCH 1.10 XML-CURL / Sofia, React / TypeScript.

**Spec:** [docs/superpowers/specs/2026-10-14-telephony-core-routing-design.md](file:///Users/tejaspatil/PBX/PBX-backend/docs/superpowers/specs/2026-10-14-telephony-core-routing-design.md)

## Global Constraints
- Target FreeSWITCH version: FreeSWITCH 1.10.x running in Docker container `pbx_freeswitch`.
- FreeSWITCH SIP profiles must remain intact (`external` on 5080 and `external-crossconnect` on 5090).
- FreeSWITCH config directory: `config/freeswitch/` mounted to `/etc/freeswitch/`.
- Frontend design tokens must adhere to [DESIGN_SYSTEM.md](file:///Users/tejaspatil/PBX/PBX-frontend/DESIGN_SYSTEM.md).

## Review Focus
1. Disabled internal calling returning fast reject: when `allow_internal_calls` is `false`, FreeSWITCH must immediately execute `respond(403 Forbidden - Internal Calling Disabled)` and `hangup(CALL_REJECTED)`.
2. Extension registration domain mismatch: internal calls must not depend on ESL socket checks (`check_registered_domain`); Sofia must bridge directly to `user/{ext}@{callee_domain}` with `continue_on_fail=true`.
3. Inbound carrier calls resolving tenant SIP domain: when calls arrive from external gateway IP, the extension bridge must use the tenant's SIP domain instead of the carrier's IP.
4. Callcenter queue hold music: when callers enter a queue, `moh-sound=local_stream://moh` must be active.
5. Conference PIN security: invalid PINs must retry up to 3 times before hangup; moderator PIN must enter room with `+flags{moderator}`.

---

### Task 1: Preload `mod_callcenter` & Configure Queues with Music on Hold

**Files:**
- Modify: `config/freeswitch/autoload_configs/modules.conf.xml:22-36`
- Create: `config/freeswitch/autoload_configs/callcenter.conf.xml`
- Test: `tests/test_callcenter_config.py`

**Interfaces:**
- Produces: FreeSWITCH configuration with `mod_callcenter` preloaded, `callcenter.conf.xml` with queue profiles using `local_stream://moh`.

- [ ] **Step 1: Write test for FreeSWITCH module and callcenter configuration**

```python
# tests/test_callcenter_config.py
import xml.etree.ElementTree as ET
import os

def test_modules_conf_loads_callcenter():
    tree = ET.parse("config/freeswitch/autoload_configs/modules.conf.xml")
    root = tree.getroot()
    modules = [m.attrib.get("module") for m in root.findall(".//load")]
    assert "mod_callcenter" in modules

def test_callcenter_conf_structure():
    assert os.path.exists("config/freeswitch/autoload_configs/callcenter.conf.xml")
    tree = ET.parse("config/freeswitch/autoload_configs/callcenter.conf.xml")
    root = tree.getroot()
    moh_params = root.findall(".//param[@name='moh-sound']")
    assert len(moh_params) > 0
    assert any("local_stream://moh" in p.attrib.get("value", "") for p in moh_params)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_callcenter_config.py -v`
Expected: FAIL (assertion error or file not found)

- [ ] **Step 3: Update `modules.conf.xml` and create `callcenter.conf.xml`**

In `config/freeswitch/autoload_configs/modules.conf.xml`, add:
```xml
    <load module="mod_callcenter"/>
```
Create `config/freeswitch/autoload_configs/callcenter.conf.xml` declaring standard queue profiles with `moh-sound="local_stream://moh"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_callcenter_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add config/freeswitch/autoload_configs/modules.conf.xml config/freeswitch/autoload_configs/callcenter.conf.xml tests/test_callcenter_config.py
git commit -m "feat: preload mod_callcenter and configure queues with native moh"
```

---

### Task 2: Internal Extension Calling Policy & Sofia Registration Bridge

**Files:**
- Create: `migrations/004_allow_internal_calls.sql`
- Modify: `src/xml_curl/dialplan.py`
- Modify: `src/api/v1/tenants.py`
- Modify: `src/api/v1/routing.py`
- Test: `tests/test_internal_calling.py`

**Interfaces:**
- Consumes: `tenants.allow_internal_calls`
- Produces: Dialplan XML with 403 response when internal calling is disabled, and native `user/{dest}@{domain}` bridge when enabled.

- [ ] **Step 1: Write the failing test for internal extension calling logic**

```python
# tests/test_internal_calling.py
import pytest
from unittest.mock import patch
from src.xml_curl.dialplan import handle_dialplan_request

@pytest.mark.asyncio
async def test_internal_calling_disabled_rejects_call():
    form_data = {
        "Caller-Context": "default",
        "Caller-Destination-Number": "1002",
        "Caller-Caller-ID-Number": "1001",
        "domain": "pbx.aikyamlabs.local",
        "variable_tenant_id": "11111111-1111-1111-1111-111111111111"
    }
    mock_tenant = {
        "id": "11111111-1111-1111-1111-111111111111",
        "allow_internal_calls": False,
        "sip_domain": "pbx.aikyamlabs.local"
    }
    mock_target_ext = {
        "id": "22222222-2222-2222-2222-222222222222",
        "extension_number": "1002",
        "sip_domain": "pbx.aikyamlabs.local"
    }
    with patch("src.xml_curl.dialplan.execute_query_one") as mock_query:
        mock_query.side_effect = [mock_tenant, mock_target_ext, None]
        xml_res = await handle_dialplan_request(form_data)
        assert "403" in xml_res
        assert "CALL_REJECTED" in xml_res

@pytest.mark.asyncio
async def test_internal_calling_enabled_bridges_natively():
    form_data = {
        "Caller-Context": "default",
        "Caller-Destination-Number": "1002",
        "Caller-Caller-ID-Number": "1001",
        "domain": "pbx.aikyamlabs.local",
        "variable_tenant_id": "11111111-1111-1111-1111-111111111111"
    }
    mock_tenant = {
        "id": "11111111-1111-1111-1111-111111111111",
        "allow_internal_calls": True,
        "sip_domain": "pbx.aikyamlabs.local"
    }
    mock_target_ext = {
        "id": "22222222-2222-2222-2222-222222222222",
        "extension_number": "1002",
        "sip_domain": "pbx.aikyamlabs.local",
        "no_answer_timeout": 20
    }
    with patch("src.xml_curl.dialplan.execute_query_one") as mock_query:
        mock_query.side_effect = [mock_tenant, mock_target_ext, None]
        xml_res = await handle_dialplan_request(form_data)
        assert "user/1002@pbx.aikyamlabs.local" in xml_res
        assert "continue_on_fail=true" in xml_res
        assert "voicemail_1002" in xml_res
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_internal_calling.py -v`
Expected: FAIL

- [ ] **Step 3: Implement migration and dialplan logic**

1. Create `migrations/004_allow_internal_calls.sql`:
   ```sql
   ALTER TABLE tenants ADD COLUMN IF NOT EXISTS allow_internal_calls BOOLEAN DEFAULT true;
   ```
2. In `src/xml_curl/dialplan.py`:
   - Remove `check_registered_domain` socket querying.
   - Query `allow_internal_calls` on the caller's tenant.
   - If disabled: return dialplan XML with `<action application="respond" data="403 Forbidden - Internal Calling Disabled"/>` and `<action application="hangup" data="CALL_REJECTED"/>`.
   - If enabled: bridge directly to `user/{ext_num}@{callee_domain}` with `continue_on_fail=true` and `transfer_on_fail=voicemail_{ext_num}`.
3. Update `src/api/v1/tenants.py` and `src/api/v1/routing.py` to support reading and updating `allow_internal_calls`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_internal_calling.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add migrations/004_allow_internal_calls.sql src/xml_curl/dialplan.py src/api/v1/tenants.py src/api/v1/routing.py tests/test_internal_calling.py
git commit -m "feat: implement allow_internal_calls policy and direct sofia user bridge"
```

---

### Task 3: Inbound DID Routing Engine for Extensions, Queues, and Hunt Groups

**Files:**
- Modify: `src/xml_curl/dialplan.py`
- Test: `tests/test_inbound_routing.py`

**Interfaces:**
- Consumes: `call_routes` and `dids`
- Produces: Correct dialplan for `destination_type`: `extension`, `queue`, `hunt_group`, and `conference`.

- [ ] **Step 1: Write tests for inbound routing scenarios**

```python
# tests/test_inbound_routing.py
import pytest
from unittest.mock import patch
from src.xml_curl.dialplan import handle_dialplan_request

@pytest.mark.asyncio
async def test_inbound_routing_to_queue():
    form_data = {
        "Caller-Context": "public",
        "Caller-Destination-Number": "+15552000",
        "domain": "8.234.117.15"
    }
    mock_route = {
        "id": "uuid-route",
        "destination_type": "queue",
        "destination": "Support_Queue",
        "tenant_id": "tid-1",
        "sip_domain": "pbx.aikyamlabs.local"
    }
    with patch("src.xml_curl.dialplan.execute_query_one") as mock_query:
        mock_query.return_value = mock_route
        xml_res = await handle_dialplan_request(form_data)
        assert 'application="callcenter"' in xml_res
        assert 'data="Support_Queue"' in xml_res

@pytest.mark.asyncio
async def test_inbound_routing_to_hunt_group():
    form_data = {
        "Caller-Context": "public",
        "Caller-Destination-Number": "+15553000",
        "domain": "8.234.117.15"
    }
    mock_route = {
        "id": "uuid-route",
        "destination_type": "hunt_group",
        "destination": "8888",
        "tenant_id": "tid-1",
        "sip_domain": "pbx.aikyamlabs.local"
    }
    mock_hg = {
        "name": "Sales Group",
        "extension_number": "8888",
        "members": "1001, 1002",
        "timeout": 20,
        "tenant_id": "tid-1"
    }
    with patch("src.xml_curl.dialplan.execute_query_one") as mock_query:
        mock_query.side_effect = [mock_route, mock_hg]
        xml_res = await handle_dialplan_request(form_data)
        assert 'user/1001@pbx.aikyamlabs.local' in xml_res
        assert 'user/1002@pbx.aikyamlabs.local' in xml_res
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_inbound_routing.py -v`
Expected: FAIL

- [ ] **Step 3: Update `src/xml_curl/dialplan.py` inbound DID routing**

Ensure inbound DID lookup resolves `tenant_id` and `sip_domain`.
- If `destination_type == "extension"`: bridge `user/{target}@{tenant_sip_domain}` with fallback to voicemail.
- If `destination_type == "queue"`: call FreeSWITCH `<action application="callcenter" data="{target}"/>`.
- If `destination_type == "hunt_group"`: fetch hunt group members and bridge simultaneously to `user/{m}@{tenant_sip_domain}`.
- If `destination_type == "conference"`: transfer to conference extension.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_inbound_routing.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/xml_curl/dialplan.py tests/test_inbound_routing.py
git commit -m "feat: enhance inbound DID routing to queues, hunt groups, and extensions"
```

---

### Task 4: Conference Dialplan Flow with Moderator & Participant PIN Authentication

**Files:**
- Modify: `src/xml_curl/dialplan.py`
- Test: `tests/test_conference_dialplan.py`

**Interfaces:**
- Consumes: `conferences` table (`extension_number`, `pin`, `moderator_pin`, `name`, `record_conference`)
- Produces: Dialplan prompting for PIN and joining conference room with moderator or participant profile.

- [ ] **Step 1: Write test for conference PIN authentication dialplan**

```python
# tests/test_conference_dialplan.py
import pytest
from unittest.mock import patch
from src.xml_curl.dialplan import handle_dialplan_request

@pytest.mark.asyncio
async def test_conference_dialplan_pin_prompt():
    form_data = {
        "Caller-Context": "default",
        "Caller-Destination-Number": "3000",
        "Caller-Caller-ID-Number": "1001",
        "domain": "pbx.aikyamlabs.local",
        "variable_tenant_id": "tid-1"
    }
    mock_conf = {
        "id": "conf-uuid",
        "name": "Team Standup",
        "extension_number": "3000",
        "pin": "1234",
        "moderator_pin": "9999",
        "record_conference": True,
        "tenant_id": "tid-1"
    }
    with patch("src.xml_curl.dialplan.execute_query_one") as mock_query:
        mock_query.return_value = mock_conf
        xml_res = await handle_dialplan_request(form_data)
        assert 'play_and_get_digits' in xml_res
        assert 'conference_auth_3000' in xml_res
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_conference_dialplan.py -v`
Expected: FAIL

- [ ] **Step 3: Implement conference dialplan in `src/xml_curl/dialplan.py`**

1. Match `dest_number` against `conferences` table.
2. In initial extension:
   - Answer channel.
   - Use `play_and_get_digits` prompting for PIN into variable `entered_conf_pin`.
   - Transfer to `conf_exec_3000_${entered_conf_pin}`.
3. In `conf_exec_3000_${entered_conf_pin}`:
   - Compare `${entered_conf_pin}` against `moderator_pin` -> bridge to `conference ${name}@default+flags{moderator}`.
   - Compare `${entered_conf_pin}` against `pin` -> bridge to `conference ${name}@default`.
   - On mismatch -> play retry prompt, then hangup on 3rd failure.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_conference_dialplan.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/xml_curl/dialplan.py tests/test_conference_dialplan.py
git commit -m "feat: add conference dialplan with moderator and participant pin verification"
```

---

### Task 5: Frontend Routing UI Updates for Internal Calling, Hunt Groups & Conferences

**Files:**
- Modify: `PBX-frontend/src/components/RoutingView.tsx`
- Modify: `PBX-frontend/src/components/DidsView.tsx`
- Modify: `PBX-frontend/src/services/api.ts`

**Interfaces:**
- Consumes: Tenant policy API (`allow_internal_calls`) and tenant hunt groups & conferences.
- Produces: Internal calling toggle switch card and options for Hunt Group & Conference in DID destination selectors.

- [ ] **Step 1: Update API service and TypeScript definitions**

In `PBX-frontend/src/services/api.ts`, add methods:
- `getTenantInternalPolicy(token, tenantId)`
- `updateTenantInternalPolicy(token, tenantId, allowInternalCalls: boolean)`
- Ensure `getHuntGroups` and `getConferences` are available to `RoutingView` and `DidsView`.

- [ ] **Step 2: Add Internal Extension Calling toggle card in `RoutingView.tsx`**

Add a dedicated card in `RoutingView.tsx` displaying:
- Switch: "Allow Internal Extension-to-Extension Calls"
- Description: "When disabled, internal extension calls will be immediately rejected with 403 Forbidden."
- On change: calls API and displays success toast.

- [ ] **Step 3: Add Hunt Group and Conference destination options in `RoutingView.tsx` and `DidsView.tsx`**

In destination type dropdown:
- Add `<option value="hunt_group">Hunt Group</option>`
- Add `<option value="conference">Conference Room</option>`
- Dynamically populate target dropdown from loaded hunt groups or conferences.

- [ ] **Step 4: Build test frontend**

Run: `cd /Users/tejaspatil/PBX/PBX-frontend && npm run build`
Expected: Build passes with 0 errors.

- [ ] **Step 5: Commit changes**

```bash
cd /Users/tejaspatil/PBX/PBX-frontend
git add src/components/RoutingView.tsx src/components/DidsView.tsx src/services/api.ts
git commit -m "feat: add internal calling toggle and hunt group/conference routing options"
```

---

### Task 6: End-to-End System Integration & Verification

- [ ] **Step 1: Apply database migration in PostgreSQL**
- [ ] **Step 2: Reload FreeSWITCH modules and dialplans via ESL**
- [ ] **Step 3: Run comprehensive verification script verifying internal calling toggle, callcenter MOH, and conference dialplan**
- [ ] **Step 4: Commit and tag completion of Sub-Project 1**
