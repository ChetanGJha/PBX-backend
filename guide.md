# Build a Production-Grade Multi-Tenant PBX Using FreeSWITCH

You are a senior VoIP/PBX architect and software engineer specializing in FreeSWITCH, SIP, WebRTC, PostgreSQL, Python FastAPI, Kamailio, and multi-tenant communications platforms.

I want to build a **fully functional, production-grade, multi-tenant PBX platform using FreeSWITCH as the telephony/media engine**.

Do not create a toy/demo PBX. Design and implement the system as a real commercial PBX platform with tenant isolation, APIs, database persistence, web administration, real-time call state, recordings, CDRs, voicemail, IVR, queues, and production deployment support.

---

# 1. Core Technology Requirements

Use:

* FreeSWITCH 1.10.x
* PostgreSQL
* Python FastAPI
* Flasgger for Swagger/OpenAPI documentation where appropriate
* Redis where useful for real-time state/cache
* PostgreSQL for persistent application data
* FreeSWITCH ESL/event socket for real-time events and commands
* mod_xml_curl for dynamic FreeSWITCH configuration
* Sofia SIP stack
* WebRTC support
* SIP.js or JsSIP for browser softphone
* Nginx as reverse proxy
* Kamailio as optional SIP SBC/load balancer
* Docker/Docker Compose for development
* Kubernetes-compatible architecture for production
* S3/GCS-compatible object storage for recordings
* Local filesystem recording support as an alternative
* FFmpeg/sox where audio conversion is required

Do NOT use:

* python-esl
* flask-restx
* swag_from
* automatic database creation from the application

The PostgreSQL database/schema must be supplied as SQL migrations/scripts.

Prefer procedural Python code rather than unnecessary OOP.

---

# 2. Multi-Tenant Architecture

The platform must support complete tenant isolation.

Each tenant must have:

* Tenant ID
* Tenant name
* Tenant domain
* SIP domain
* Branding
* Timezone
* Business hours
* Recording policies
* Voicemail settings
* Music-on-hold settings
* Email settings
* Caller-ID policies
* IVR configuration
* PBX settings

Every telephony object must belong to a tenant.

Examples:

* extensions
* ring groups
* hunt groups
* queues
* IVRs
* DIDs
* voicemail boxes
* recordings
* CDRs
* announcements
* music-on-hold
* call forwarding
* conferences

Tenant A must NEVER be able to:

* call Tenant B's extension
* access Tenant B's recordings
* access Tenant B's CDRs
* access Tenant B's voicemail
* access Tenant B's IVRs
* access Tenant B's queues
* access Tenant B's configuration
* modify Tenant B's users/extensions

Implement tenant isolation at:

1. API layer
2. Database layer
3. FreeSWITCH dialplan layer
4. SIP authentication layer
5. Recording storage layer
6. CDR query layer

---

# 3. User Roles

Implement RBAC with:

## Platform Super Admin

Can manage:

* tenants
* platform configuration
* SIP infrastructure
* FreeSWITCH nodes
* SIP trunks
* system settings
* storage
* email/SMTP
* monitoring

## Tenant Admin

Can manage:

* extensions
* users
* ring groups
* hunt groups
* IVRs
* DIDs
* call forwarding
* voicemail
* recordings
* CDRs
* music on hold
* announcements
* tenant settings

## Supervisor

Can manage:

* agents/extensions
* call monitoring
* queues
* recordings
* CDRs
* reports

## Agent/User

Can:

* register SIP/WebRTC endpoint
* make calls
* receive calls
* transfer calls
* hold calls
* park calls
* retrieve parked calls
* access voicemail
* configure forwarding
* configure DND
* view own call history

---

# 4. Extension Management

Implement complete extension management.

Extension fields:

* extension number
* tenant
* username
* display name
* email
* SIP password
* voicemail PIN
* caller ID name
* caller ID number
* outbound caller ID
* timezone
* enabled/disabled
* DND status
* call waiting status
* recording policy
* call forwarding settings
* no-answer timeout
* busy destination
* no-answer destination
* always-forward destination

