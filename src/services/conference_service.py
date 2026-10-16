import logging
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from src.services.gateway_sync import execute_esl_command

logger = logging.getLogger("pbx.conference_service")


def get_conference_live_status(conf_name: str) -> Dict[str, Any]:
    """
    Queries FreeSWITCH ESL for live status of the given conference room.
    Returns:
      {
        "name": conf_name,
        "active": bool,
        "member_count": int,
        "has_moderator": bool,
        "members": [
          {
            "id": member_id,
            "uuid": channel_uuid,
            "caller_id_name": name,
            "caller_id_number": number,
            "join_time": join_time_or_duration,
            "is_moderator": bool,
            "can_speak": bool,
            "can_hear": bool
          }
        ]
      }
    """
    res: Dict[str, Any] = {
        "name": conf_name,
        "active": False,
        "member_count": 0,
        "has_moderator": False,
        "members": []
    }

    if not conf_name:
        return res

    raw_output = execute_esl_command(f"conference {conf_name} xml_list")
    if not raw_output or "not found" in raw_output.lower():
        return res

    try:
        # Locate valid XML payload in ESL response
        xml_start = raw_output.find("<?xml")
        if xml_start == -1:
            xml_start = raw_output.find("<conferences")
        if xml_start == -1:
            xml_start = raw_output.find("<conference")

        if xml_start != -1:
            raw_xml = raw_output[xml_start:].strip()
        else:
            raw_xml = raw_output.strip()

        root = ET.fromstring(raw_xml)
        conf_elem = root.find("conference") if root.tag != "conference" else root

        if conf_elem is not None:
            members_elem = conf_elem.find("members")
            if members_elem is not None:
                for m in members_elem.findall("member"):
                    mid = m.findtext("id") or m.attrib.get("id") or ""
                    uuid = m.findtext("uuid") or ""
                    cid_name = m.findtext("caller_id_name") or ""
                    cid_num = m.findtext("caller_id_number") or ""
                    join_time = m.findtext("join_time") or ""

                    flags_elem = m.find("flags")
                    is_mod = False
                    can_speak = True
                    can_hear = True

                    if flags_elem is not None:
                        flag_mod = flags_elem.findtext("is_moderator")
                        if flag_mod and flag_mod.strip().lower() in ("true", "1", "yes"):
                            is_mod = True
                        elif "moderator" in (flags_elem.text or "").lower():
                            is_mod = True

                        if flags_elem.findtext("can_speak") == "false":
                            can_speak = False
                        if flags_elem.findtext("can_hear") == "false":
                            can_hear = False

                    # Check member tag attributes or text
                    if "moderator" in m.attrib.get("flags", "").lower():
                        is_mod = True

                    if is_mod:
                        res["has_moderator"] = True

                    res["members"].append({
                        "id": mid,
                        "uuid": uuid,
                        "caller_id_name": cid_name,
                        "caller_id_number": cid_num,
                        "join_time": join_time,
                        "is_moderator": is_mod,
                        "can_speak": can_speak,
                        "can_hear": can_hear
                    })

            res["member_count"] = len(res["members"])
            res["active"] = res["member_count"] > 0
    except Exception as e:
        logger.warning(f"Failed to parse FreeSWITCH ESL xml_list for conference '{conf_name}': {e}")

    return res


def terminate_conference(conf_name: str) -> bool:
    """
    Terminates the active conference room in FreeSWITCH, hanging up all callers.
    """
    if not conf_name:
        return False
    logger.info(f"Terminating conference room '{conf_name}' via FreeSWITCH ESL")
    out = execute_esl_command(f"conference {conf_name} hup all")
    if not out or "not found" in out.lower():
        # Fallback to kick all
        execute_esl_command(f"conference {conf_name} kick all")
    return True


def kick_conference_member(conf_name: str, member_id: str) -> bool:
    """
    Hangs up and drops a specific member from an active conference.
    """
    if not conf_name or not member_id:
        return False
    logger.info(f"Dropping member '{member_id}' from conference room '{conf_name}'")
    execute_esl_command(f"conference {conf_name} hup {member_id}")
    return True
