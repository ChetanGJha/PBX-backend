import os
import logging
from xml.etree.ElementTree import Element, SubElement, tostring
from typing import Dict, Any
from src.core.database import execute_query_one, execute_query

logger = logging.getLogger("pbx.xml_curl.dialplan")

NOT_FOUND_XML = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<document type="freeswitch/xml">
  <section name="result">
    <result status="not found"/>
  </section>
</document>"""

# Complete list of failure dispositions to continue to voicemail (excluding NORMAL_CLEARING)
VOICEMAIL_CONTINUE_ON_FAIL = (
    "NORMAL_TEMPORARY_FAILURE,USER_BUSY,NO_ANSWER,TIMEOUT,ALLOTTED_TIMEOUT,"
    "NO_ROUTE_DESTINATION,USER_NOT_REGISTERED,CALL_REJECTED,NO_USER_RESPONSE,"
    "PROGRESS_TIMEOUT,RECOVERY_ON_TIMER_EXPIRE,SERVICE_NOT_IMPLEMENTED,"
    "SUBSCRIBER_ABSENT,UNALLOCATED_NUMBER,INCOMPATIBLE_DESTINATION"
)


async def handle_dialplan_request(form_data: Dict[str, Any]) -> str:
    """
    Handles section=dialplan XML-CURL requests from FreeSWITCH.
    Dynamically generates dialplan XML for:
    1. Internal Extension-to-Extension calling with recording & voicemail fallback
    2. Outbound calling via assigned gateway / SIP trunk (with carrier simulation fallback)
    3. Voicemail with audio prompt, tone beep, recording, and webhook notification
    4. Incoming call routing with Test DIDs to Queue, IVR, and Hunt Group
    5. Automatic CDR generation and Call Recording tagging
    """
    context = form_data.get("Caller-Context", "public")
    dest_number = form_data.get("Caller-Destination-Number", "").strip()
    caller_id_number = form_data.get("Caller-Caller-ID-Number", "").strip()
    caller_id_name = form_data.get("Caller-Caller-ID-Name", "").strip()
    domain_name = form_data.get("domain") or form_data.get("variable_domain_name") or form_data.get("variable_sip_req_host") or "pbx.aikyamlabs.local"
    tenant_id = form_data.get("variable_tenant_id") or form_data.get("variable_accountcode")

    logger.info(
        f"mod_xml_curl Dialplan request: context='{context}', dest='{dest_number}', "
        f"caller='{caller_id_number}', domain='{domain_name}', tenant='{tenant_id}'"
    )

    if not dest_number:
        return NOT_FOUND_XML

    # Resolve Tenant ID if not already passed in channel variables
    if not tenant_id and context.startswith("tenant-"):
        tenant_id = context.replace("tenant-", "")

    if not tenant_id and domain_name:
        t_row = await execute_query_one(
            "SELECT id FROM tenants WHERE (sip_domain = :d OR domain = :d) AND enabled = true AND deleted_at IS NULL",
            {"d": domain_name}
        )
        if t_row:
            tenant_id = str(t_row["id"])

    if not tenant_id:
        t_row = await execute_query_one(
            "SELECT id FROM tenants WHERE enabled = true AND deleted_at IS NULL ORDER BY created_at ASC LIMIT 1"
        )
        if t_row:
            tenant_id = str(t_row["id"])

    # Build XML Document
    doc = Element("document", type="freeswitch/xml")
    section = SubElement(doc, "section", name="dialplan", description="Dynamic Multi-Tenant Dialplan")
    context_elem = SubElement(section, "context", name=context)

    # -------------------------------------------------------------------------
    # CALL BLOCK (BLACKLIST) CHECK
    # -------------------------------------------------------------------------
    if tenant_id and caller_id_number:
        try:
            blocked = await execute_query_one(
                "SELECT action FROM call_block WHERE tenant_id = CAST(:tid AS uuid) AND number = :num AND enabled = true",
                {"tid": tenant_id, "num": caller_id_number}
            )
            if blocked:
                act = blocked.get("action", "reject")
                logger.warning(f"Blocked call from blacklisted caller '{caller_id_number}' (action={act})")
                ext_elem = SubElement(context_elem, "extension", name="blocked_call")
                cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=".*")
                if act == "busy":
                    SubElement(cond_elem, "action", application="respond", data="486 Busy Here")
                elif act == "voicemail":
                    add_voicemail_block(cond_elem, "1001", domain_name, tenant_id)
                else:
                    SubElement(cond_elem, "action", application="respond", data="603 Declined")
                return format_xml(doc)
        except Exception as e:
            logger.error(f"Error checking call_block: {e}")

    # =========================================================================
    # SCENARIO 1: SPECIAL FEATURE CODES
    # =========================================================================
    # Direct Pickup: **<ext>
    if dest_number.startswith("**") and len(dest_number) > 2:
        target = dest_number[2:]
        ext_elem = SubElement(context_elem, "extension", name=f"direct_pickup_{target}")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=".*")
        SubElement(cond_elem, "action", application="set", data=f"tenant_id={tenant_id}")
        SubElement(cond_elem, "action", application="intercept", data=f"user/{target}@{domain_name}")
        return format_xml(doc)

    # Group Pickup: *8
    if dest_number == "*8":
        ext_elem = SubElement(context_elem, "extension", name="group_pickup")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=r"^\*8$")
        SubElement(cond_elem, "action", application="set", data=f"tenant_id={tenant_id}")
        SubElement(cond_elem, "action", application="intercept", data=f"all@{domain_name}")
        return format_xml(doc)

    # Eavesdrop / Spy: *33<ext>
    if dest_number.startswith("*33") and len(dest_number) > 3:
        target = dest_number[3:]
        ext_elem = SubElement(context_elem, "extension", name=f"eavesdrop_{target}")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=".*")
        SubElement(cond_elem, "action", application="set", data=f"tenant_id={tenant_id}")
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="eavesdrop", data=f"user/{target}@{domain_name}")
        return format_xml(doc)

    # Whisper: *34<ext>
    if dest_number.startswith("*34") and len(dest_number) > 3:
        target = dest_number[3:]
        ext_elem = SubElement(context_elem, "extension", name=f"whisper_{target}")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=".*")
        SubElement(cond_elem, "action", application="set", data=f"tenant_id={tenant_id}")
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="set", data="eavesdrop_whisper_aleg=true")
        SubElement(cond_elem, "action", application="eavesdrop", data=f"user/{target}@{domain_name}")
        return format_xml(doc)

    # Intercom / Auto-answer page: *80<ext>
    if dest_number.startswith("*80") and len(dest_number) > 3:
        target = dest_number[3:]
        ext_elem = SubElement(context_elem, "extension", name=f"intercom_{target}")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=".*")
        SubElement(cond_elem, "action", application="set", data=f"tenant_id={tenant_id}")
        SubElement(cond_elem, "action", application="export", data="sip_h_Call-Info=<sip:x>;answer-after=0")
        SubElement(cond_elem, "action", application="export", data="sip_auto_answer=true")
        SubElement(cond_elem, "action", application="export", data="sip_h_Alert-Info=Ring Answer")
        SubElement(cond_elem, "action", application="bridge", data=f"user/{target}@{domain_name}")
        return format_xml(doc)

    # Valet Call Parking (*5900 park, *5901-*5999 or 5901-5999 retrieve)
    if dest_number == "*5900":
        ext_elem = SubElement(context_elem, "extension", name="valet_park")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=r"^\*5900$")
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="sleep", data="500")
        SubElement(cond_elem, "action", application="valet_park", data=f"parklot_{tenant_id} auto in 5901 5999")
        return format_xml(doc)

    if (dest_number.startswith("*59") or (dest_number.startswith("59") and dest_number.isdigit())) and len(dest_number.replace("*", "")) == 4:
        slot = dest_number.replace("*", "")
        ext_elem = SubElement(context_elem, "extension", name=f"valet_unpark_{slot}")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=".*")
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="valet_park", data=f"parklot_{tenant_id} out {slot}")
        return format_xml(doc)

    # Do Not Disturb (*78 enable, *79 disable)
    if dest_number == "*78":
        if tenant_id and caller_id_number:
            await execute_query(
                '''INSERT INTO dnd_settings (extension_id, enabled, updated_at)
                   SELECT id, true, NOW() FROM extensions WHERE tenant_id = CAST(:tid AS uuid) AND extension_number = :num
                   ON CONFLICT (extension_id) DO UPDATE SET enabled = true, updated_at = NOW()''',
                {"tid": tenant_id, "num": caller_id_number}
            )
        ext_elem = SubElement(context_elem, "extension", name="dnd_on")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=r"^\*78$")
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="sleep", data="500")
        SubElement(cond_elem, "action", application="playback", data="tone_stream://%(250,50,440);%(250,50,440)")
        return format_xml(doc)

    if dest_number == "*79":
        if tenant_id and caller_id_number:
            await execute_query(
                '''INSERT INTO dnd_settings (extension_id, enabled, updated_at)
                   SELECT id, false, NOW() FROM extensions WHERE tenant_id = CAST(:tid AS uuid) AND extension_number = :num
                   ON CONFLICT (extension_id) DO UPDATE SET enabled = false, updated_at = NOW()''',
                {"tid": tenant_id, "num": caller_id_number}
            )
        ext_elem = SubElement(context_elem, "extension", name="dnd_off")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=r"^\*79$")
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="sleep", data="500")
        SubElement(cond_elem, "action", application="playback", data="tone_stream://%(500,50,440)")
        return format_xml(doc)

    # Call Forwarding (*72<dest> enable, *73 disable)
    if dest_number.startswith("*72") and len(dest_number) > 3:
        fwd_target = dest_number[3:]
        if tenant_id and caller_id_number:
            await execute_query(
                '''INSERT INTO call_forwarding (extension_id, forward_always_enabled, forward_always_destination, updated_at)
                   SELECT id, true, :target, NOW() FROM extensions WHERE tenant_id = CAST(:tid AS uuid) AND extension_number = :num
                   ON CONFLICT (extension_id) DO UPDATE SET forward_always_enabled = true, forward_always_destination = :target, updated_at = NOW()''',
                {"tid": tenant_id, "num": caller_id_number, "target": fwd_target}
            )
        ext_elem = SubElement(context_elem, "extension", name="cf_on")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=".*")
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="sleep", data="500")
        SubElement(cond_elem, "action", application="playback", data="tone_stream://%(250,50,440);%(250,50,440)")
        return format_xml(doc)

    if dest_number == "*73":
        if tenant_id and caller_id_number:
            await execute_query(
                '''INSERT INTO call_forwarding (extension_id, forward_always_enabled, updated_at)
                   SELECT id, false, NOW() FROM extensions WHERE tenant_id = CAST(:tid AS uuid) AND extension_number = :num
                   ON CONFLICT (extension_id) DO UPDATE SET forward_always_enabled = false, updated_at = NOW()''',
                {"tid": tenant_id, "num": caller_id_number}
            )
        ext_elem = SubElement(context_elem, "extension", name="cf_off")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=r"^\*73$")
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="sleep", data="500")
        SubElement(cond_elem, "action", application="playback", data="tone_stream://%(500,50,440)")
        return format_xml(doc)

    # Direct Voicemail Deposit (*99 + Extension, e.g. *991001)
    if dest_number.startswith("*99") and len(dest_number) > 3:
        target_vm_ext = dest_number[3:]
        ext_elem = SubElement(context_elem, "extension", name=f"vm_deposit_{target_vm_ext}")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=f"^\\*99{target_vm_ext}$")
        add_voicemail_block(cond_elem, target_vm_ext, domain_name, tenant_id)
        return format_xml(doc)

    # Voicemail Star-codes (*97 self, *98 any)
    if dest_number == "*97":
        ext_elem = SubElement(context_elem, "extension", name="voicemail_self")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=r"^\*97$")
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="sleep", data="500")
        SubElement(cond_elem, "action", application="voicemail", data=f"check default {domain_name} {caller_id_number}")
        return format_xml(doc)

    if dest_number == "*98":
        ext_elem = SubElement(context_elem, "extension", name="voicemail_any")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=r"^\*98$")
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="sleep", data="500")
        SubElement(cond_elem, "action", application="voicemail", data=f"check default {domain_name}")
        return format_xml(doc)

    # Conference Rooms (3000 to 3999)
    if dest_number.isdigit() and 3000 <= int(dest_number) <= 3999:
        conf_room = None
        if tenant_id:
            conf_room = await execute_query_one(
                "SELECT id, name, pin, moderator_pin, record_conference, enabled FROM conferences WHERE extension_number = :dest AND (tenant_id = CAST(:tid AS uuid) OR tenant_id IS NULL) AND enabled = true",
                {"dest": dest_number, "tid": tenant_id}
            )
        conf_name = f"conf_{tenant_id}_{dest_number}"
        ext_elem = SubElement(context_elem, "extension", name=f"conf_{dest_number}")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=".*")
        SubElement(cond_elem, "action", application="set", data=f"tenant_id={tenant_id}")
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="sleep", data="500")
        if conf_room and conf_room.get("record_conference"):
            SubElement(cond_elem, "action", application="record_session", data=f"/var/lib/freeswitch/recordings/{tenant_id}/conf_{dest_number}_${{uuid}}.wav")
        SubElement(cond_elem, "action", application="conference", data=f"{conf_name}@default")
        return format_xml(doc)
    if dest_number in ("*96", "9196"):
        ext_elem = SubElement(context_elem, "extension", name="echo_test")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=r"^(\*96|9196)$")
        SubElement(cond_elem, "action", application="set", data=f"tenant_id={tenant_id}")
        SubElement(cond_elem, "action", application="set", data="direction=internal")
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="sleep", data="500")
        SubElement(cond_elem, "action", application="echo")
        return format_xml(doc)

    if dest_number in ("*95", "9195"):
        ext_elem = SubElement(context_elem, "extension", name="moh_test")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=r"^(\*95|9195)$")
        SubElement(cond_elem, "action", application="set", data=f"tenant_id={tenant_id}")
        SubElement(cond_elem, "action", application="set", data="direction=internal")
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="playback", data="local_stream://moh")
        return format_xml(doc)

    # =========================================================================
    # SCENARIO 4: INCOMING CALLS WITH TEST DIDs / QUEUE / IVR / HUNT GROUP
    # =========================================================================
    # Test DID 1: Route to Call Queue (TESTQ / 7777 / 5551 / +15551001)
    if dest_number in ("5551", "+15551001", "7777"):
        ext_elem = SubElement(context_elem, "extension", name="route_queue")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=".*")
        SubElement(cond_elem, "action", application="set", data=f"tenant_id={tenant_id}")
        SubElement(cond_elem, "action", application="set", data="direction=inbound")
        SubElement(cond_elem, "action", application="set", data="did=5551")
        SubElement(cond_elem, "action", application="set", data="hangup_after_bridge=true")
        SubElement(cond_elem, "action", application="export", data="hangup_after_bridge=true")
        SubElement(cond_elem, "action", application="set", data=f"continue_on_fail={VOICEMAIL_CONTINUE_ON_FAIL}")
        SubElement(cond_elem, "action", application="set", data=f"recording_file=/var/lib/freeswitch/recordings/{tenant_id}/${{uuid}}.wav")
        SubElement(cond_elem, "action", application="record_session", data=f"/var/lib/freeswitch/recordings/{tenant_id}/${{uuid}}.wav")
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="set", data="ringback=%(2000,4000,440.0,480.0)")
        SubElement(cond_elem, "action", application="set", data="instant_ringback=true")
        # Ring available queue agents simultaneously with 20s timeout
        SubElement(cond_elem, "action", application="bridge", data=f"[leg_timeout=20]user/1001@{domain_name},user/1002@{domain_name}")
        # Voicemail fallback if no agent answers
        add_voicemail_block(cond_elem, "1001", domain_name, tenant_id)
        return format_xml(doc)

    # Check for IVR Menu configured in database or default test DIDs
    ivr_menu = None
    if tenant_id:
        ivr_menu = await execute_query_one(
            """
            SELECT id, name, extension_number, timeout, max_retries, greeting_audio
            FROM ivr_menus
            WHERE tenant_id = CAST(:tid AS uuid)
              AND extension_number = :dest AND enabled = true AND deleted_at IS NULL
            ORDER BY updated_at DESC LIMIT 1
            """,
            {"tid": tenant_id, "dest": dest_number}
        )

    # Test DID 2 & IVR (6001 / 5552 / +15551002 or matched ivr_menus)
    if dest_number in ("5552", "+15551002", "6001") or ivr_menu:
        menu_id = str(ivr_menu["id"]) if ivr_menu else "46765586-c906-497f-83ba-0d39776cfbe4"
        ext_elem = SubElement(context_elem, "extension", name="route_ivr")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=".*")
        SubElement(cond_elem, "action", application="set", data=f"tenant_id={tenant_id}")
        SubElement(cond_elem, "action", application="set", data="direction=inbound")
        SubElement(cond_elem, "action", application="set", data=f"did={dest_number}")
        SubElement(cond_elem, "action", application="set", data=f"ivr_menu_id={menu_id}")
        SubElement(cond_elem, "action", application="set", data="hangup_after_bridge=true")
        SubElement(cond_elem, "action", application="export", data="hangup_after_bridge=true")
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="sleep", data="500")
        SubElement(cond_elem, "action", application="set", data=f"recording_file=/var/lib/freeswitch/recordings/{tenant_id}/${{uuid}}.wav")
        SubElement(cond_elem, "action", application="record_session", data=f"/var/lib/freeswitch/recordings/{tenant_id}/${{uuid}}.wav")

        menu_timeout = 5000
        if ivr_menu and ivr_menu.get("timeout"):
            menu_timeout = int(ivr_menu["timeout"]) * 1000

        prompt_file = "/var/lib/freeswitch/recordings/prompts/ivr_welcome.wav"
        if ivr_menu and ivr_menu.get("greeting_audio"):
            db_audio = ivr_menu["greeting_audio"]
            if os.path.exists(f"/var/lib/freeswitch/recordings/prompts/{db_audio}"):
                prompt_file = f"/var/lib/freeswitch/recordings/prompts/{db_audio}"

        # Play IVR Welcome Greeting and capture DTMF (1-4 digits)
        SubElement(
            cond_elem,
            "action",
            application="play_and_get_digits",
            data=f"1 4 3 {menu_timeout} # {prompt_file} /var/lib/freeswitch/recordings/prompts/beep.wav dtmf_result \\d+"
        )
        # Transfer caller to ivr_choice_${dtmf_result}
        SubElement(cond_elem, "action", application="transfer", data="ivr_choice_${dtmf_result} XML " + context)
        # Fallback if no choice entered / timeout: route to 1001
        SubElement(cond_elem, "action", application="transfer", data="1001 XML " + context)
        return format_xml(doc)

    # Route IVR Captured Selection (ivr_choice_1, ivr_choice_2, ivr_choice_1002, etc.)
    if dest_number.startswith("ivr_choice_"):
        key = dest_number.replace("ivr_choice_", "").strip()
        ivr_menu_id = form_data.get("variable_ivr_menu_id") or "46765586-c906-497f-83ba-0d39776cfbe4"
        logger.info(f"Processing IVR Choice DTMF key='{key}', menu_id='{ivr_menu_id}' for context='{context}', tenant='{tenant_id}'")

        ext_elem = SubElement(context_elem, "extension", name=f"ivr_exec_{key or 'default'}")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=".*")
        SubElement(cond_elem, "action", application="set", data=f"tenant_id={tenant_id}")
        SubElement(cond_elem, "action", application="set", data="hangup_after_bridge=true")
        SubElement(cond_elem, "action", application="export", data="hangup_after_bridge=true")

        # 1. Direct Extension Dialing (2 to 4 digits, e.g. 1001, 1002, 9001)
        if len(key) >= 2 and key.isdigit():
            logger.info(f"IVR: Direct extension dial to {key}")
            SubElement(cond_elem, "action", application="transfer", data=f"{key} XML {context}")
            return format_xml(doc)

        # 2. Check IVR Nodes in Database for key
        ivr_node = None
        if key:
            if ivr_menu_id:
                ivr_node = await execute_query_one(
                    """
                    SELECT action_type, action_target
                    FROM ivr_nodes
                    WHERE ivr_menu_id = CAST(:mid AS uuid) AND dtmf_key = :key
                    LIMIT 1
                    """,
                    {"mid": ivr_menu_id, "key": key}
                )
            if not ivr_node and tenant_id:
                ivr_node = await execute_query_one(
                    """
                    SELECT n.action_type, n.action_target
                    FROM ivr_nodes n
                    JOIN ivr_menus m ON n.ivr_menu_id = m.id
                    WHERE m.tenant_id = CAST(:tid AS uuid) AND n.dtmf_key = :key
                    ORDER BY m.updated_at DESC LIMIT 1
                    """,
                    {"tid": tenant_id, "key": key}
                )

        if ivr_node:
            act_type = ivr_node.get("action_type")
            act_target = ivr_node.get("action_target")
            logger.info(f"IVR Node matched: key={key} -> {act_type}:{act_target}")

            if act_type == "extension":
                SubElement(cond_elem, "action", application="transfer", data=f"{act_target} XML {context}")
                return format_xml(doc)
            elif act_type == "queue":
                SubElement(cond_elem, "action", application="transfer", data=f"{act_target or '7777'} XML {context}")
                return format_xml(doc)
            elif act_type == "hunt_group":
                SubElement(cond_elem, "action", application="transfer", data=f"{act_target or '8888'} XML {context}")
                return format_xml(doc)
            elif act_type == "voicemail":
                add_voicemail_block(cond_elem, act_target or "1001", domain_name, tenant_id)
                return format_xml(doc)

        # 3. Standard built-in default menu map
        # 1 -> 1001 (Sales), 2 -> 1002 (Support), 3 -> Queue 7777, 4 -> Hunt Group 8888, 9 -> Voicemail 1001
        if key == "1":
            SubElement(cond_elem, "action", application="transfer", data=f"1001 XML {context}")
        elif key == "2":
            SubElement(cond_elem, "action", application="transfer", data=f"1002 XML {context}")
        elif key == "3":
            SubElement(cond_elem, "action", application="transfer", data=f"7777 XML {context}")
        elif key == "4":
            SubElement(cond_elem, "action", application="transfer", data=f"8888 XML {context}")
        elif key == "9":
            add_voicemail_block(cond_elem, "1001", domain_name, tenant_id)
        else:
            # Fallback for timeout or unrecognized key
            logger.info(f"IVR: Fallback transfer to default 1001")
            SubElement(cond_elem, "action", application="transfer", data=f"1001 XML {context}")
        return format_xml(doc)

    # Test DID 3: Route to Hunt Group (TESTGROUP / 8888 / 5553 / +15551003)
    if dest_number in ("5553", "+15551003", "8888"):
        ext_elem = SubElement(context_elem, "extension", name="route_hunt_group")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=".*")
        SubElement(cond_elem, "action", application="set", data=f"tenant_id={tenant_id}")
        SubElement(cond_elem, "action", application="set", data="direction=inbound")
        SubElement(cond_elem, "action", application="set", data="did=5553")
        SubElement(cond_elem, "action", application="set", data="hangup_after_bridge=true")
        SubElement(cond_elem, "action", application="export", data="hangup_after_bridge=true")
        SubElement(cond_elem, "action", application="set", data=f"continue_on_fail={VOICEMAIL_CONTINUE_ON_FAIL}")
        SubElement(cond_elem, "action", application="set", data=f"recording_file=/var/lib/freeswitch/recordings/{tenant_id}/${{uuid}}.wav")
        SubElement(cond_elem, "action", application="record_session", data=f"/var/lib/freeswitch/recordings/{tenant_id}/${{uuid}}.wav")
        SubElement(cond_elem, "action", application="set", data="ringback=%(2000,4000,440.0,480.0)")
        SubElement(cond_elem, "action", application="instant_ringback=true")
        # Ring hunt group member extensions (simultaneous strategy) with 25s timeout
        SubElement(cond_elem, "action", application="bridge", data=f"[leg_timeout=25]user/1001@{domain_name},user/1002@{domain_name}")
        add_voicemail_block(cond_elem, "1001", domain_name, tenant_id)
        return format_xml(doc)

    # Check Database DIDs & Call Routes
    if tenant_id:
        did_route = await execute_query_one(
            """
            SELECT destination_type, destination_target, destination
            FROM dids
            WHERE (did_number = :dest OR did_number = '+' || :dest) AND enabled = true AND deleted_at IS NULL
            LIMIT 1
            """,
            {"dest": dest_number}
        )
        if did_route:
            dest_type = did_route.get("destination_type") or "extension"
            target = did_route.get("destination_target") or did_route.get("destination") or "1001"
            ext_elem = SubElement(context_elem, "extension", name=f"did_{dest_number}")
            cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=".*")
            SubElement(cond_elem, "action", application="set", data=f"tenant_id={tenant_id}")
            SubElement(cond_elem, "action", application="set", data="direction=inbound")
            SubElement(cond_elem, "action", application="set", data=f"did={dest_number}")
            SubElement(cond_elem, "action", application="set", data="hangup_after_bridge=true")
            SubElement(cond_elem, "action", application="export", data="hangup_after_bridge=true")
            SubElement(cond_elem, "action", application="set", data=f"continue_on_fail={VOICEMAIL_CONTINUE_ON_FAIL}")
            SubElement(cond_elem, "action", application="set", data=f"recording_file=/var/lib/freeswitch/recordings/{tenant_id}/${{uuid}}.wav")
            SubElement(cond_elem, "action", application="record_session", data=f"/var/lib/freeswitch/recordings/{tenant_id}/${{uuid}}.wav")
            SubElement(cond_elem, "action", application="set", data="ringback=%(2000,4000,440.0,480.0)")
            SubElement(cond_elem, "action", application="set", data="instant_ringback=true")

            if dest_type in ("business_hours", "time_condition"):
                await evaluate_and_route_business_hours(cond_elem, target, tenant_id, domain_name, context)
            elif dest_type == "extension":
                SubElement(cond_elem, "action", application="bridge", data=f"[leg_timeout=20]user/{target}@{domain_name}")
                add_voicemail_block(cond_elem, target, domain_name, tenant_id)
            elif dest_type == "queue":
                SubElement(cond_elem, "action", application="bridge", data=f"[leg_timeout=20]user/1001@{domain_name},user/1002@{domain_name}")
            elif dest_type == "hunt_group":
                SubElement(cond_elem, "action", application="bridge", data=f"[leg_timeout=25]user/1001@{domain_name},user/1002@{domain_name}")
            elif dest_type == "ivr":
                SubElement(cond_elem, "action", application="transfer", data=f"{target or '6001'} XML {context}")
            return format_xml(doc)

    # =========================================================================
    # SCENARIO 1 & 3: INTERNAL EXTENSION-TO-EXTENSION CALL WITH VOICEMAIL
    # =========================================================================
    target_ext = None
    if tenant_id:
        target_ext = await execute_query_one(
            """
            SELECT e.id, e.extension_number, e.display_name, e.caller_id_name, e.caller_id_number,
                   e.email, e.enabled, e.no_answer_timeout, t.sip_domain
            FROM extensions e
            JOIN tenants t ON e.tenant_id = t.id
            WHERE e.tenant_id = :tenant_id AND e.extension_number = :dest
              AND e.enabled = true AND e.deleted_at IS NULL
            """,
            {"tenant_id": tenant_id, "dest": dest_number}
        )

    if target_ext:
        ext_num = target_ext["extension_number"]
        callee_domain = target_ext.get("sip_domain") or domain_name

        # Configurable no-answer timeout (per extension or default 20s)
        timeout = target_ext.get("no_answer_timeout")
        if not timeout or not isinstance(timeout, int) or timeout <= 0:
            timeout = 20

        ext_elem = SubElement(context_elem, "extension", name=f"internal_ext_{ext_num}")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=f"^{ext_num}$")

        # Set standard call & CDR variables
        SubElement(cond_elem, "action", application="set", data=f"tenant_id={tenant_id}")
        SubElement(cond_elem, "action", application="set", data="direction=internal")

        # Disconnect calling party immediately when either party hangs up
        SubElement(cond_elem, "action", application="set", data="hangup_after_bridge=true")
        SubElement(cond_elem, "action", application="export", data="hangup_after_bridge=true")

        # Only continue down the dialplan if the call was NOT answered or failed
        SubElement(
            cond_elem,
            "action",
            application="set",
            data=f"continue_on_fail={VOICEMAIL_CONTINUE_ON_FAIL}"
        )

        # Ringing timeout variables
        SubElement(cond_elem, "action", application="set", data=f"call_timeout={timeout}")
        SubElement(cond_elem, "action", application="set", data=f"originate_timeout={timeout}")
        SubElement(cond_elem, "action", application="set", data=f"leg_timeout={timeout}")
        SubElement(cond_elem, "action", application="set", data=f"progress_timeout={timeout}")
        SubElement(cond_elem, "action", application="set", data="ringback=%(2000,4000,440.0,480.0)")
        SubElement(cond_elem, "action", application="set", data="instant_ringback=true")
        SubElement(cond_elem, "action", application="export", data="sip_contact_user=${destination_number}")

        # Voice Call Recording
        rec_path = f"/var/lib/freeswitch/recordings/{tenant_id}/${{uuid}}.wav"
        SubElement(cond_elem, "action", application="set", data=f"recording_file={rec_path}")
        SubElement(cond_elem, "action", application="record_session", data=rec_path)

        # Check Do Not Disturb (DND)
        dnd_record = await execute_query_one(
            "SELECT enabled FROM dnd_settings WHERE extension_id = CAST(:ext_id AS uuid)",
            {"ext_id": str(target_ext["id"])}
        )
        if dnd_record and dnd_record.get("enabled"):
            logger.info(f"Extension {ext_num} has DND enabled, redirecting to voicemail")
            add_voicemail_block(cond_elem, ext_num, callee_domain, tenant_id)
            return format_xml(doc)

        # Check Call Forwarding
        cf_record = await execute_query_one(
            """
            SELECT forward_always_enabled, forward_always_destination,
                   forward_busy_enabled, forward_busy_destination,
                   forward_no_answer_enabled, forward_no_answer_destination
            FROM call_forwarding
            WHERE extension_id = CAST(:ext_id AS uuid)
            """,
            {"ext_id": str(target_ext["id"])}
        )

        if cf_record and cf_record.get("forward_always_enabled") and cf_record.get("forward_always_destination"):
            cf_dest = cf_record["forward_always_destination"]
            logger.info(f"Extension {ext_num} has unconditional forward to {cf_dest}")
            SubElement(cond_elem, "action", application="bridge", data=f"[leg_timeout={timeout},originate_timeout={timeout}]user/{cf_dest}@{callee_domain}")
        else:
            # Standard bridge to callee with multi-domain fallback (|) to support both pbx.aikyamlabs.local and 127.0.0.1 registrations
            bridge_targets = [f"user/{ext_num}@{callee_domain}"]
            if callee_domain != "pbx.aikyamlabs.local":
                bridge_targets.append(f"user/{ext_num}@pbx.aikyamlabs.local")
            if callee_domain != "127.0.0.1":
                bridge_targets.append(f"user/{ext_num}@127.0.0.1")
            bridge_data = f"[leg_timeout={timeout},originate_timeout={timeout}]" + "|".join(bridge_targets)
            SubElement(cond_elem, "action", application="bridge", data=bridge_data)

        # Voicemail fallback if callee does not answer or is unavailable
        custom_greeting = None
        vm_box_row = await execute_query_one(
            "SELECT greeting_path FROM voicemail_boxes WHERE extension_id = CAST(:ext_id AS uuid)",
            {"ext_id": str(target_ext["id"])}
        )
        if vm_box_row and vm_box_row.get("greeting_path"):
            gp = vm_box_row["greeting_path"]
            for cand in [
                f"/var/lib/freeswitch/recordings/audio/{gp}",
                f"/var/lib/freeswitch/recordings/{gp}",
                f"/app/media/audio/{gp}"
            ]:
                if os.path.exists(cand):
                    custom_greeting = cand
                    break

        add_voicemail_block(cond_elem, ext_num, callee_domain, tenant_id, greeting_file=custom_greeting)
        return format_xml(doc)

    # =========================================================================
    # SCENARIO 2: OUTBOUND CALLS VIA ASSIGNED GATEWAY / SIP TRUNK
    # =========================================================================
    # Matches numbers starting with 9 (e.g. 918005551234), 10+ digits, or E.164 (+)
    is_outbound = (
        dest_number.startswith("9") and len(dest_number) >= 5
    ) or (
        dest_number.isdigit() and len(dest_number) >= 10
    ) or (
        dest_number.startswith("+")
    )

    if is_outbound:
        # Strip dialing prefix 9 if present
        dialed_digits = dest_number[1:] if dest_number.startswith("9") else dest_number

        # Check for assigned trunk in database
        trunk = await execute_query_one(
            """
            SELECT name, host, port FROM sip_trunks
            WHERE (tenant_id = CAST(:tid AS uuid) OR tenant_id IS NULL) AND enabled = true AND deleted_at IS NULL
            ORDER BY priority ASC LIMIT 1
            """,
            {"tid": tenant_id}
        )
        trunk_name = trunk["name"] if trunk else "tata"

        ext_elem = SubElement(context_elem, "extension", name=f"outbound_{dest_number}")
        cond_elem = SubElement(ext_elem, "condition", field="destination_number", expression=".*")

        SubElement(cond_elem, "action", application="set", data=f"tenant_id={tenant_id}")
        SubElement(cond_elem, "action", application="set", data="direction=outbound")
        SubElement(cond_elem, "action", application="set", data="hangup_after_bridge=true")
        SubElement(cond_elem, "action", application="export", data="hangup_after_bridge=true")
        SubElement(cond_elem, "action", application="set", data="continue_on_fail=NORMAL_TEMPORARY_FAILURE,USER_BUSY,NO_ANSWER,TIMEOUT,NO_ROUTE_DESTINATION")

        # Record outbound call session
        rec_path = f"/var/lib/freeswitch/recordings/{tenant_id}/${{uuid}}.wav"
        SubElement(cond_elem, "action", application="set", data=f"recording_file={rec_path}")
        SubElement(cond_elem, "action", application="record_session", data=rec_path)

        # Set Caller ID from extension or tenant
        SubElement(cond_elem, "action", application="set", data="effective_caller_id_name=${outbound_caller_id_name}")
        SubElement(cond_elem, "action", application="set", data="effective_caller_id_number=${outbound_caller_id_number}")

        # Attempt bridge through gateway
        SubElement(cond_elem, "action", application="bridge", data=f"sofia/gateway/{trunk_name}/{dialed_digits}")

        # Interactive Outbound Carrier Simulation Fallback (for testing without live PSTN provider)
        SubElement(cond_elem, "action", application="answer")
        SubElement(cond_elem, "action", application="sleep", data="500")
        SubElement(cond_elem, "action", application="playback", data="/var/lib/freeswitch/recordings/prompts/outbound_connected.wav")
        SubElement(cond_elem, "action", application="sleep", data="500")
        SubElement(cond_elem, "action", application="echo")

        return format_xml(doc)

    logger.warning(f"No dialplan route matched for dest='{dest_number}' in context='{context}'")
    return NOT_FOUND_XML



async def evaluate_and_route_business_hours(cond_elem: Element, target: str, tenant_id: str, domain_name: str, context: str):
    """
    Evaluates business hours schedule, checks holidays and weekly open/close window,
    and appends FreeSWITCH routing actions to cond_elem.
    """
    import zoneinfo
    from datetime import datetime, date

    bh_row = None
    try:
        bh_row = await execute_query_one(
            """
            SELECT id, name, timezone, schedule,
                   open_destination_type, open_destination_target,
                   closed_destination_type, closed_destination_target,
                   holiday_destination_type, holiday_destination_target
            FROM business_hours
            WHERE (id::text = :target OR tenant_id = :tenant_id)
            ORDER BY (id::text = :target) DESC
            LIMIT 1
            """,
            {"target": str(target or ""), "tenant_id": tenant_id}
        )
    except Exception as e:
        logger.error(f"Error querying business_hours: {e}")

    if not bh_row:
        SubElement(cond_elem, "action", application="bridge", data=f"[leg_timeout=20]user/1001" + "@" + f"{domain_name}")
        add_voicemail_block(cond_elem, "1001", domain_name, tenant_id)
        return

    tz_str = bh_row.get("timezone") or "UTC"
    try:
        tz = zoneinfo.ZoneInfo(tz_str)
    except Exception:
        tz = zoneinfo.ZoneInfo("UTC")

    now_tz = datetime.now(tz)
    today_date = now_tz.date()
    curr_time_str = now_tz.strftime("%H:%M")
    day_name = now_tz.strftime("%A").lower()

    holidays = []
    try:
        holidays = await execute_query(
            "SELECT holiday_date FROM holidays WHERE business_hours_id = :bh_id",
            {"bh_id": bh_row["id"]}
        )
    except Exception as e:
        logger.error(f"Error querying holidays: {e}")

    is_holiday = any(h.get("holiday_date") == today_date for h in holidays)

    if is_holiday:
        status = "HOLIDAY"
        dest_type = bh_row.get("holiday_destination_type") or bh_row.get("closed_destination_type") or "voicemail"
        dest_target = bh_row.get("holiday_destination_target") or bh_row.get("closed_destination_target") or "1001"
    else:
        sched = bh_row.get("schedule") or {}
        if isinstance(sched, str):
            import json
            try:
                sched = json.loads(sched)
            except Exception:
                sched = {}
        day_conf = sched.get(day_name) or {}
        is_open = False
        if day_conf.get("enabled"):
            o = day_conf.get("open", "00:00")
            c = day_conf.get("close", "23:59")
            if o <= curr_time_str < c:
                is_open = True

        if is_open:
            status = "OPEN"
            dest_type = bh_row.get("open_destination_type") or "extension"
            dest_target = bh_row.get("open_destination_target") or "1001"
        else:
            status = "CLOSED"
            dest_type = bh_row.get("closed_destination_type") or "voicemail"
            dest_target = bh_row.get("closed_destination_target") or "1001"

    SubElement(cond_elem, "action", application="set", data=f"business_hours_status={status}")
    SubElement(cond_elem, "action", application="set", data=f"business_hours_name={bh_row.get('name')}")

    if dest_type == "extension":
        SubElement(cond_elem, "action", application="bridge", data=f"[leg_timeout=20]user/{dest_target}" + "@" + f"{domain_name}")
        add_voicemail_block(cond_elem, dest_target, domain_name, tenant_id)
    elif dest_type == "ivr":
        SubElement(cond_elem, "action", application="transfer", data=f"{dest_target or '6001'} XML {context}")
    elif dest_type in ("hunt_group", "queue"):
        SubElement(cond_elem, "action", application="bridge", data=f"[leg_timeout=25]user/1001" + "@" + f"{domain_name},user/1002" + "@" + f"{domain_name}")
    elif dest_type == "conference":
        SubElement(cond_elem, "action", application="conference", data=f"{dest_target}" + "@" + f"{domain_name}")
    elif dest_type == "voicemail":
        add_voicemail_block(cond_elem, dest_target, domain_name, tenant_id)
    else:
        SubElement(cond_elem, "action", application="bridge", data=f"[leg_timeout=20]user/{dest_target}" + "@" + f"{domain_name}")


def add_voicemail_block(cond_elem: Element, ext_num: str, domain: str, tenant_id: str, greeting_file: str = None):
    """
    Appends full Voicemail execution actions:
    1. Answers the channel
    2. Sets channel variables for CDR fallback logging
    3. Plays custom or default 'User not available' greeting
    4. Plays 1000Hz beep tone
    5. Records caller's audio message to disk
    6. Calls API webhook via query params & JSON to guarantee recording capture
    7. Hangs up cleanly
    """
    vm_file = f"/var/lib/freeswitch/recordings/voicemail/{ext_num}_${{uuid}}.wav"

    SubElement(cond_elem, "action", application="answer")
    SubElement(cond_elem, "action", application="sleep", data="500")
    SubElement(cond_elem, "action", application="set", data=f"voicemail_target={ext_num}")
    SubElement(cond_elem, "action", application="set", data=f"voicemail_file={vm_file}")

    # Play Custom Voicemail Greeting if configured and exists, else default prompt
    if greeting_file and os.path.exists(greeting_file):
        SubElement(cond_elem, "action", application="playback", data=greeting_file)
    else:
        SubElement(cond_elem, "action", application="playback", data="/var/lib/freeswitch/recordings/prompts/voicemail_greeting.wav")

    # Play Beep Tone
    SubElement(cond_elem, "action", application="playback", data="/var/lib/freeswitch/recordings/prompts/beep.wav")
    # Record message: max 120s, threshold 200, silence terminate 4s
    SubElement(cond_elem, "action", application="record", data=f"{vm_file} 120 200 4")

    # Trigger webhook with call details (using URL query parameters for 100% reliability in mod_curl)
    curl_url = f"http://api:8000/freeswitch/voicemail?extension_number={ext_num}&caller_id_number=${{caller_id_number}}&caller_id_name=${{caller_id_name}}&file_path={vm_file}&duration=15&tenant_id={tenant_id}"
    SubElement(
        cond_elem,
        "action",
        application="curl",
        data=f"{curl_url} post"
    )
    SubElement(cond_elem, "action", application="hangup")


def format_xml(doc: Element) -> str:
    xml_header = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    return xml_header + tostring(doc, encoding="utf-8").decode("utf-8")