Provide APIs:

POST /extensions

GET /extensions

GET /extensions/{id}

PUT /extensions/{id}

DELETE /extensions/{id}

POST /extensions/{id}/reset-password

POST /extensions/{id}/register

GET /extensions/{id}/status

GET /extensions/{id}/calls

The extension status must support:

* Registered
* Unregistered
* Ringing
* In Call
* On Hold
* DND
* Busy
* Unknown

Use FreeSWITCH events to maintain real-time registration/call state.

---

# 5. SIP Registration

Implement SIP registration using FreeSWITCH Sofia.

Support:

* SIP phones
* Zoiper
* MicroSIP
* WebRTC
* SIP.js
* JsSIP

Each tenant must have its own SIP domain.

Example:

tenant-a.example.com

tenant-b.example.com

The generated FreeSWITCH directory configuration must be tenant-aware.

Use mod_xml_curl for:

* directory
* dialplan
* configuration where appropriate

Example:

/freeswitch/xml

The API must return the appropriate XML based on:

* section
* tag
* key_value
* tenant
* domain
* extension

---

# 6. Internal Calling

Implement extension-to-extension calling.

Example:

1001 -> 1002

1002 -> 1003

Calls must remain inside the tenant.

If:

Tenant A:

1001

Tenant A:

1002

Tenant B:

1001

Tenant A/1001 must NOT be able to dial Tenant B/1001.

Explicitly validate tenant ownership before routing.

---

# 7. Ring Groups

Implement ring groups.

Support strategies:

## Simultaneous

Ring all members simultaneously.

Example:

1001
1002
1003

## Sequential

Ring:

1001

then 1002

then 1003

## Rollover

Try primary destination and then fallback destinations.

Configuration:

* ring group name
* extension
* members
* strategy
* timeout
* retry count
* failover destination
* voicemail destination
* external number
* business hours

APIs:

POST /ring-groups

GET /ring-groups

PUT /ring-groups/{id}

DELETE /ring-groups/{id}

POST /ring-groups/{id}/members

DELETE /ring-groups/{id}/members/{extension}

---

# 8. Hunt Groups / Follow-Me / Find-Me

Implement:

* Hunt groups
* Follow-me
* Find-me

Allow destinations such as:

* internal extension
* multiple extensions
* external phone number
* mobile number
* voicemail
* another ring group

Support:

* sequential ringing
* simultaneous ringing
* timeout
* retry
* failover

Example:

1001

-> 1001

-> Mobile

-> 1002

-> Voicemail

---

# 9. Call Forwarding

Support:

## Always Forward

All calls redirect immediately.

## Busy Forward

Redirect when extension is busy.

## No Answer Forward

Redirect after configurable timeout.

Configuration:

forward_always_enabled

forward_always_destination

forward_busy_enabled

forward_busy_destination

forward_no_answer_enabled

forward_no_answer_destination

forward_no_answer_timeout

Validate destinations to prevent tenant bypass.

---

# 10. Call Transfer

Implement:

## Blind Transfer

Example:

1001 transfers caller to 1002.

## Attended Transfer

Example:

1001:

Caller -> 1002

1001 talks to 1002

Then completes transfer.

Implement FreeSWITCH-compatible transfer mechanisms and SIP REFER handling.

Provide softphone UI controls.

---

# 11. Call Hold

Support:

* hold
* resume
* multiple calls
* call swapping

Use SIP re-INVITE/session state appropriately.

Expose call state to WebSocket clients.

---

# 12. Call Parking

Implement call parking.

Example:

Caller -> Extension 1001

1001 parks caller

System returns:

Park Slot 701

Another extension:

701

retrieves the call.

Support:

* configurable parking slots
* tenant-specific parking
* timeout
* timeout destination
* parking announcements

---

# 13. Call Pickup

Implement:

* directed pickup
* group pickup

Example:

