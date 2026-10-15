import os
import re
import socket
import logging
import asyncio
from typing import Dict, Any, List, Optional
from src.core.config import settings
from src.core.database import execute_query

logger = logging.getLogger("pbx.services.gateway_sync")


def get_sip_profiles_base_dir() -> str:
    """
    Locates the FreeSWITCH sip_profiles directory across Docker container or local host.
    """
    candidates = [
        "/etc/freeswitch/sip_profiles",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "../../config/freeswitch/sip_profiles")),
        os.path.abspath("config/freeswitch/sip_profiles"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    
    # Default fallback
    fallback = candidates[0]
    os.makedirs(fallback, exist_ok=True)
    return fallback


def sanitize_filename(name: str) -> str:
    """
    Sanitize gateway name for safe XML filenames.
    """
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", name).strip("_")


def determine_gateway_profile(gw: Dict[str, Any]) -> str:
    """
    Determines whether the gateway belongs to:
    - 'external-crossconnect': for Fixed Line series SBC (e.g. ISHAN_FL, 10.50.185.x, Cross Connect, No NAT)
    - 'external': for ITS SBC (e.g. ISHAN_ITS, GCP Public NAT 8.234.117.15)
    """
    explicit_profile = (gw.get("profile") or "").strip().lower()
    if explicit_profile in ("external-crossconnect", "crossconnect", "fixedline"):
        return "external-crossconnect"
    
    name = (gw.get("name") or "").strip().lower()
    proxy = (gw.get("proxy") or gw.get("host") or "").strip()

    # If trunk name contains '_fl' or 'fixedline' or proxy matches crossconnect
    if "_fl" in name or "fixedline" in name or "crossconnect" in name or proxy.startswith("10.50.185.") or proxy.startswith("10.50."):
        return "external-crossconnect"
        
    return "external"


def render_gateway_xml(gw: Dict[str, Any]) -> str:
    """
    Generates FreeSWITCH Sofia Gateway XML definition.
    """
    gw_name = gw.get("name") or "unnamed_gateway"
    proxy = gw.get("proxy") or gw.get("host") or "127.0.0.1"
    port = gw.get("port")
    if port and port != 5060 and ":" not in str(proxy):
        proxy = f"{proxy}:{port}"

    realm = gw.get("realm") or gw.get("proxy") or gw.get("host") or proxy
    username = gw.get("username") or gw_name
    password = gw.get("password") or "nopassword"
    register = "true" if gw.get("register") and gw.get("username") and gw.get("username") != "IP Auth" else "false"
    from_user = gw.get("username") or gw_name
    if from_user == "IP Auth":
        from_user = gw_name
    from_domain = gw.get("from_domain") or realm or proxy
    caller_id_in_from = "true" if gw.get("caller_id_in_from", True) else "false"
    codecs = gw.get("codecs") or "PCMU,PCMA,G722"

    xml_lines = [
        '<include>',
        f'  <gateway name="{gw_name}">',
        f'    <param name="proxy" value="{proxy}"/>',
        f'    <param name="realm" value="{realm}"/>',
        f'    <param name="username" value="{username}"/>',
        f'    <param name="password" value="{password}"/>',
        f'    <param name="register" value="{register}"/>',
        f'    <param name="from-user" value="{from_user}"/>',
        f'    <param name="from-domain" value="{from_domain}"/>',
        f'    <param name="caller-id-in-from" value="{caller_id_in_from}"/>',
        f'    <param name="codec-prefs" value="{codecs}"/>',
        '    <param name="retry-seconds" value="30"/>',
        '    <param name="ping" value="25"/>',
        '    <param name="ping-max" value="3"/>',
        '    <param name="ping-min" value="1"/>',
        '  </gateway>',
        '</include>',
        ''
    ]
    return "\n".join(xml_lines)


def execute_esl_command(command: str) -> Optional[str]:
    """
    Executes a command on FreeSWITCH via Event Socket (ESL).
    Tries configured host followed by container and host loopback candidates.
    """
    port = settings.FREESWITCH_ESL_PORT
    password = settings.FREESWITCH_ESL_PASSWORD
    hosts_to_try = [settings.FREESWITCH_ESL_HOST]
    for h in ["freeswitch", "127.0.0.1", "localhost", "pbx_freeswitch"]:
        if h and h not in hosts_to_try:
            hosts_to_try.append(h)

    for host in hosts_to_try:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect((host, port))
            
            # Read banner
            s.recv(1024)
            
            # Authenticate
            s.sendall(f"auth {password}\n\n".encode())
            auth_resp = s.recv(1024).decode(errors="ignore")
            if "+OK accepted" not in auth_resp:
                logger.error(f"FreeSWITCH ESL authentication failed on {host}:{port}")
                s.close()
                continue

            # Execute API command
            s.sendall(f"api {command}\n\n".encode())
            data = ""
            while True:
                chunk = s.recv(4096).decode(errors="ignore")
                if not chunk:
                    break
                data += chunk
                if len(chunk) < 4096:
                    break

            s.close()
            logger.info(f"FreeSWITCH ESL command '{command}' succeeded on {host}:{port}")
            return data
        except Exception:
            continue

    logger.warning(f"Failed to execute ESL command '{command}' across hosts {hosts_to_try}:{port}")
    return None


async def sync_gateways_to_freeswitch() -> Dict[str, Any]:
    """
    Synchronizes all Sofia gateways (from both 'gateways' and 'sip_trunks' tables)
    into FreeSWITCH XML files, removes obsolete XMLs, and rescans Sofia profiles.
    """
    base_dir = get_sip_profiles_base_dir()
    ext_dir = os.path.join(base_dir, "external")
    cross_dir = os.path.join(base_dir, "external-crossconnect")

    os.makedirs(ext_dir, exist_ok=True)
    os.makedirs(cross_dir, exist_ok=True)

    active_items: Dict[str, Dict[str, Any]] = {}

    # 1. Fetch all active gateways from 'gateways' table
    try:
        gw_query = """
            SELECT id, name, proxy, username, password, realm, from_domain, codecs,
                   tenant_id, register, caller_id_in_from, enabled, profile
            FROM gateways
            WHERE deleted_at IS NULL AND enabled = true
            ORDER BY name ASC
        """
        gw_rows = await execute_query(gw_query)
        for r in gw_rows:
            d = dict(r)
            active_items[d["name"]] = d
    except Exception as e:
        logger.warning(f"Error querying gateways table: {e}")

    # 2. Fetch all active trunks from 'sip_trunks' table (e.g. ISHAN_FL, ISHAN_ITS)
    try:
        trunk_query = """
            SELECT id, name, host as proxy, username, password, realm, port, priority,
                   tenant_id, register, enabled
            FROM sip_trunks
            WHERE deleted_at IS NULL AND enabled = true
            ORDER BY priority ASC, name ASC
        """
        trunk_rows = await execute_query(trunk_query)
        for r in trunk_rows:
            d = dict(r)
            name = d["name"]
            if name not in active_items:
                # Add default codecs and caller_id_in_from for sip_trunks
                d["codecs"] = "PCMU,PCMA,G722"
                d["caller_id_in_from"] = True
                active_items[name] = d
    except Exception as e:
        logger.warning(f"Error querying sip_trunks table: {e}")

    synced_files = {"external": set(), "external-crossconnect": set()}
    written_count = 0

    # 3. Write gateway XML files
    for name, item in active_items.items():
        profile_type = determine_gateway_profile(item)
        gw_filename = f"{sanitize_filename(name)}.xml"
        target_dir = cross_dir if profile_type == "external-crossconnect" else ext_dir
        target_path = os.path.join(target_dir, gw_filename)

        xml_content = render_gateway_xml(item)
        try:
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(xml_content)
            synced_files[profile_type].add(gw_filename)
            written_count += 1
            logger.info(f"Wrote gateway XML: {target_path} for profile '{profile_type}' (name='{name}')")
        except Exception as e:
            logger.error(f"Failed writing gateway XML file {target_path}: {e}")

    # 4. Clean up stale gateway XML files
    deleted_count = 0
    for profile_type, p_dir in [("external", ext_dir), ("external-crossconnect", cross_dir)]:
        try:
            for f in os.listdir(p_dir):
                if f.endswith(".xml") and f not in synced_files[profile_type]:
                    dead_path = os.path.join(p_dir, f)
                    try:
                        os.remove(dead_path)
                        deleted_count += 1
                        gw_raw_name = f[:-4]
                        execute_esl_command(f"sofia profile {profile_type} killgw {gw_raw_name}")
                        logger.info(f"Removed stale gateway XML: {dead_path}")
                    except Exception as err:
                        logger.warning(f"Error removing file {dead_path}: {err}")
        except Exception as e:
            logger.warning(f"Error checking stale XML files in {p_dir}: {e}")

    # 5. Trigger FreeSWITCH XML reload and Sofia rescans
    execute_esl_command("reloadxml")
    execute_esl_command("sofia profile external rescan")
    execute_esl_command("sofia profile external-crossconnect rescan")

    # 6. Fetch sofia status for verification
    status_output = execute_esl_command("sofia status") or ""

    return {
        "success": True,
        "total_active_gateways": len(active_items),
        "written_files": written_count,
        "deleted_files": deleted_count,
        "external_gateways": list(synced_files["external"]),
        "crossconnect_gateways": list(synced_files["external-crossconnect"]),
        "sofia_status_summary": status_output.strip()
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = asyncio.run(sync_gateways_to_freeswitch())
    print("\n--- GATEWAY SYNC RESULT ---")
    print("Success:", res["success"])
    print("Total active:", res["total_active_gateways"])
    print("External Gateways:", res["external_gateways"])
    print("CrossConnect Gateways:", res["crossconnect_gateways"])
    print("\nSofia Status Output:")
    print(res["sofia_status_summary"])
