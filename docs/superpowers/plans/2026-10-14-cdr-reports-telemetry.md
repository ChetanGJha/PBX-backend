# Sub-Project 2: CDR Pipeline, Reports & Dashboard Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement FreeSWITCH `mod_xml_cdr` ingestion to PostgreSQL with call recordings and audio streaming, real-time WebSocket broadcasting for live CDRs and disposition updates, dedicated Disposition Summary reporting, and live Dashboard telemetry widgets.

**Architecture:** FreeSWITCH dumps completed call XML via `mod_xml_cdr` to `/freeswitch/cdr`. The API parses the XML, resolves the tenant, detects call direction (`inbound`, `outbound`, `internal`), registers recordings in `public.recordings`, inserts into `public.cdr`, and broadcasts `cdr.created` over WebSockets (`/ws/reports`). The frontend `ReportsView` and `DashboardView` consume both REST and WebSockets for real-time telemetry.

**Tech Stack:** Python 3.12, FastAPI, FreeSWITCH `mod_xml_cdr`, PostgreSQL, WebSockets, React 19, TypeScript, Lucide React.

**Spec:** [docs/superpowers/specs/2026-10-14-cdr-reports-telemetry-design.md](file:///Users/tejaspatil/PBX/PBX-backend/docs/superpowers/specs/2026-10-14-cdr-reports-telemetry-design.md)

## Global Constraints
- Preserve multi-homed SIP gateways (`ISHAN_FL` on 5090 cross-connect and `ISHAN_ITS` on 5080 external) untouched.
- Maintain Design System consistency in `PBX-frontend` (using existing UI components: `Card`, `FormField`, `Select`, `Button`, `Badge`, `Tabs`, `DataTable`).
- WebSocket endpoint must be authenticated via token (`/ws/reports?token=...`).

## Review Focus
1. `mod_xml_cdr` fails to load if `xml_cdr.conf.xml` is missing or invalid -> unit test XML configuration validity and verify live module in FreeSWITCH.
2. Ingesting duplicate CDRs for the same call UUID -> use PostgreSQL `ON CONFLICT (call_uuid) DO UPDATE` to ensure idempotency.
3. Call direction ambiguity (e.g. carrier calls vs extension calls) -> strictly evaluate direction as `inbound`, `outbound`, or `internal`.
4. WebSocket connection drops -> frontend client must automatically reconnect with exponential backoff.
5. Missing audio file on disk -> stream endpoint must gracefully return 404 without crashing.

---

### Task 1: FreeSWITCH `mod_xml_cdr` Configuration & Module Loading

**Files:**
- Create: `config/freeswitch/autoload_configs/xml_cdr.conf.xml`
- Modify: `config/freeswitch/autoload_configs/modules.conf.xml`
- Test: `tests/test_xml_cdr_config.py`

**Interfaces:**
- Produces: Valid XML configuration for `mod_xml_cdr` pointing to `http://api:8000/freeswitch/cdr`.

- [ ] **Step 1: Write test for `xml_cdr.conf.xml` and `modules.conf.xml`**

```python
# tests/test_xml_cdr_config.py
import unittest
import xml.etree.ElementTree as ET

class TestXmlCdrConfig(unittest.TestCase):
    def test_xml_cdr_conf_validity(self):
        tree = ET.parse("config/freeswitch/autoload_configs/xml_cdr.conf.xml")
        root = tree.getroot()
        self.assertEqual(root.attrib.get("name"), "xml_cdr.conf")
        params = {p.attrib["name"]: p.attrib["value"] for p in root.findall(".//param")}
        self.assertIn("http://api:8000/freeswitch/cdr", params.get("url", ""))
        self.assertEqual(params.get("encode"), "true")

    def test_modules_conf_contains_mod_xml_cdr(self):
        tree = ET.parse("config/freeswitch/autoload_configs/modules.conf.xml")
        root = tree.getroot()
        loaded = [elem.attrib.get("module") for elem in root.findall(".//load")]
        self.assertIn("mod_xml_cdr", loaded)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_xml_cdr_config.py`
Expected: FAIL (file not found)

- [ ] **Step 3: Create `xml_cdr.conf.xml` and add module to `modules.conf.xml`**

1. Create `config/freeswitch/autoload_configs/xml_cdr.conf.xml`:
```xml
<configuration name="xml_cdr.conf" description="XML CDR Module">
  <settings>
    <param name="url" value="http://api:8000/freeswitch/cdr"/>
    <param name="retries" value="3"/>
    <param name="delay" value="0"/>
    <param name="log-b-leg" value="false"/>
    <param name="prefix-a-leg" value="false"/>
    <param name="encode" value="true"/>
  </settings>
</configuration>
```
2. Add `<load module="mod_xml_cdr"/>` in `config/freeswitch/autoload_configs/modules.conf.xml`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_xml_cdr_config.py`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add config/freeswitch/autoload_configs/xml_cdr.conf.xml config/freeswitch/autoload_configs/modules.conf.xml tests/test_xml_cdr_config.py
git commit -m "feat: configure mod_xml_cdr in freeswitch modules and autoload configs"
```

---

### Task 2: XML CDR Ingestion Endpoint with Audio Recording & Direction Tagging

**Files:**
- Modify: `src/xml_curl/router.py`
- Test: `tests/test_xml_cdr_ingestion.py`

**Interfaces:**
- Consumes: FreeSWITCH XML CDR POST payloads (`cdr=<urlencoded_xml>` or raw XML).
- Produces: Rows in `public.cdr` and `public.recordings`.

- [ ] **Step 1: Write test for XML CDR parsing and database insertion**

```python
# tests/test_xml_cdr_ingestion.py
import unittest
from unittest.mock import patch, AsyncMock
from src.xml_curl.router import parse_and_process_xml_cdr

class TestXmlCdrIngestion(unittest.IsolatedAsyncioTestCase):
    async def test_parse_xml_cdr_inbound_call(self):
        sample_xml = """<?xml version="1.0"?>
        <cdr>
          <variables>
            <uuid>test-call-uuid-1</uuid>
            <direction>inbound</direction>
            <caller_id_number>+18005550100</caller_id_number>
            <caller_id_name>John Doe</caller_id_name>
            <destination_number>1001</destination_number>
            <tenant_id>11111111-1111-1111-1111-111111111111</tenant_id>
            <start_epoch>1700000000</start_epoch>
            <answer_epoch>1700000005</answer_epoch>
            <end_epoch>1700000045</end_epoch>
            <duration>45</duration>
            <billsec>40</billsec>
            <hangup_cause>NORMAL_CLEARING</hangup_cause>
          </variables>
        </cdr>
        """
        with patch("src.xml_curl.router.execute_query", new_callable=AsyncMock) as mock_exec:
            res = await parse_and_process_xml_cdr(sample_xml)
            self.assertEqual(res["call_uuid"], "test-call-uuid-1")
            self.assertEqual(res["direction"], "inbound")
            self.assertEqual(res["duration"], 45)
            self.assertEqual(res["billsec"], 40)
            self.assertEqual(mock_exec.call_count, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_xml_cdr_ingestion.py`
Expected: FAIL

- [ ] **Step 3: Implement XML CDR parser in `src/xml_curl/router.py`**

1. Parse XML safely using `xml.etree.ElementTree`.
2. Extract channel variables: `uuid`, `direction` (inbound, outbound, internal), `caller_id_number`, `caller_id_name`, `destination_number`, `tenant_id`, `start_epoch`, `answer_epoch`, `end_epoch`, `duration`, `billsec`, `hangup_cause`, `recording_file`.
3. Check for recording on disk; if present, insert into `recordings` and set `recording_id`.
4. Upsert into `cdr` table.
5. In `@router.post("/cdr")`: detect XML vs JSON and route accordingly.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_xml_cdr_ingestion.py`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/xml_curl/router.py tests/test_xml_cdr_ingestion.py
git commit -m "feat: implement xml cdr parser and database ingestion in router"
```

---

### Task 3: WebSocket Real-Time Event Broadcaster

**Files:**
- Create: `src/core/websocket_manager.py`
- Modify: `src/main.py`
- Modify: `src/xml_curl/router.py`
- Test: `tests/test_websocket_broadcaster.py`

**Interfaces:**
- Produces: `ws_manager.broadcast_cdr_created(cdr_dict)` and `/ws/reports` WebSocket endpoint.

- [ ] **Step 1: Write test for WebSocket manager connection and event dispatch**

```python
# tests/test_websocket_broadcaster.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_websocket_broadcaster.py`
Expected: FAIL

- [ ] **Step 3: Implement `ConnectionManager` and add WebSocket endpoint**

1. Create `src/core/websocket_manager.py` with `ConnectionManager` supporting tenant filtering and token authentication.
2. In `src/main.py`, mount `websocket("/ws/reports")` calling `ws_manager.connect()`.
3. In `src/xml_curl/router.py`, call `await ws_manager.broadcast_cdr_created(cdr_data)` after inserting the CDR into PostgreSQL.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_websocket_broadcaster.py`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/core/websocket_manager.py src/main.py src/xml_curl/router.py tests/test_websocket_broadcaster.py
git commit -m "feat: add real-time websocket broadcaster for live cdr and reports"
```

---

### Task 4: Backend Disposition Summary & Enhanced CDR/Dashboard Endpoints

**Files:**
- Modify: `src/api/v1/reports.py`
- Test: `tests/test_disposition_reports.py`

**Interfaces:**
- Produces: `GET /api/v1/reports/disposition-summary`, enhanced `GET /api/v1/reports/cdr` with disposition and call direction filters, enhanced `GET /api/v1/reports/dashboard-metrics`.

- [ ] **Step 1: Write test for disposition summary API**

```python
# tests/test_disposition_reports.py
import unittest
from unittest.mock import patch, AsyncMock
from src.api.v1.reports import get_disposition_summary

class TestDispositionReports(unittest.IsolatedAsyncioTestCase):
    async def test_disposition_summary_calculation(self):
        mock_rows = [
            {"disposition": "ANSWERED", "count": 80, "avg_duration": 120},
            {"disposition": "NO_ANSWER", "count": 10, "avg_duration": 0},
            {"disposition": "BUSY", "count": 5, "avg_duration": 0},
            {"disposition": "FAILED", "count": 5, "avg_duration": 0},
        ]
        with patch("src.api.v1.reports.execute_query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = mock_rows
            mock_user = AsyncMock()
            mock_user.is_super_admin = True
            mock_user.tenant_id = None
            res = await get_disposition_summary(current_user=mock_user)
            self.assertEqual(res["total_calls"], 100)
            self.assertEqual(res["answered"], 80)
            self.assertEqual(res["answer_rate_pct"], 80.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_disposition_reports.py`
Expected: FAIL

- [ ] **Step 3: Implement endpoints in `src/api/v1/reports.py`**

1. Implement `GET /api/v1/reports/disposition-summary`:
   - Compute `ANSWERED`, `NO_ANSWER`, `BUSY`, `FAILED`, `CANCELLED` counts and percentages.
2. In `GET /api/v1/reports/cdr`:
   - Add `disposition` parameter filtering by `answered`, `no_answer`, `busy`, `failed`.
3. In `GET /api/v1/reports/dashboard-metrics`:
   - Add ESL live channel query with fallback.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_disposition_reports.py`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/api/v1/reports.py tests/test_disposition_reports.py
git commit -m "feat: add disposition summary endpoint and enhance cdr filters"
```

---

### Task 5: Frontend ReportsView & DashboardView with Real-Time WebSockets

**Files:**
- Modify: `PBX-frontend/src/services/api.ts`
- Modify: `PBX-frontend/src/components/ReportsView.tsx`
- Modify: `PBX-frontend/src/components/DashboardView.tsx`

**Interfaces:**
- Consumes: REST endpoints (`/api/v1/reports/disposition-summary`, `/api/v1/reports/cdr`) and WebSocket (`/ws/reports`).
- Produces: Real-time UI updates for CDRs, Disposition Cards, and Dashboard widgets.

- [ ] **Step 1: Update `api.ts` with disposition summary and filters**

Add `getDispositionSummaryReport(token, tenantId?, startDate?, endDate?, callType?)` and update `getCdrReport` with `callType` and `disposition`.

- [ ] **Step 2: Update `ReportsView.tsx`**

1. Add `'disposition'` tab to `Tabs` with icon `<PieChart />`.
2. In Disposition tab, render KPI cards:
   - Total Calls, Answered, Unanswered / No Answer, Busy, Failed, Answer Rate %.
   - Granular breakdown table with counts and percentages.
3. In FilterBar, add:
   - Call Direction Select: `All Directions`, `Inbound`, `Outbound`, `Internal`.
   - Disposition Select: `All Dispositions`, `Answered`, `No Answer`, `Busy`, `Failed`.
4. Establish WebSocket connection to `/ws/reports?token=${token}`:
   - On `cdr.created`: if on CDR tab, prepend new record to `reportData`; if on Disposition tab, refresh counters.

- [ ] **Step 3: Update `DashboardView.tsx`**

Connect to `/ws/reports?token=${token}`: on `cdr.created` or `telemetry.updated`, re-fetch dashboard metrics to update Traffic Summary and Peak widgets in real time.

- [ ] **Step 4: Build and test frontend**

Run: `cd /Users/tejaspatil/PBX/PBX-frontend && npm run build`
Expected: Build passes with 0 errors and 0 design system violations.

- [ ] **Step 5: Commit changes**

```bash
cd /Users/tejaspatil/PBX/PBX-frontend
git add src/services/api.ts src/components/ReportsView.tsx src/components/DashboardView.tsx
git commit -m "feat: add disposition summary tab, direction filters, and realtime websocket updates to reports and dashboard"
```

---

### Task 6: End-to-End Live Integration Verification

- [ ] **Step 1: Reload FreeSWITCH configuration**

```bash
docker exec pbx_freeswitch fs_cli -x "reloadxml"
docker exec pbx_freeswitch fs_cli -x "load mod_xml_cdr"
docker exec pbx_freeswitch fs_cli -x "module_exists mod_xml_cdr"
```
Verify output is `true`.

- [ ] **Step 2: Run end-to-end simulation test**

Post sample XML CDR payloads for inbound, outbound, and internal calls to live `/freeswitch/cdr`, and verify:
1. Records appear in `public.cdr` with correct direction and billsec.
2. `GET /api/v1/reports/disposition-summary` reflects the call dispositions.
3. `GET /api/v1/reports/dashboard-metrics` displays updated traffic summary and peak concurrency.
4. WebSocket client receives `cdr.created` broadcast.

- [ ] **Step 3: Run full test suite**

Run all backend unit and integration tests to confirm 100% green.

- [ ] **Step 4: Commit and finalize Sub-Project 2**