*8

Pickup ringing extension.

Or:

*801

Pickup extension 801.

Pickup must be tenant restricted.

---

# 14. Call Waiting

Support:

* enable/disable call waiting
* per-extension setting
* SIP call waiting
* second incoming call
* call waiting indication

Expose API:

PUT /extensions/{id}/call-waiting

---

# 15. Do Not Disturb

Implement DND.

Support:

* enable
* disable
* temporary DND
* permanent DND

When DND is active:

Incoming call -> configurable destination

Options:

* busy
* voicemail
* custom destination

Provide:

POST /extensions/{id}/dnd

---

# 16. Caller ID Management

Support caller ID per extension.

Fields:

* caller ID name
* caller ID number
* outbound CLI
* emergency caller ID
* anonymous calling

Allow tenant administrators to configure allowed outbound caller IDs.

Prevent arbitrary caller ID spoofing.

For outbound calls validate the requested CLI against tenant-owned numbers.

Support:

From

P-Asserted-Identity

Remote-Party-ID where required by carrier.

---

# 17. Conferencing

Implement conference calling using FreeSWITCH conference functionality.

Support:

* conference rooms
* PIN
* moderator PIN
* participant mute
* participant unmute
* kick participant
* lock conference
* unlock conference
* recording
* conference announcements
* participant list

APIs:

POST /conferences

GET /conferences

GET /conferences/{id}

POST /conferences/{id}/participants/{id}/mute

POST /conferences/{id}/participants/{id}/kick

---

# 18. Auto Attendant / IVR

Build a complete multi-level IVR system.

Example:

Incoming DID

-> Welcome Announcement

"Welcome to ABC Company"

Press 1:

Sales

Press 2:

Support

Press 3:

Accounts

Press 4:

Directory

Press 0:

Operator

Support nested IVRs.

Example:

Main IVR

1 Sales

1 Sales Team

2 Sales Manager

2 Support

1 Technical Support

2 Billing

3 Accounts

Implement:

* configurable prompts
* DTMF
* timeout
* invalid input
* retry count
* maximum retries
* failover destination
* business-hours routing
* holiday routing

IVR configuration must be stored in PostgreSQL.

---

# 19. Dial-by-Extension

Allow callers to dial an extension from IVR.

Example:

"Please enter the extension number."

Validate:

* extension exists
* extension belongs to same tenant

Then route call.

---

# 20. Dial-by-Name Directory

Implement dial-by-name.

Use extension:

* first name
* last name
* display name

Generate searchable directory.

Allow callers to enter letters using DTMF.

Example:

2 = ABC

3 = DEF

etc.

---

# 21. Announcements

Implement tenant-specific announcements.

Support:

* upload WAV/MP3
* text-to-speech generated prompts
* welcome greeting
* IVR prompts
* queue announcements
* voicemail greeting
* holiday announcement

Store metadata in PostgreSQL.

Store files:

Local filesystem

or

GCS/S3-compatible object storage.

---

# 22. Music on Hold

Support:

* tenant-level MOH
* queue-level MOH
* extension-specific MOH if useful

Allow:

* upload audio
* playlist
* random playback
* sequential playback

Do not mix tenant MOH directories.

---

# 23. Voicemail

Implement voicemail per extension.

Features:

* voicemail box
* PIN
* greeting
* unavailable greeting
* busy greeting
* message recording
* message playback
* delete
* save
* forward
* voicemail-to-email

Support:

*97

for voicemail access.

Also support:

*98

for voicemail login to another mailbox where permitted.

---

# 24. Voicemail-to-Email

When voicemail is received:

1. Record audio.
2. Store recording.
3. Create voicemail database record.
4. Send email.
5. Attach audio file.
6. Include:

   * caller number
   * caller name
   * date/time
   * duration
   * tenant
   * extension

SMTP configuration must be tenant configurable with platform defaults.

---

# 25. Call Recording

Implement configurable call recording.

Recording modes:

