# Multi-Tenant PBX Platform — API User Manual

Welcome to the **Multi-Tenant PBX Platform API Guide**. This document provides step-by-step instructions, request/response schemas, and `curl` command examples for authenticating, managing tenants, provisioning SIP extensions, and testing FreeSWITCH dynamic configuration.

---

## 1. Quick Reference & Interactive Docs

- **API Base URL**: `http://localhost:8000/api/v1` (or via Nginx `http://localhost/api/v1`)
- **Interactive Swagger UI**: [`http://localhost:8000/docs`](http://localhost:8000/docs)
- **ReDoc Schema Documentation**: [`http://localhost:8000/redoc`](http://localhost:8000/redoc)

---

## 2. Authentication & Security Workflow

All protected API endpoints require a JWT bearer token passed in the HTTP Authorization header:
`Authorization: Bearer <your_access_token>`

### Step 1: Bootstrap Super Admin User
*Call this initial endpoint once to create your platform Super Admin account.*

- **Endpoint**: `POST /api/v1/auth/seed-superadmin`
- **Request Body**:
```json
{
  "username": "superadmin",
  "email": "admin@pbx.com",
  "password": "SuperSecurePassword123!",
  "first_name": "Platform",
  "last_name": "Admin"
}
```

- **Example `curl`**:
```bash
curl -X POST http://localhost:8000/api/v1/auth/seed-superadmin \
  -H "Content-Type: application/json" \
  -d '{
    "username": "superadmin",
    "email": "admin@pbx.com",
    "password": "SuperSecurePassword123!"
  }'
```

- **Response `200 OK`**:
```json
{
  "message": "Super Admin user created successfully",
  "user_id": "0c909c30-0116-45ab-91c7-b16ec662ee4a",
  "username": "superadmin"
}
```

---

### Step 2: Login & Obtain JWT Tokens

- **Endpoint**: `POST /api/v1/auth/login`
- **Request Body**:
```json
{
  "username_or_email": "superadmin",
  "password": "SuperSecurePassword123!"
}
```

- **Example `curl`**:
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username_or_email": "superadmin",
    "password": "SuperSecurePassword123!"
  }'
```

- **Response `200 OK`**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": "0c909c30-0116-45ab-91c7-b16ec662ee4a",
    "username": "superadmin",
    "email": "admin@pbx.com",
    "role": "SUPER_ADMIN",
    "tenant_id": null
  }
}
```

---

### Step 3: Get Current User Profile (`/auth/me`)

- **Endpoint**: `GET /api/v1/auth/me`
- **Example `curl`**:
```bash
curl -X GET http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

---

## 3. Tenant Management (`/api/v1/tenants`)

Tenant isolation is strictly enforced across the entire platform. Super Admins can manage all tenants, whereas Tenant Admins can view/update their assigned tenant.

### 1. Create a New Tenant (Super Admin Only)

- **Endpoint**: `POST /api/v1/tenants`
- **Request Body**:
```json
{
  "name": "Acme Corporation",
  "domain": "acme.pbx.com",
  "sip_domain": "acme.local",
  "timezone": "UTC",
  "max_extensions": 100,
  "max_concurrent_calls": 20,
  "branding": {
    "logo_url": "https://acme.com/logo.png",
    "primary_color": "#0052CC"
  }
}
```

- **Example `curl`**:
```bash
curl -X POST http://localhost:8000/api/v1/tenants \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Acme Corporation",
    "domain": "acme.pbx.com",
    "sip_domain": "acme.local"
  }'
```

- **Response `201 Created`**:
```json
{
  "id": "45a5c3e7-a7a2-4b81-95ea-3ae21d3d7656",
  "name": "Acme Corporation",
  "domain": "acme.pbx.com",
  "sip_domain": "acme.local",
  "timezone": "UTC",
  "enabled": true,
  "max_extensions": 100,
  "max_concurrent_calls": 20,
  "created_at": "2026-09-26T06:33:24.236796+00:00"
}
```

---

### 2. List Tenants

- **Endpoint**: `GET /api/v1/tenants?skip=0&limit=50`
- **Example `curl`**:
```bash
curl -X GET "http://localhost:8000/api/v1/tenants?skip=0&limit=50" \
  -H "Authorization: Bearer <access_token>"
```

---

### 3. Get Tenant Details

- **Endpoint**: `GET /api/v1/tenants/{tenant_id}`
- **Example `curl`**:
```bash
curl -X GET http://localhost:8000/api/v1/tenants/45a5c3e7-a7a2-4b81-95ea-3ae21d3d7656 \
  -H "Authorization: Bearer <access_token>"
