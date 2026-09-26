-- Multi-Tenant PBX Platform Schema
-- PostgreSQL 14+ compatible
-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Tenants Table
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    domain VARCHAR(255) UNIQUE NOT NULL,
    sip_domain VARCHAR(255) UNIQUE NOT NULL,
    branding JSONB DEFAULT '{}'::jsonb,
    timezone VARCHAR(50) DEFAULT 'UTC',
    enabled BOOLEAN NOT NULL DEFAULT true,
    max_extensions INT DEFAULT 100,
    max_concurrent_calls INT DEFAULT 20,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE INDEX idx_tenants_domain ON tenants(domain);
CREATE INDEX idx_tenants_sip_domain ON tenants(sip_domain);

-- 2. Roles Table
CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(50) UNIQUE NOT NULL, -- SUPER_ADMIN, TENANT_ADMIN, SUPERVISOR, AGENT
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed System Roles
INSERT INTO roles (name, description) VALUES
('SUPER_ADMIN', 'Platform Super Administrator'),
('TENANT_ADMIN', 'Tenant Administrator'),
('SUPERVISOR', 'Call Center / Extension Supervisor'),
('AGENT', 'Standard Extension / Softphone User');

-- 3. Permissions Table
CREATE TABLE permissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Users Table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE, -- NULL for Super Admin
    username VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(50),
    last_name VARCHAR(50),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ NULL,
    UNIQUE(tenant_id, username),
    UNIQUE(tenant_id, email)
);

CREATE INDEX idx_users_tenant ON users(tenant_id);

-- 5. User Roles Junction Table
CREATE TABLE user_roles (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

-- 6. Extensions Table
CREATE TABLE extensions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    extension_number VARCHAR(20) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    email VARCHAR(255),
    sip_password VARCHAR(255) NOT NULL,
    voicemail_pin VARCHAR(20) NOT NULL DEFAULT '1234',
    caller_id_name VARCHAR(100),
    caller_id_number VARCHAR(50),
    outbound_caller_id VARCHAR(50),
    emergency_caller_id VARCHAR(50),
    timezone VARCHAR(50) DEFAULT 'UTC',
    enabled BOOLEAN NOT NULL DEFAULT true,
    webrtc_enabled BOOLEAN NOT NULL DEFAULT true,
    no_answer_timeout INT NOT NULL DEFAULT 20,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ NULL,
    UNIQUE(tenant_id, extension_number)
);

CREATE INDEX idx_extensions_tenant ON extensions(tenant_id);
CREATE INDEX idx_extensions_lookup ON extensions(tenant_id, extension_number);

-- 7. Extension Settings Table
CREATE TABLE extension_settings (
    extension_id UUID PRIMARY KEY REFERENCES extensions(id) ON DELETE CASCADE,
    codecs JSONB DEFAULT '["opus", "G722", "PCMU", "PCMA"]'::jsonb,
    max_contacts INT DEFAULT 5,
    allow_anonymous BOOLEAN DEFAULT false,
    record_inbound BOOLEAN DEFAULT false,
    record_outbound BOOLEAN DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 8. Ring Groups Table
CREATE TABLE ring_groups (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    extension_number VARCHAR(20) NOT NULL,
    strategy VARCHAR(30) NOT NULL DEFAULT 'simultaneous', -- simultaneous, sequential, rollover
    ring_timeout INT NOT NULL DEFAULT 20,
    distinctive_ring VARCHAR(50),
    failover_destination_type VARCHAR(30) DEFAULT 'voicemail', -- voicemail, extension, external, hangup
    failover_destination VARCHAR(100),
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, extension_number)
);

CREATE INDEX idx_ring_groups_tenant ON ring_groups(tenant_id);