* all calls
* inbound only
* outbound only
* extension based
* queue based
* on-demand

Support:

* start recording
* stop recording
* pause recording where appropriate

Provide recording policy hierarchy:

Platform

Tenant

Queue

Extension

Call

More-specific policy overrides less-specific policy.

Record:

* UUID
* tenant
* extension
* caller
* callee
* direction
* start time
* end time
* duration
* recording path
* storage provider
* file format
* file size
* encryption status

Support WAV/MP3/OGG as required.

---

# 26. Recording Storage

Support:

## Local

Example:

/var/lib/freeswitch/recordings/{tenant}/{YYYY}/{MM}/{DD}/

## Google Cloud Storage

Example:

gs://bucket/{tenant}/{YYYY}/{MM}/{DD}/

## S3

Example:

s3://bucket/{tenant}/{YYYY}/{MM}/{DD}/

Create an abstraction so the application can switch storage providers.

Never expose raw storage credentials to the browser.

Provide secure authenticated playback/download endpoints.

---

# 27. Recording Portal

Build a recording management interface.

Features:

* search
* filter
* tenant
* extension
* caller
* destination
* date
* direction
* duration
* queue
* call UUID

Actions:

* playback
* download
* delete according to retention policy
* metadata view

Use HTTP range requests for audio streaming.

---

# 28. CDR

Implement comprehensive Call Detail Records.

Fields should include at minimum:

* UUID
* tenant_id
* direction
* caller_number
* caller_name
* destination
* source_extension
* destination_extension
* DID
* SIP trunk
* start_time
* answer_time
* end_time
* duration
* billsec
* hangup_cause
* hangup_code
* recording_id
* transfer information
* queue information
* IVR information
* ring group information
* conference information

Create indexes for:

* tenant
* UUID
* caller
* destination
* extension
* DID
* start_time
* direction
* hangup_cause

---

# 29. CDR Search

Implement:

GET /cdr

Filters:

tenant

extension

caller

callee

DID

direction

date_from

date_to

duration

hangup_cause

queue

ring_group

recorded

Provide:

* pagination
* sorting
* filtering
* CSV export

Example:

GET /cdr/export?format=csv

Tenant users must only see their own tenant's CDRs.

---

# 30. Real-Time Call Monitoring

Create a WebSocket service.

Provide real-time events:

* extension registered
* extension unregistered
* call started
* call ringing
* call answered
* call held
* call resumed
* call transferred
* call parked
* call retrieved
* call ended
* recording started
* recording stopped
* DND changed
* voicemail received

Use FreeSWITCH ESL/event socket.

Do NOT use python-esl.

Implement the ESL protocol using a native TCP socket/client implementation or another lightweight compatible mechanism.

---

# 31. FreeSWITCH XML Architecture

Use mod_xml_curl.

Do not create huge static XML configuration files for tenant data.

Implement endpoints such as:

POST /freeswitch/xml

or separate endpoints:

/freeswitch/directory

/freeswitch/dialplan

/freeswitch/configuration

/freeswitch/callcenter

The XML response must be dynamically generated from PostgreSQL.

Handle FreeSWITCH requests based on:

section

tag_name

key_name

key_value

Event headers must be logged during development.

---

# 32. Dialplan Architecture

Create clean FreeSWITCH dialplan contexts.

Example:

public

tenant-{tenant_id}

internal

outbound

inbound

ivr

conference

voicemail

parking

feature-codes

Never route calls between tenants.

Implement feature codes such as:

*72 - Call Forward Always Enable

*73 - Call Forward Always Disable

*90 - Call Forward Busy Enable

*91 - Call Forward Busy Disable

*92 - Call Forward No Answer Enable

*93 - Call Forward No Answer Disable

*78 - DND Enable

*79 - DND Disable

*97 - Voicemail

*98 - Voicemail Login

*8 - Call Pickup

*70 - Call Waiting

*74 - Call Park

Define these as configurable feature codes rather than hardcoding them throughout the application.

---