```

---

### 4. Update Tenant Settings

- **Endpoint**: `PUT /api/v1/tenants/{tenant_id}`
- **Request Body**:
```json
{
  "name": "Acme Corp Updated",
  "timezone": "America/New_York",
  "max_extensions": 150
}
```

- **Example `curl`**:
```bash
curl -X PUT http://localhost:8000/api/v1/tenants/45a5c3e7-a7a2-4b81-95ea-3ae21d3d7656 \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Acme Corp Updated",
    "timezone": "America/New_York"
  }'
```

---

### 5. Delete Tenant (Soft Delete)

- **Endpoint**: `DELETE /api/v1/tenants/{tenant_id}`
- **Example `curl`**:
```bash
curl -X DELETE http://localhost:8000/api/v1/tenants/45a5c3e7-a7a2-4b81-95ea-3ae21d3d7656 \
  -H "Authorization: Bearer <access_token>"
```

---

## 4. Extension Management (`/api/v1/extensions`)

Provision and manage SIP & WebRTC softphone extensions.

### 1. Create a New Extension

- **Endpoint**: `POST /api/v1/extensions`
- **Request Body**:
```json
{
  "tenant_id": "45a5c3e7-a7a2-4b81-95ea-3ae21d3d7656",
  "extension_number": "1001",
  "display_name": "Alice Smith",
  "email": "alice@acme.com",
  "sip_password": "SIPPassword123!",
  "voicemail_pin": "1234",
  "caller_id_name": "Alice Smith",
  "caller_id_number": "1001",
  "webrtc_enabled": true,
  "no_answer_timeout": 20
}
```

- **Example `curl`**:
```bash
curl -X POST http://localhost:8000/api/v1/extensions \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "45a5c3e7-a7a2-4b81-95ea-3ae21d3d7656",
    "extension_number": "1001",
    "display_name": "Alice Smith",
    "email": "alice@acme.com",
    "sip_password": "SIPPassword123!",
    "voicemail_pin": "1234"
  }'
```

- **Response `201 Created`**:
```json
{
  "id": "69233e69-c273-4ff9-990b-5dfcf5131516",
  "tenant_id": "45a5c3e7-a7a2-4b81-95ea-3ae21d3d7656",
  "extension_number": "1001",
  "display_name": "Alice Smith",
  "email": "alice@acme.com",
  "caller_id_name": "Alice Smith",
  "caller_id_number": "1001",
  "outbound_caller_id": null,
  "enabled": true,
  "webrtc_enabled": true,
  "no_answer_timeout": 20,
  "created_at": "2026-09-26T06:33:24.255539+00:00"
}
```

---

### 2. List Extensions

- **Endpoint**: `GET /api/v1/extensions?skip=0&limit=50`
- **Example `curl`**:
```bash
curl -X GET "http://localhost:8000/api/v1/extensions?skip=0&limit=50" \
  -H "Authorization: Bearer <access_token>"
```

---

### 3. Reset Extension Password or Voicemail PIN

- **Endpoint**: `POST /api/v1/extensions/{extension_id}/reset-password`
- **Request Body**:
```json
{
  "new_sip_password": "NewSIPPassword456!",
  "new_voicemail_pin": "5678"
}
```

- **Example `curl`**:
```bash
curl -X POST http://localhost:8000/api/v1/extensions/69233e69-c273-4ff9-990b-5dfcf5131516/reset-password \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "new_sip_password": "NewSIPPassword456!",
    "new_voicemail_pin": "5678"
  }'
