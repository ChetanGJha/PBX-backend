# Voicemail System, Custom Prompts & Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the complete Voicemail system with custom greetings, 1000Hz beep tone, message recording, database persistence, asynchronous email delivery with audio attachment, and a dedicated interactive "Voicemail" tab in ReportsView.

**Architecture:** FreeSWITCH XML Curl dialplan generates greeting playback (custom uploaded prompt or dynamic TTS greeting), beep tone, and caller recording to `/var/lib/freeswitch/recordings/voicemail/`. The webhook (`/freeswitch/voicemail`) ingests the recording into PostgreSQL `voicemail_messages`, broadcasts WebSocket events, and invokes an asynchronous SMTP worker attaching the `.wav` file. The frontend `ReportsView.tsx` provides a dedicated Voicemail tab with summary KPI cards, itemized message table, inline streaming audio player, read toggle, and delete actions.

**Tech Stack:** Python 3.11, FastAPI, PostgreSQL (asyncpg), smtplib, React 19, TypeScript, Lucide Icons, FreeSWITCH mod_curl / XML Curl.

**Spec:** `docs/superpowers/specs/2026-10-14-voicemail-custom-prompts-notifications-design.md`

## Global Constraints

- Never break or modify SIP gateways `ISHAN_FL.xml` (port 5090) and `ISHAN_ITS.xml` (port 5080).
- Preserve real-time WebSockets on `/ws/reports` and `/ws/events`.
- Voicemail audio files must be stored as 8kHz mono 16-bit PCM WAV.
- Frontend must strictly adhere to the PBX Design System: zero inline styles (`style={{`) in migrated views.
- All backend tests must run and pass cleanly via `docker exec -e PYTHONPATH=/app pbx_api pytest`.

## Review Focus

1. Extension has custom greeting audio uploaded vs. dynamic TTS fallback: greeting audio path exists on disk and is correctly used in dialplan playback.
2. Caller hangs up immediately during beep vs. leaves full voice message: webhook handles both gracefully without raising uncaught exceptions.
3. SMTP server unconfigured or down: call flow and database insertion succeed; diagnostic warning is logged without crashing the webhook.
4. Voicemail message deletion: both database row and physical audio file on disk are cleaned up safely.
5. Frontend audio playback: playing one voicemail recording pauses any other playing recording in the table.

---

### Task 1: Dialplan Voicemail Greeting Resolution & Audio Flow

**Files:**
- Modify: `src/xml_curl/dialplan.py`
- Test: `tests/test_voicemail_dialplan.py`

**Interfaces:**
- Consumes: `execute_query_one`, `ensure_voicemail_prompt(ext_num: str) -> str`
- Produces: `add_voicemail_block(cond_elem: Element, ext_num: str, domain: str, tenant_id: str)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_voicemail_dialplan.py
import unittest
from xml.etree.ElementTree import Element, tostring
from unittest.mock import patch, MagicMock
from src.xml_curl.dialplan import add_voicemail_block

class TestVoicemailDialplan(unittest.TestCase):
    @patch("src.xml_curl.dialplan.ensure_voicemail_prompt", return_value="/var/lib/freeswitch/recordings/prompts/voicemail_1001.wav")
    def test_add_voicemail_block_actions(self, mock_prompt):
        cond = Element("condition")
        add_voicemail_block(cond, "1001", "pbx.local", "tenant-123")
        actions = cond.findall("action")
        apps = [a.attrib.get("application") for a in actions]
        
        self.assertIn("answer", apps)
        self.assertIn("playback", apps)
        self.assertIn("record", apps)
        self.assertIn("curl", apps)
        self.assertIn("hangup", apps)
        
        # Verify 1000Hz beep tone playback
        beep_action = [a for a in actions if a.attrib.get("application") == "playback" and "tone_stream" in a.attrib.get("data", "")]
        self.assertTrue(len(beep_action) > 0)
        self.assertIn("%(500,0,1000)", beep_action[0].attrib["data"])
        
        # Verify record command parameters
        rec_action = [a for a in actions if a.attrib.get("application") == "record"][0]
        self.assertIn("120 200 4", rec_action.attrib["data"])
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `docker exec -e PYTHONPATH=/app pbx_api pytest tests/test_voicemail_dialplan.py -v`

- [ ] **Step 3: Enhance `add_voicemail_block` in `src/xml_curl/dialplan.py`**

Ensure `add_voicemail_block` supports custom extension greeting playback from `voicemail_boxes.greeting_path` when available on disk, falls back to `ensure_voicemail_prompt(ext_num)`, generates the 1000Hz beep tone, records to `/var/lib/freeswitch/recordings/voicemail/{ext_num}_${uuid}.wav`, and registers the hangup hook.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec -e PYTHONPATH=/app pbx_api pytest tests/test_voicemail_dialplan.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_voicemail_dialplan.py src/xml_curl/dialplan.py
git commit -m "feat(voicemail): enhance dialplan voicemail greeting and beep actions"
```

---

### Task 2: Voicemail Message Ingestion & Email Dispatch Pipeline

**Files:**
- Modify: `src/xml_curl/router.py`, `src/core/email_service.py`
- Test: `tests/test_voicemail_ingestion.py`

**Interfaces:**
- Consumes: `get_smtp_settings(tenant_id: Optional[str])`, `build_email_message`
- Produces: `POST /freeswitch/voicemail`, `send_voicemail_notification`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_voicemail_ingestion.py
import unittest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from src.main import app