# 33. Outbound Calling

Implement SIP trunk management.

Fields:

* provider
* host
* port
* transport
* username
* password
* realm
* caller ID
* codecs
* registration
* enabled
* priority

Support:

* multiple trunks
* trunk failover
* tenant-specific trunks
* outbound prefixes
* dial patterns
* caller ID validation

Example:

9 + 18005551234

should strip 9 and send:

18005551234

---

# 34. DID Management

Implement DID management.

Fields:

* DID
* tenant
* inbound destination
* IVR
* ring group
* hunt group
* queue
* extension
* conference
* voicemail
* enabled

Inbound routing:

DID

-> tenant

-> destination

Never allow a DID belonging to Tenant A to route into Tenant B without explicit platform-level permission.

---

# 35. Business Hours

Implement:

* business hours
* holidays
* holiday calendars
* timezone
* open destination
* closed destination

Example:

Monday-Friday:

09:00-18:00

Outside hours:

Closed announcement

-> voicemail

or

after-hours IVR.

---

# 36. Database

Create complete PostgreSQL schema.

At minimum tables:

tenants

users

roles

permissions

user_roles

extensions

extension_settings

ring_groups

ring_group_members

hunt_groups

hunt_group_members

call_forwarding

dnd_settings

call_waiting_settings

parking_slots

pickup_groups

ivr_menus

ivr_nodes

ivr_actions

announcements

music_on_hold

voicemail_boxes

voicemail_messages

recording_policies

recordings

cdr

sip_trunks

outbound_routes

outbound_route_patterns

dids

conferences

conference_participants

business_hours

holidays

audit_logs

system_settings

storage_settings

email_settings

Create proper:

PKs

FKs

unique constraints

indexes

tenant_id indexes

timestamps

soft deletion where appropriate.

Do not make the application automatically create the database.

Provide SQL migration files.

---

# 37. REST API

Create a complete REST API.

Organize:

/api/v1/auth

/api/v1/tenants

/api/v1/users

/api/v1/extensions

/api/v1/ring-groups

/api/v1/hunt-groups

/api/v1/call-forwarding

/api/v1/dnd

/api/v1/call-waiting

/api/v1/parking

/api/v1/ivr

/api/v1/announcements

/api/v1/music-on-hold

/api/v1/voicemail

/api/v1/recordings

/api/v1/cdr

/api/v1/dids

/api/v1/sip-trunks

/api/v1/outbound-routes

/api/v1/conferences

/api/v1/business-hours

/api/v1/settings

/api/v1/freeswitch

/api/v1/monitoring

All APIs must have:

* validation
* authentication
* authorization
* tenant isolation
* error handling
* logging
* pagination
* consistent response format

---

# 38. Authentication

Implement:

* JWT
* access token
* refresh token
* password hashing
* RBAC
* tenant-aware authorization

Do not store plain-text passwords.

SIP passwords should be stored securely and should not be exposed through normal API responses.

---

# 39. Web Administration Portal

Build a modern PBX admin interface.

Main navigation:

Dashboard

Extensions

Ring Groups

Hunt Groups

Call Forwarding

DND

Call Parking

IVR

Announcements

Music on Hold

Voicemail

Recordings

CDR

DIDs

SIP Trunks

Outbound Routes

Conferences

Business Hours

Users

Settings

Monitoring

---

# 40. PBX Dashboard

Show:

* registered extensions
* offline extensions
* active calls
* calls today
* inbound calls
* outbound calls
* missed calls
* average call duration
* recordings
* voicemail count
* trunk status

Real-time active call table:

UUID

Caller

Destination

Extension

State

Duration

Direction

Tenant

Recording

---

# 41. WebRTC Softphone

Build a browser softphone.

Support:

* registration
* dialpad
* incoming calls
* outgoing calls
* answer
* reject
* hold
* resume
* mute
* transfer
* attended transfer
* blind transfer
* call park
* call pickup
* DTMF
* conference
* recording status
* call history