-- 9. Ring Group Members Table
CREATE TABLE ring_group_members (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ring_group_id UUID NOT NULL REFERENCES ring_groups(id) ON DELETE CASCADE,
    extension_id UUID REFERENCES extensions(id) ON DELETE CASCADE,
    external_number VARCHAR(50),
    priority INT NOT NULL DEFAULT 1,
    delay_seconds INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 10. Hunt Groups / Follow-Me Table
CREATE TABLE hunt_groups (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    extension_id UUID NOT NULL REFERENCES extensions(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT false,
    strategy VARCHAR(30) NOT NULL DEFAULT 'sequential',
    confirm_call BOOLEAN DEFAULT false,
    confirm_key VARCHAR(5) DEFAULT '1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_hunt_groups_tenant ON hunt_groups(tenant_id);

-- 11. Hunt Group Members Table
CREATE TABLE hunt_group_members (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    hunt_group_id UUID NOT NULL REFERENCES hunt_groups(id) ON DELETE CASCADE,
    destination_type VARCHAR(30) NOT NULL, -- extension, external, voicemail
    destination VARCHAR(100) NOT NULL,
    priority INT NOT NULL DEFAULT 1,
    timeout INT NOT NULL DEFAULT 15,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 12. Call Forwarding Table
CREATE TABLE call_forwarding (
    extension_id UUID PRIMARY KEY REFERENCES extensions(id) ON DELETE CASCADE,
    forward_always_enabled BOOLEAN DEFAULT false,
    forward_always_destination VARCHAR(100),
    forward_busy_enabled BOOLEAN DEFAULT false,
    forward_busy_destination VARCHAR(100),
    forward_no_answer_enabled BOOLEAN DEFAULT false,
    forward_no_answer_destination VARCHAR(100),
    forward_no_answer_timeout INT DEFAULT 20,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 13. DND Settings Table
CREATE TABLE dnd_settings (
    extension_id UUID PRIMARY KEY REFERENCES extensions(id) ON DELETE CASCADE,
    enabled BOOLEAN DEFAULT false,
    destination_type VARCHAR(30) DEFAULT 'voicemail',
    destination VARCHAR(100),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 14. Call Waiting Settings Table
CREATE TABLE call_waiting_settings (
    extension_id UUID PRIMARY KEY REFERENCES extensions(id) ON DELETE CASCADE,
    enabled BOOLEAN DEFAULT true,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 15. Parking Slots Table
CREATE TABLE parking_slots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    slot_number VARCHAR(10) NOT NULL, -- e.g. 701, 702
    timeout INT DEFAULT 60,
    timeout_destination_type VARCHAR(30) DEFAULT 'extension',
    timeout_destination VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, slot_number)
);

CREATE INDEX idx_parking_slots_tenant ON parking_slots(tenant_id);

-- 16. Pickup Groups Table
CREATE TABLE pickup_groups (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    group_number VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, group_number)
);

-- 17. IVR Menus Table
CREATE TABLE ivr_menus (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    extension_number VARCHAR(20),
    greeting_announcement_id UUID,
    invalid_announcement_id UUID,
    timeout_announcement_id UUID,
    timeout INT DEFAULT 10,
    max_retries INT DEFAULT 3,
    allow_direct_extension BOOLEAN DEFAULT true,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, extension_number)
);

CREATE INDEX idx_ivr_menus_tenant ON ivr_menus(tenant_id);

-- 18. IVR Nodes Table
CREATE TABLE ivr_nodes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ivr_menu_id UUID NOT NULL REFERENCES ivr_menus(id) ON DELETE CASCADE,
    dtmf_key VARCHAR(5) NOT NULL, -- 0-9, *, #, timeout, invalid
    action_type VARCHAR(30) NOT NULL, -- extension, ring_group, ivr, voicemail, hangup, external
    action_target VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(ivr_menu_id, dtmf_key)
);

-- 19. IVR Actions Table
CREATE TABLE ivr_actions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ivr_node_id UUID NOT NULL REFERENCES ivr_nodes(id) ON DELETE CASCADE,
    step_order INT NOT NULL DEFAULT 1,
    action VARCHAR(50) NOT NULL,
    parameters JSONB DEFAULT '{}'::jsonb
);

-- 20. Announcements Table
CREATE TABLE announcements (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size BIGINT DEFAULT 0,
    duration INT DEFAULT 0,
    tts_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_announcements_tenant ON announcements(tenant_id);

-- 21. Music On Hold Table
CREATE TABLE music_on_hold (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    directory_path VARCHAR(500) NOT NULL,
    mode VARCHAR(20) DEFAULT 'playlist', -- playlist, random
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_music_on_hold_tenant ON music_on_hold(tenant_id);

-- 22. Voicemail Boxes Table
CREATE TABLE voicemail_boxes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    extension_id UUID NOT NULL REFERENCES extensions(id) ON DELETE CASCADE,
    mailbox VARCHAR(20) NOT NULL,
    password VARCHAR(20) NOT NULL DEFAULT '1234',
    email_notification BOOLEAN DEFAULT true,
    email_attach_file BOOLEAN DEFAULT true,
    email_address VARCHAR(255),
    delete_after_email BOOLEAN DEFAULT false,
    greeting_path VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, mailbox)
);

CREATE INDEX idx_voicemail_boxes_tenant ON voicemail_boxes(tenant_id);

-- 23. Voicemail Messages Table
CREATE TABLE voicemail_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    voicemail_box_id UUID NOT NULL REFERENCES voicemail_boxes(id) ON DELETE CASCADE,
    caller_id_name VARCHAR(100),
    caller_id_number VARCHAR(50),
    file_path VARCHAR(500) NOT NULL,
    duration INT NOT NULL,
    read BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 24. Recording Policies Table
CREATE TABLE recording_policies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    scope VARCHAR(30) NOT NULL, -- tenant, queue, extension
    target_id UUID,
    record_inbound BOOLEAN DEFAULT false,
    record_outbound BOOLEAN DEFAULT false,
    record_internal BOOLEAN DEFAULT false,
    format VARCHAR(10) DEFAULT 'wav',
    storage_provider VARCHAR(20) DEFAULT 'local', -- local, s3, gcs
    retention_days INT DEFAULT 90,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_recording_policies_tenant ON recording_policies(tenant_id);

-- 25. Recordings Table
CREATE TABLE recordings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    call_uuid VARCHAR(100) NOT NULL,
    source_extension VARCHAR(20),
    caller_number VARCHAR(50),
    destination_number VARCHAR(50),
    direction VARCHAR(20) NOT NULL, -- inbound, outbound, internal
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    duration INT DEFAULT 0,
    file_path VARCHAR(500) NOT NULL,
    storage_provider VARCHAR(20) NOT NULL DEFAULT 'local',
    file_format VARCHAR(10) DEFAULT 'wav',
    file_size BIGINT DEFAULT 0,
    encryption_status VARCHAR(20) DEFAULT 'none',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_recordings_tenant ON recordings(tenant_id);
CREATE INDEX idx_recordings_uuid ON recordings(call_uuid);

-- 26. CDR Table
CREATE TABLE cdr (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    call_uuid VARCHAR(100) UNIQUE NOT NULL,
    direction VARCHAR(20) NOT NULL, -- inbound, outbound, internal
    caller_number VARCHAR(50),
    caller_name VARCHAR(100),
    destination VARCHAR(50),
    source_extension VARCHAR(20),
    destination_extension VARCHAR(20),
    did VARCHAR(50),
    sip_trunk_id UUID,
    start_time TIMESTAMPTZ NOT NULL,
    answer_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ NOT NULL,
    duration INT NOT NULL DEFAULT 0,
    billsec INT NOT NULL DEFAULT 0,
    hangup_cause VARCHAR(50),
    hangup_code INT,
    recording_id UUID REFERENCES recordings(id) ON DELETE SET NULL,
    queue_id UUID,
    ivr_id UUID,
    ring_group_id UUID,
    conference_id UUID,
    transfer_history JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cdr_tenant ON cdr(tenant_id);
CREATE INDEX idx_cdr_call_uuid ON cdr(call_uuid);
CREATE INDEX idx_cdr_dates ON cdr(tenant_id, start_time);
CREATE INDEX idx_cdr_source ON cdr(tenant_id, source_extension);
CREATE INDEX idx_cdr_destination ON cdr(tenant_id, destination);

-- 27. SIP Trunks Table
CREATE TABLE sip_trunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE, -- NULL for global trunks
    name VARCHAR(100) NOT NULL,
    provider VARCHAR(100),
    host VARCHAR(255) NOT NULL,
    port INT DEFAULT 5060,
    transport VARCHAR(10) DEFAULT 'udp',
    username VARCHAR(100),
    password VARCHAR(255),
    realm VARCHAR(255),
    caller_id VARCHAR(50),
    codecs JSONB DEFAULT '["PCMU", "PCMA", "G722"]'::jsonb,
    register BOOLEAN DEFAULT true,
    enabled BOOLEAN DEFAULT true,
    priority INT DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 28. Outbound Routes Table
CREATE TABLE outbound_routes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE, -- NULL for global routes
    name VARCHAR(100) NOT NULL,
    priority INT NOT NULL DEFAULT 1,
    strip_digits INT DEFAULT 0,
    prepend_digits VARCHAR(20) DEFAULT '',
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 29. Outbound Route Patterns Table
CREATE TABLE outbound_route_patterns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    outbound_route_id UUID NOT NULL REFERENCES outbound_routes(id) ON DELETE CASCADE,
    pattern VARCHAR(100) NOT NULL, -- Regex pattern e.g. ^(\+?1)?([2-9]\d{9})$
    sip_trunk_id UUID NOT NULL REFERENCES sip_trunks(id) ON DELETE CASCADE,
    priority INT DEFAULT 1
);

-- 30. DIDs Table
CREATE TABLE dids (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    did_number VARCHAR(50) NOT NULL,
    destination_type VARCHAR(30) NOT NULL, -- extension, ring_group, ivr, queue, voicemail, conference
    destination_target VARCHAR(100) NOT NULL,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(did_number)
);

CREATE INDEX idx_dids_tenant ON dids(tenant_id);
CREATE INDEX idx_dids_number ON dids(did_number);

-- 31. Conferences Table
CREATE TABLE conferences (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    extension_number VARCHAR(20) NOT NULL,
    pin VARCHAR(20),
    moderator_pin VARCHAR(20),
    max_members INT DEFAULT 50,
    record_conference BOOLEAN DEFAULT false,
    wait_for_moderator BOOLEAN DEFAULT false,
    announce_join_leave BOOLEAN DEFAULT true,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, extension_number)
);

