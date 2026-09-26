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