Use SIP.js or JsSIP.

Use secure WSS.

---

# 42. Security

Implement:

* HTTPS
* WSS
* JWT
* CORS restrictions
* rate limiting
* SIP brute-force protection
* fail2ban-compatible logging
* tenant isolation
* API audit logs
* secure secrets
* encrypted storage where required
* secure recording URLs
* authorization checks on every tenant resource

Never trust tenant_id supplied by the client.

Derive tenant context from authenticated user/token wherever possible.

---

# 43. Audit Logging

Record:

* user
* tenant
* action
* resource
* resource ID
* old value
* new value
* IP
* timestamp

Examples:

Extension created

Extension password changed

Recording downloaded

CDR exported

Trunk modified

IVR modified

DID reassigned

---

# 44. High Availability

Design FreeSWITCH for active-active operation.

Example:

Kamailio/SBC

```
    |
    +---- FreeSWITCH Node 1
    |
    +---- FreeSWITCH Node 2
    |
    +---- FreeSWITCH Node 3
```

Use PostgreSQL as shared application database.

Do not use Keepalived.

Use Kamailio/HAProxy where appropriate.

Implement:

* node health checks
* SIP load balancing
* failover
* shared configuration
* shared recording storage
* centralized CDR
* event synchronization

Explain the limitations of active-active SIP/PBX failover, especially for already-established media sessions.

---

# 45. Monitoring

Expose:

/health

/ready

/metrics

Monitor:

* FreeSWITCH status
* SIP registrations
* active channels
* CPU
* memory
* disk
* RTP ports
* SIP trunks
* PostgreSQL
* Redis
* API
* recording storage

Provide Prometheus-compatible metrics where possible.

---

# 46. Logging

Use structured logs.

Separate:

application logs

SIP logs

FreeSWITCH logs

CDR logs

audit logs

recording logs

Use correlation IDs.

For every call, maintain a common call UUID.

---

# 47. Testing

Create automated tests for:

* tenant isolation
* extension creation
* SIP directory XML
* dialplan XML
* internal calls
* outbound calls
* inbound DID routing
* ring groups
* hunt groups
* forwarding
* DND
* voicemail
* IVR
* recording
* CDR
* authentication
* authorization

Create integration tests where possible.

---

# 48. Docker Deployment

Provide:

docker-compose.yml

Services:

postgres

redis

api

worker

nginx

freeswitch

optional:

kamailio

Create persistent volumes for:

PostgreSQL

FreeSWITCH recordings

FreeSWITCH sounds

configuration

logs

---

# 49. Production Deployment

Provide deployment documentation for:

Ubuntu 22.04/24.04

Docker

Kubernetes

GKE

Include:

* networking
* SIP ports
* RTP ports
* WebSocket/WSS
* TLS
* firewall
* NAT
* public/private IP
* load balancing
* persistent storage

Clearly document required ports.

Example categories:

SIP UDP/TCP

SIP TLS

RTP UDP range

WSS

HTTPS

ESL

PostgreSQL

Redis

---

# 50. Deliverables

Do not stop at architecture.

Produce the implementation in logical phases.

## Phase 1

Architecture

Database schema

Project structure

Configuration

Environment variables

Docker setup

## Phase 2

Authentication

RBAC

Tenant management

Extension management

SIP directory

mod_xml_curl

## Phase 3

Internal calling

Ring groups

Hunt groups

Call forwarding

DND

Call waiting

Call transfer

Parking

Pickup

## Phase 4

IVR

Announcements

Dial-by-extension

Dial-by-name

Business hours

DID routing

## Phase 5

Voicemail

Voicemail-to-email

## Phase 6

Call recording

Recording storage

Recording portal

## Phase 7

CDR

CDR search

CSV export

Reports

## Phase 8

Conference

## Phase 9

WebRTC softphone

## Phase 10

Real-time monitoring

ESL event processing

WebSockets

## Phase 11

HA

Kamailio

Multiple FreeSWITCH nodes

