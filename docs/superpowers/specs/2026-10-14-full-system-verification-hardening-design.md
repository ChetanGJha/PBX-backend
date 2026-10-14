# Sub-Project 4: Full-System Verification, Hardening & Documentation Handover Design Specification

**Date:** 2026-10-14  
**Status:** In Progress  
**Sub-Project:** 4 of 4  
**Authors:** AI Engineering Lead & PBX Telephony Team  

---

## 1. Scope & Objectives

Sub-Project 4 brings together all 12 initial PBX requirements implemented across Sub-Projects 1, 2, and 3:
1. **Core Telephony & Dialplan Routing (Items 1, 2, 3, 5, 8, 10)**:
   - Item 1: Multi-tenant outbound & inbound routing with tenant DID mapping.
   - Item 2: Extension call forwarding (immediate, busy, no-answer) with failover timeouts.
   - Item 3: Hunt Groups / Ring Groups (simultaneous, sequential, random distribution).
   - Item 5: Call Queues & Call Center (`mod_callcenter`, agent tiers, strategy, music-on-hold).
   - Item 8: Conference Bridges (multi-tenant rooms, PIN protection, audio mixing).
   - Item 10: IVR / Auto-Attendant (multi-level menus, timeout and invalid key failovers).
2. **CDR Pipeline, Real-Time Reports & Telemetry (Items 6, 7, 11)**:
   - Item 6: Call recording management (safe streaming, download, tenant permission scoping).
   - Item 7: FreeSWITCH `mod_xml_cdr` HTTP POST ingestion, CDR normalization, and database storage.
   - Item 11: Real-time Reports & Analytics (Disposition summary, CDR analytics, WebSocket live prepend, active channel telemetry).
3. **Voicemail System, Custom Prompts & Notifications (Items 4, 9, 12)**:
   - Item 4: Voicemail system with custom audio greeting, beep tone, message recording, database persistence, and dedicated Voicemail tab in ReportsView.
   - Item 9: System Prompts / Custom Audio (upload, preview, associate with IVR/extensions).
   - Item 12: Voicemail email notification delivery (hierarchical SMTP resolution, MIME attachment).
4. **Multi-Homed FreeSWITCH Gateways**:
   - `external-crossconnect` on port 5090 (`ISHAN_FL`, direct IP, no NAT).
   - `external` on port 5080 (`ISHAN_ITS`, GCP public NAT).
   - `internal` on ports 5060 / 5061 (TLS).
5. **Documentation Handover**:
   - Update `API_USER_MANUAL.md` with complete documentation for all new endpoints (Voicemail, Audio Prompts, Disposition Reports, WebSockets).
   - Update `docs/ARCHITECTURE.md` to reflect the current multi-tenant architecture, call flows, and WebSocket topology.

---

## 2. Hardening & Verification Strategy

- **Master Regression Suite**: Execute all 47+ backend tests in `pbx_api` container ensuring 100% pass rate.
- **Frontend Quality Gate**: Execute `scripts/lint-ds.js` to ensure 0 Design System violations and run `tsc -b && vite build` with 0 type errors.
- **FreeSWITCH Profile Health**: Verify all Sofia profiles (`internal`, `external`, `external-crossconnect`) and loaded modules (`mod_xml_cdr`, `mod_callcenter`, `mod_conference`).
- **Comprehensive Handover Documentation**: Generate clear operational and API manuals for the client.