class TestVoicemailIngestion(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("src.xml_curl.router.execute_query_one")
    @patch("src.xml_curl.router.execute_query")
    @patch("src.xml_curl.router.send_voicemail_notification", new_callable=AsyncMock)
    @patch("src.core.websocket_manager.ws_manager.broadcast_json", new_callable=AsyncMock)
    def test_voicemail_webhook_ingestion(self, mock_ws, mock_send_email, mock_exec, mock_exec_one):
        mock_exec_one.side_effect = [
            {"id": "ext-1", "email": "alice@acme.com", "display_name": "Alice", "tenant_name": "Acme"},
            {"id": "box-1"}
        ]
        
        response = self.client.post("/freeswitch/voicemail", params={
            "extension_number": "1001",
            "caller_id_number": "+15551234567",
            "caller_id_name": "John Doe",
            "file_path": "/var/lib/freeswitch/recordings/voicemail/1001_12345.wav",
            "duration": "24",
            "tenant_id": "00000000-0000-0000-0000-000000000001"
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["email_sent_to"], "alice@acme.com")
        self.assertTrue(mock_send_email.called)
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `docker exec -e PYTHONPATH=/app pbx_api pytest tests/test_voicemail_ingestion.py -v`

- [ ] **Step 3: Implement / Refine `src/xml_curl/router.py`**

Ensure `handle_voicemail_webhook` creates/links `voicemail_boxes`, persists `voicemail_messages`, dispatches `send_voicemail_notification`, and notifies connected WebSockets (`broadcast_json({"type": "voicemail.created", ...})`).

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec -e PYTHONPATH=/app pbx_api pytest tests/test_voicemail_ingestion.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_voicemail_ingestion.py src/xml_curl/router.py
git commit -m "feat(voicemail): integrate voicemail ingestion webhook and websocket notifications"
```

---

### Task 3: Custom Audio Prompts API & Extension Greeting Linking

**Files:**
- Modify: `src/api/v1/audio.py`
- Test: `tests/test_audio_prompts.py`

**Interfaces:**
- Consumes: `audio_files` table
- Produces: `GET /audio`, `POST /audio/upload`, `GET /audio/{id}/stream`, `DELETE /audio/{id}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audio_prompts.py
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app
from src.core.permissions import CurrentUser

class TestAudioPrompts(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("src.api.v1.audio.get_current_user", return_value=CurrentUser(
        user_id="u-1", username="admin", role="SUPER_ADMIN", is_super_admin=True, tenant_id=None
    ))
    @patch("src.api.v1.audio.execute_query")
    def test_list_audio_files(self, mock_query, mock_user):
        mock_query.return_value = [
            {"id": "a-1", "name": "Greeting 1", "file_name": "greet1.wav", "category": "ivr_greeting"}
        ]
        res = self.client.get("/api/v1/audio")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "Greeting 1")
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `docker exec -e PYTHONPATH=/app pbx_api pytest tests/test_audio_prompts.py -v`

- [ ] **Step 3: Implement / Refine `src/api/v1/audio.py`**

Verify audio file upload with validation, stream preview with `Accept-Ranges: bytes`, and tenant scoping.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec -e PYTHONPATH=/app pbx_api pytest tests/test_audio_prompts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_audio_prompts.py src/api/v1/audio.py
git commit -m "feat(audio): verify custom audio prompts api and stream endpoints"
```

---

### Task 4: Dedicated Voicemail Tab in Frontend `ReportsView.tsx`

**Files:**
- Modify: `PBX-frontend/src/components/ReportsView.tsx`

**Interfaces:**
- Consumes: `apiService.getVoicemailReport`, `apiService.toggleVoicemailRead`, `apiService.deleteVoicemailMessage`, `apiService.getVoicemailAudioUrl`
- Produces: Dedicated `'voicemail'` tab in `ReportsView.tsx`

- [ ] **Step 1: Implement Voicemail Tab in `ReportsView.tsx`**

- Extend `activeTab` type to `'summary' | 'disposition' | 'voicemail' | 'cdr' | 'internal' | 'outbound' | 'recordings'`.
- Add Voicemail tab button with `Voicemail` icon.
- Fetch voicemail report data on tab activation or filter changes.
- Display 4 KPI StatCards:
  - Total Voicemails
  - Unread Messages
  - Total Duration
  - Active Mailboxes
- Display itemized messages DataTable with columns: Extension, Caller ID, Timestamp, Duration, Status badge, Audio Player, Actions.
- Provide inline streaming audio player, read toggle, and delete message action.
- Ensure strict adherence to Design System (no inline styles).

- [ ] **Step 2: Run Design System lint and TypeScript build**

Run: `npm run build` in `PBX-frontend`
Expected: 0 DS violations, 0 TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add src/components/ReportsView.tsx
git commit -m "feat(reports): add dedicated interactive voicemail tab to reports view"
```

---

### Task 5: End-to-End System Integration & Live Verification

**Files:**
- Test: `tests/test_e2e_voicemail_system.py`

**Interfaces:**
- Integrates Dialplan -> Voicemail Webhook -> DB -> Reports API -> Audio Streaming

- [ ] **Step 1: Write and run end-to-end integration test**

Verify complete lifecycle:
1. Dialplan generates valid voicemail XML actions with greeting and beep.
2. Webhook stores message in database and triggers notification.
3. Reports API returns the message under `/reports/voicemail`.
4. Audio streaming endpoint serves the `.wav` file.
5. Message read status can be toggled and message can be deleted.

- [ ] **Step 2: Run all backend tests**

Run: `docker exec -e PYTHONPATH=/app pbx_api pytest -v`
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_voicemail_system.py
git commit -m "test(voicemail): add comprehensive end-to-end voicemail integration tests"
```