Shared storage

Failover

## Phase 12

Production hardening

Monitoring

Security

Testing

Documentation

---

# 51. Critical Implementation Rule

For every feature, provide:

1. PostgreSQL schema
2. API endpoint
3. API validation
4. FreeSWITCH configuration
5. FreeSWITCH dialplan
6. mod_xml_curl implementation where applicable
7. Actual call flow
8. Example SIP call
9. Example API request
10. Example API response
11. Error handling
12. Tenant isolation logic
13. Test case

Do not provide pseudocode where production code can be provided.

Do not omit FreeSWITCH configuration.

Do not assume a feature works simply because an API exists.

The feature must result in an actual SIP call flow through FreeSWITCH.

---

# 52. Important FreeSWITCH Design Principle

FreeSWITCH is the media/telephony engine.

The Python application is the control plane.

PostgreSQL is the persistent configuration/state database.

ESL is used for real-time FreeSWITCH control/events.

mod_xml_curl is used for dynamic FreeSWITCH configuration.

The architecture should therefore be:

```
                ┌──────────────────────┐
                │      Web Portal      │
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │     FastAPI API      │
                │   Control Plane      │
                └───────┬───────┬──────┘
                        │       │
             ┌──────────┘       └──────────┐
             ▼                             ▼
      ┌──────────────┐              ┌──────────────┐
      │ PostgreSQL   │              │    Redis     │
      └──────────────┘              └──────────────┘
             ▲
             │
       mod_xml_curl
             │
             ▼
      ┌──────────────────┐
      │    FreeSWITCH    │
      │ SIP + RTP + IVR  │
      │ Media + Calls    │
      └────────┬─────────┘
               │
               ▼
         SIP/WebRTC
          Endpoints
```

For multiple FreeSWITCH nodes:

```
                     ┌─────────────┐
                     │  Kamailio   │
                     │     SBC     │
                     └──────┬──────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
      FreeSWITCH-1    FreeSWITCH-2    FreeSWITCH-3
            │               │               │
            └───────────────┼───────────────┘
                            │
                     ┌──────▼──────┐
                     │ PostgreSQL  │
                     └─────────────┘
```

---

# 53. Expected Development Style

Do not dump thousands of lines of code at once.

Work incrementally.

For every phase:

1. Explain the architecture briefly.
2. Show directory structure.
3. Create database migration.
4. Create backend code.
5. Create FreeSWITCH configuration.
6. Create XML-CURL implementation.
7. Create API endpoints.
8. Provide curl examples.
9. Provide FreeSWITCH CLI commands.
10. Provide test instructions.
11. Explain expected output.
12. Only then move to the next phase.

Every generated file must have:

* filename
* complete contents
* dependencies
* configuration requirements
* purpose

If a file must be modified later, provide the complete updated file rather than ambiguous snippets.

---

# 54. Production Quality Requirement

Assume this PBX will eventually serve:

* thousands of tenants
* tens of thousands of extensions
* multiple FreeSWITCH nodes
* high concurrent call volumes

Therefore design for:

* connection pooling
* database indexes
* async APIs where appropriate
* background workers
* event-driven processing
* idempotency
* retries
* transaction safety
* distributed locking where necessary
* horizontal scaling
* observability
* graceful failure

Do not introduce unnecessary microservices unless there is a concrete operational reason.

---

# 55. First Task

Start with:

1. Complete system architecture.
2. Component diagram.
3. Database ER design.
4. Complete PostgreSQL schema.
5. Recommended project directory structure.
6. FreeSWITCH configuration architecture.
7. mod_xml_curl architecture.
8. Tenant isolation strategy.
9. SIP/WebRTC architecture.
10. Call-flow architecture.
11. Recording architecture.
12. CDR architecture.
13. HA architecture.
14. Security architecture.
15. Development roadmap.

Do not start implementing the APIs until the architecture and database design are established.

After presenting the architecture, wait for confirmation before proceeding to Phase 1 implementation.