```

---

## 5. FreeSWITCH Integration (`mod_xml_curl`)

FreeSWITCH communicates with the API Control Plane automatically via HTTP POST requests to fetch dynamic XML directory configurations during SIP REGISTER and INVITE operations.

### Simulating a FreeSWITCH XML-CURL Request

- **Endpoint**: `POST /freeswitch/xml`
- **Content-Type**: `application/x-www-form-urlencoded`
- **Form Data**:
  - `section`: `directory`
  - `domain`: `acme.local`
  - `user`: `1001`

- **Example `curl`**:
```bash
curl -X POST http://localhost:8000/freeswitch/xml \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "section=directory&domain=acme.local&user=1001"
```

- **FreeSWITCH Dynamic XML Output**:
```xml
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<document type="freeswitch/xml">
  <section name="directory">
    <domain name="acme.local">
      <params>
        <param name="dial-string" value="{sip_invite_domain}/${dialed_user}@${dialed_domain}" />
      </params>
      <groups>
        <group name="default">
          <users>
            <user id="1001">
              <params>
                <param name="password" value="SIPPassword123!" />
                <param name="vm-password" value="1234" />
              </params>
              <variables>
                <variable name="user_context" value="tenant-45a5c3e7-a7a2-4b81-95ea-3ae21d3d7656" />
                <variable name="effective_caller_id_name" value="Alice Smith" />
                <variable name="effective_caller_id_number" value="1001" />
                <variable name="accountcode" value="45a5c3e7-a7a2-4b81-95ea-3ae21d3d7656" />
                <variable name="tenant_id" value="45a5c3e7-a7a2-4b81-95ea-3ae21d3d7656" />
                <variable name="user_email" value="alice@acme.com" />
              </variables>
            </user>
          </users>
        </group>
      </groups>
    </domain>
  </section>
</document>
```

---

## 6. Health & System Monitoring

- **Liveness Probe**: `GET /health`
```bash
curl -X GET http://localhost:8000/health
```

- **Readiness Probe** (Verifies DB & Redis connection): `GET /ready`
```bash
curl -X GET http://localhost:8000/ready
```

---

## 7. Call Detail Records (CDR) & Real-Time Reports

### CDR Query & Analytics
- **Endpoint**: `GET /api/v1/reports/cdr`
- **Query Parameters**:
  - `tenant_id`: (Super Admin only) filter by tenant UUID
  - `start_date`: `YYYY-MM-DD`
  - `end_date`: `YYYY-MM-DD`
  - `direction`: `inbound` | `outbound` | `internal` | `all`
  - `disposition`: `ANSWERED` | `NO_ANSWER` | `BUSY` | `FAILED` | `all`

```bash
curl -X GET "http://localhost:8000/api/v1/reports/cdr?direction=inbound&disposition=ANSWERED" \
  -H "Authorization: Bearer <access_token>"
```

### Disposition Summary KPI Analytics
- **Endpoint**: `GET /api/v1/reports/disposition-summary`
- **Query Parameters**: `tenant_id`, `start_date`, `end_date`, `direction`
- **Response**: Aggregated counts for `total_calls`, `answered`, `no_answer`, `busy`, `failed`, `answer_rate_pct`, and detailed hangup cause breakdown.

```bash
curl -X GET "http://localhost:8000/api/v1/reports/disposition-summary" \
  -H "Authorization: Bearer <access_token>"
```

### FreeSWITCH mod_xml_cdr Webhook
- **Endpoint**: `POST /freeswitch/cdr`
- FreeSWITCH automatically posts complete XML CDR records upon call completion. The backend normalizes variables, determines call direction, computes billable seconds, updates PostgreSQL `cdrs`, and broadcasts real-time events over WebSockets.

---

## 8. Voicemail Subsystem & Reports

### Fetch Voicemail Report & Messages
- **Endpoint**: `GET /api/v1/reports/voicemail`
- **Query Parameters**:
  - `extension_number`: Filter by extension
  - `is_read`: `true` | `false`
  - `start_date` / `end_date`: Date range filters
- **Response**: Summary counts (`total_messages`, `unread_messages`, `total_duration_seconds`) and itemized message list.

```bash
curl -X GET "http://localhost:8000/api/v1/reports/voicemail" \
  -H "Authorization: Bearer <access_token>"
```

### Stream Voicemail Audio
- **Endpoint**: `GET /api/v1/reports/voicemail/{message_id}/audio`
- Streams the 8kHz mono WAV voice message with `Accept-Ranges: bytes` support for in-browser playback.

```bash
curl -X GET "http://localhost:8000/api/v1/reports/voicemail/<message_id>/audio" \
  -H "Authorization: Bearer <access_token>" \
  -o voicemail.wav
```

### Mark Voicemail Read / Unread
- **Endpoint**: `PATCH /api/v1/reports/voicemail/{message_id}/read?read=true`

```bash
curl -X PATCH "http://localhost:8000/api/v1/reports/voicemail/<message_id>/read?read=true" \
  -H "Authorization: Bearer <access_token>"
```

### Delete Voicemail Message
- **Endpoint**: `DELETE /api/v1/reports/voicemail/{message_id}`
- Removes message metadata from database and purges recording audio file from disk.

```bash
curl -X DELETE "http://localhost:8000/api/v1/reports/voicemail/<message_id>" \
  -H "Authorization: Bearer <access_token>"