CREATE INDEX idx_conferences_tenant ON conferences(tenant_id);

-- 32. Conference Participants Table
CREATE TABLE conference_participants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conference_id UUID NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
    member_id INT NOT NULL,
    call_uuid VARCHAR(100) NOT NULL,
    caller_id_name VARCHAR(100),
    caller_id_number VARCHAR(50),
    is_moderator BOOLEAN DEFAULT false,
    is_muted BOOLEAN DEFAULT false,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    left_at TIMESTAMPTZ
);

-- 33. Business Hours Table
CREATE TABLE business_hours (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    timezone VARCHAR(50) DEFAULT 'UTC',
    schedule JSONB NOT NULL, -- e.g. {"mon": [{"start": "09:00", "end": "17:00"}]}
    open_destination_type VARCHAR(30) NOT NULL,
    open_destination_target VARCHAR(100) NOT NULL,
    closed_destination_type VARCHAR(30) NOT NULL,
    closed_destination_target VARCHAR(100) NOT NULL,
    holiday_destination_type VARCHAR(30),
    holiday_destination_target VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_business_hours_tenant ON business_hours(tenant_id);

-- 34. Holidays Table
CREATE TABLE holidays (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    business_hours_id UUID NOT NULL REFERENCES business_hours(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    holiday_date DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 35. Audit Logs Table
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id VARCHAR(100),
    old_value JSONB,
    new_value JSONB,
    ip_address VARCHAR(45),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_tenant ON audit_logs(tenant_id);
CREATE INDEX idx_audit_logs_user ON audit_logs(user_id);

-- 36. System Settings Table
CREATE TABLE system_settings (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 37. Storage Settings Table
CREATE TABLE storage_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE, -- NULL for default platform storage
    provider VARCHAR(20) NOT NULL DEFAULT 'local', -- local, s3, gcs
    config JSONB NOT NULL, -- bucket, region, credentials, etc.
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id)
);

-- 38. Email Settings Table
CREATE TABLE email_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE, -- NULL for platform default
    smtp_host VARCHAR(255) NOT NULL,
    smtp_port INT NOT NULL DEFAULT 587,
    smtp_username VARCHAR(100),
    smtp_password VARCHAR(255),
    from_email VARCHAR(255) NOT NULL,
    from_name VARCHAR(100) DEFAULT 'PBX Voicemail',
    use_tls BOOLEAN DEFAULT true,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id)
);