```

---

## 9. System Prompts & Custom Audio Management

### List Audio Files
- **Endpoint**: `GET /api/v1/audio`
- **Query Parameters**: `category` (`ivr_greeting`, `ivr_prompt`, `moh`), `tenant_id`

```bash
curl -X GET "http://localhost:8000/api/v1/audio" \
  -H "Authorization: Bearer <access_token>"
```

### Upload Custom Audio File
- **Endpoint**: `POST /api/v1/audio/upload`
- **Form Data**:
  - `file`: Audio file (`.wav`, `.mp3`, `.ogg`)
  - `category`: `ivr_greeting` | `ivr_prompt` | `moh`
  - `tenant_id`: Optional tenant UUID

```bash
curl -X POST "http://localhost:8000/api/v1/audio/upload" \
  -H "Authorization: Bearer <access_token>" \
  -F "file=@/path/to/custom_greeting.wav" \
  -F "category=ivr_greeting"
```

### Stream Audio File
- **Endpoint**: `GET /api/v1/audio/{file_id}/stream`
- Streams audio for browser preview or FreeSWITCH playback.

---

## 10. Call Center Queues, Hunt Groups & Conferences

### Call Queues (`mod_callcenter`)
- **Endpoint**: `GET /api/v1/queues`, `POST /api/v1/queues`
- Supported strategies: `round-robin`, `longest-idle-agent`, `top-down`, `ring-all`.
- Supported tiers: Agent priority, penalty, and wrap-up times.

### Hunt Groups / Ring Groups
- **Endpoint**: `GET /api/v1/hunt-groups`, `POST /api/v1/hunt-groups`
- Supported ring strategies: `simultaneous` (all ring at once), `sequential` (linear ordered failover), `random`.

### Conference Rooms (`mod_conference`)
- **Endpoint**: `GET /api/v1/conferences`, `POST /api/v1/conferences`
- Pin protection for participants and moderators (`participant_pin`, `moderator_pin`), max members limits, and hold music assignment.

---

## 11. SMTP Settings & Email Notifications

### Get SMTP Settings
- **Endpoint**: `GET /api/v1/settings/smtp`
- Returns configured status and active SMTP configuration. Automatically falls back to Global PBX SMTP settings if tenant settings are not defined.

```bash
curl -X GET "http://localhost:8000/api/v1/settings/smtp" \
  -H "Authorization: Bearer <access_token>"
```

### Update SMTP Configuration
- **Endpoint**: `PUT /api/v1/settings/smtp`
- **Request Body**:
```json
{
  "smtp_host": "smtp.mailgun.org",
  "smtp_port": 587,
  "smtp_username": "postmaster@mycompany.com",
  "smtp_password": "MySecretPassword!",
  "from_email": "voicemail@mycompany.com",
  "from_name": "PBX Notifications",
  "use_tls": true
}
```

### Test SMTP Connection
- **Endpoint**: `POST /api/v1/settings/smtp/test`
- Sends a live test email verifying host, credentials, TLS negotiation, and recipient delivery.

```bash
curl -X POST "http://localhost:8000/api/v1/settings/smtp/test" \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"to_email": "admin@mycompany.com"}'
```

---

## 12. Real-Time WebSockets Telemetry

The platform provides live full-duplex WebSocket feeds for live dashboard metrics and instant report table updates.

### Endpoints
- **Reports Live Feed**: `ws://localhost:8000/ws/reports?token=<jwt_token>`
- **Global Events Feed**: `ws://localhost:8000/ws/events?token=<jwt_token>`

### Message Types
1. `cdr.created`: Dispatched instantaneously when a call concludes and its CDR is processed.
   ```json
   {
     "event": "cdr.created",
     "type": "cdr.created",
     "data": {
       "caller_id_number": "1001",
       "destination_number": "+15551234567",
       "direction": "outbound",
       "hangup_cause": "NORMAL_CLEARING",
       "billsec": 42
     }
   }
   ```
2. `voicemail.created`: Dispatched when a caller records a voice message.
   ```json
   {
     "event": "voicemail.created",
     "type": "voicemail.created",
     "data": {
       "extension_number": "1001",
       "caller_id_number": "+15559876543",
       "duration": 25
     }
   }
   ```
3. `ping` / `pong`: Heartbeat keeping client sockets alive through proxies.
