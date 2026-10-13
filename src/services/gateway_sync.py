import os
<<<<<<< HEAD
import socket
import logging
from typing import Dict, Any, List, Optional
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
from src.core.config import settings
=======
import re
import socket
import logging
import asyncio
from typing import Dict, Any, List, Optional
from src.core.config import settings
from src.core.database import execute_query
>>>>>>> 642b5a2a01afc3a19796c4f49f1737db7fe86dc0

logger = logging.getLogger("pbx.services.gateway_sync")


<<<<<<< HEAD
def get_external_profiles_dir() -> str:
    """
    Locates or creates the external sip_profiles directory.
    Checks container path /etc/freeswitch/sip_profiles/external first,
    then host relative paths.
    """
    candidates = [
        "/etc/freeswitch/sip_profiles/external",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "../../config/freeswitch/sip_profiles/external")),
        "./config/freeswitch/sip_profiles/external"
    ]
    for path in candidates:
        parent = os.path.dirname(path)
        if os.path.exists(parent):
            os.makedirs(path, exist_ok=True)
            return path
            
    # Fallback default
    fallback = "./config/freeswitch/sip_profiles/external"
=======
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
>>>>>>> 642b5a2a01afc3a19796c4f49f1737db7fe86dc0
    os.makedirs(fallback, exist_ok=True)
    return fallback


<<<<<<< HEAD
def generate_gateway_xml(gw: Dict[str, Any]) -> str:
    """
    Generates FreeSWITCH Sofia gateway XML format for inclusion in sip_profiles/external.
    """
    include = Element("include")
    gw_elem = SubElement(include, "gateway", name=gw["name"])
    
    # Required Proxy
    SubElement(gw_elem, "param", name="proxy", value=str(gw.get("proxy", "")))
    
    # Realm / Domain
    if gw.get("realm"):
        SubElement(gw_elem, "param", name="realm", value=str(gw["realm"]))
    elif gw.get("proxy"):
        SubElement(gw_elem, "param", name="realm", value=str(gw["proxy"]).split(":")[0])
        
    if gw.get("from_domain"):
        SubElement(gw_elem, "param", name="from-domain", value=str(gw["from_domain"]))
        
    # Username and Password (SIP Auth)
    if gw.get("username"):
        SubElement(gw_elem, "param", name="username", value=str(gw["username"]))
        SubElement(gw_elem, "param", name="from-user", value=str(gw["username"]))
    if gw.get("password"):
        SubElement(gw_elem, "param", name="password", value=str(gw["password"]))
        
    # Registration parameter
    reg_val = "true" if gw.get("register", True) and gw.get("username") else "false"
    SubElement(gw_elem, "param", name="register", value=reg_val)
    
    # Caller ID in From Header
    if gw.get("caller_id_in_from"):
        SubElement(gw_elem, "param", name="caller-id-in-from", value="true")
    else:
        SubElement(gw_elem, "param", name="caller-id-in-from", value="false")
        
    # Codec preferences
    codecs = gw.get("codecs") or "PCMU,PCMA,G722"
    SubElement(gw_elem, "param", name="codec-prefs", value=codecs)
    
    # Standard health & NAT parameters
    SubElement(gw_elem, "param", name="retry-seconds", value="30")
    SubElement(gw_elem, "param", name="expire-seconds", value="600")
    SubElement(gw_elem, "param", name="ping", value="25")
    
    xml_raw = tostring(include, encoding="utf-8")
    return minidom.parseString(xml_raw).toprettyxml(indent="  ")


def generate_sofia_conf_xml(gateways: List[Dict[str, Any]]) -> str:
    """
    Generates dynamic sofia.conf XML with all active gateways inside the external profile.
    """
    doc = Element("document", type="freeswitch/xml")
    sec = SubElement(doc, "section", name="configuration", description="sofia Endpoint")
    conf = SubElement(sec, "configuration", name="sofia.conf", description="sofia Endpoint")
    
    # Global Settings
    glob = SubElement(conf, "global_settings")
    SubElement(glob, "param", name="log-level", value="0")
    SubElement(glob, "param", name="auto-restart", value="true")
    SubElement(glob, "param", name="debug-presence", value="0")
    
    profiles = SubElement(conf, "profiles")
    
    # Profile: external
    ext_prof = SubElement(profiles, "profile", name="external")
    ext_settings = SubElement(ext_prof, "settings")
    SubElement(ext_settings, "param", name="debug", value="0")
    SubElement(ext_settings, "param", name="sip-port", value="5080")
    SubElement(ext_settings, "param", name="dialplan", value="XML")
    SubElement(ext_settings, "param", name="context", value="public")
    SubElement(ext_settings, "param", name="rfc2833-pt", value="101")
    SubElement(ext_settings, "param", name="sip-ip", value="$${local_ip_v4}")
    SubElement(ext_settings, "param", name="rtp-ip", value="$${local_ip_v4}")
    SubElement(ext_settings, "param", name="ext-rtp-ip", value="auto-nat")
    SubElement(ext_settings, "param", name="ext-sip-ip", value="auto-nat")
    SubElement(ext_settings, "param", name="user-agent-string", value="MultiTenantPBX-External")
    SubElement(ext_settings, "param", name="inbound-codec-prefs", value="OPUS,PCMU,PCMA")
    SubElement(ext_settings, "param", name="outbound-codec-prefs", value="OPUS,PCMU,PCMA")
    SubElement(ext_settings, "param", name="inbound-late-negotiation", value="true")
    SubElement(ext_settings, "param", name="auth-calls", value="false")
    SubElement(ext_settings, "param", name="rtp-timeout-sec", value="300")
    
    # Gateways in external profile
    gw_container = SubElement(ext_prof, "gateways")
    for gw in gateways:
        gw_elem = SubElement(gw_container, "gateway", name=gw["name"])
        SubElement(gw_elem, "param", name="proxy", value=str(gw.get("proxy", "")))
        
        if gw.get("realm"):
            SubElement(gw_elem, "param", name="realm", value=str(gw["realm"]))
        elif gw.get("proxy"):
            SubElement(gw_elem, "param", name="realm", value=str(gw["proxy"]).split(":")[0])
            
        if gw.get("from_domain"):
            SubElement(gw_elem, "param", name="from-domain", value=str(gw["from_domain"]))
            
        if gw.get("username"):
            SubElement(gw_elem, "param", name="username", value=str(gw["username"]))
            SubElement(gw_elem, "param", name="from-user", value=str(gw["username"]))
        if gw.get("password"):
            SubElement(gw_elem, "param", name="password", value=str(gw["password"]))
            
        reg_val = "true" if gw.get("register", True) and gw.get("username") else "false"
        SubElement(gw_elem, "param", name="register", value=reg_val)
        
        if gw.get("caller_id_in_from"):
            SubElement(gw_elem, "param", name="caller-id-in-from", value="true")
        else:
            SubElement(gw_elem, "param", name="caller-id-in-from", value="false")
            
        codecs = gw.get("codecs") or "PCMU,PCMA,G722"
        SubElement(gw_elem, "param", name="codec-prefs", value=codecs)
        SubElement(gw_elem, "param", name="retry-seconds", value="30")
        SubElement(gw_elem, "param", name="expire-seconds", value="600")
        SubElement(gw_elem, "param", name="ping", value="25")
        
    # Profile: internal
    int_prof = SubElement(profiles, "profile", name="internal")
    int_aliases = SubElement(int_prof, "aliases")
    SubElement(int_aliases, "alias", name="pbx.aikyamlabs.local")
    SubElement(int_aliases, "alias", name="127.0.0.1")
    SubElement(int_aliases, "alias", name="172.16.0.179")
    
    int_settings = SubElement(int_prof, "settings")
    SubElement(int_settings, "param", name="debug", value="0")
    SubElement(int_settings, "param", name="sip-port", value="5060")
    SubElement(int_settings, "param", name="dialplan", value="XML")
    SubElement(int_settings, "param", name="context", value="public")
    SubElement(int_settings, "param", name="rfc2833-pt", value="101")
    SubElement(int_settings, "param", name="sip-ip", value="$${local_ip_v4}")
    SubElement(int_settings, "param", name="rtp-ip", value="$${local_ip_v4}")
    SubElement(int_settings, "param", name="ext-rtp-ip", value="$${external_rtp_ip}")
    SubElement(int_settings, "param", name="ext-sip-ip", value="$${external_sip_ip}")
    SubElement(int_settings, "param", name="user-agent-string", value="MultiTenantPBX-FreeSWITCH")
    SubElement(int_settings, "param", name="inbound-codec-prefs", value="OPUS,PCMU,PCMA")
    SubElement(int_settings, "param", name="outbound-codec-prefs", value="OPUS,PCMU,PCMA")
    SubElement(int_settings, "param", name="inbound-late-negotiation", value="true")
    SubElement(int_settings, "param", name="inbound-codec-negotiation", value="generous")
    SubElement(int_settings, "param", name="auth-calls", value="true")
    SubElement(int_settings, "param", name="accept-blind-reg", value="false")
    SubElement(int_settings, "param", name="accept-blind-auth", value="false")
    SubElement(int_settings, "param", name="suppress-cng", value="true")
    SubElement(int_settings, "param", name="challenge-realm", value="auto_to")
    SubElement(int_settings, "param", name="NDLB-force-rport", value="true")
    SubElement(int_settings, "param", name="NDLB-broken-auth-hash", value="true")
    SubElement(int_settings, "param", name="NDLB-received-in-nat-reg-contact", value="true")
    SubElement(int_settings, "param", name="NDLB-sendrecv-in-nat", value="true")
    SubElement(int_settings, "param", name="aggressive-nat-detection", value="true")
    SubElement(int_settings, "param", name="nat-options-ping", value="true")
    SubElement(int_settings, "param", name="sip-force-contact", value="NDLB-connectile-dysfunction")
    SubElement(int_settings, "param", name="ws-binding", value=":5066")
    SubElement(int_settings, "param", name="wss-binding", value=":7443")
    SubElement(int_settings, "param", name="tls", value="true")
    SubElement(int_settings, "param", name="tls-cert-dir", value="/etc/freeswitch/tls")
    SubElement(int_settings, "param", name="insecure-configured", value="true")
    SubElement(int_settings, "param", name="rtp-timeout-sec", value="300")
    SubElement(int_settings, "param", name="rtp-hold-timeout-sec", value="1800")
    
    xml_header = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    return xml_header + tostring(doc, encoding="utf-8").decode("utf-8")


def sync_gateway_file(gw: Dict[str, Any]) -> Optional[str]:
    """
    Writes the gateway XML file into the external profiles directory.
    """
    try:
        ext_dir = get_external_profiles_dir()
        file_path = os.path.join(ext_dir, f"{gw['name']}.xml")
        xml_content = generate_gateway_xml(gw)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(xml_content)
        logger.info(f"Successfully synced gateway XML to {file_path}")
        return file_path
    except Exception as exc:
        logger.error(f"Failed to write gateway file: {exc}", exc_info=True)
        return None


def remove_gateway_file(gw_name: str) -> bool:
    """
    Removes the gateway XML file from the external profiles directory.
    """
    try:
        ext_dir = get_external_profiles_dir()
        file_path = os.path.join(ext_dir, f"{gw_name}.xml")
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Removed gateway XML {file_path}")
            return True
        return False
    except Exception as exc:
        logger.error(f"Failed to remove gateway file: {exc}", exc_info=True)
        return False


def reload_freeswitch_gateways() -> bool:
    """
    Notifies FreeSWITCH via Event Socket (ESL) to rescan the external profile.
=======
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
>>>>>>> 642b5a2a01afc3a19796c4f49f1737db7fe86dc0
    """
    host = settings.FREESWITCH_ESL_HOST
    port = settings.FREESWITCH_ESL_PORT
    password = settings.FREESWITCH_ESL_PASSWORD
<<<<<<< HEAD
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect((host, port))
        s.recv(1024)
        s.sendall(f"auth {password}\n\n".encode())
        auth_resp = s.recv(1024).decode("utf-8", errors="ignore")
        if "+OK accepted" not in auth_resp:
            logger.warning(f"ESL auth failed: {auth_resp.strip()}")
            s.close()
            return False
            
        s.sendall(b"api reloadxml\n\n")
        s.recv(1024)
        s.sendall(b"api sofia profile external rescan\n\n")
        rescan_resp = s.recv(1024).decode("utf-8", errors="ignore")
        s.close()
        logger.info(f"FreeSWITCH external profile rescan triggered: {rescan_resp.strip()}")
        return True
    except Exception as exc:
        logger.warning(f"Unable to reload FreeSWITCH gateways via ESL ({host}:{port}): {exc}")
        return False
=======

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3.0)
        s.connect((host, port))
        
        # Read banner
        s.recv(1024)
        
        # Authenticate
        s.sendall(f"auth {password}\n\n".encode())
        auth_resp = s.recv(1024).decode(errors="ignore")
        if "+OK accepted" not in auth_resp:
            logger.error(f"FreeSWITCH ESL authentication failed on {host}:{port}")
            s.close()
            return None

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
        return data
    except Exception as e:
        logger.warning(f"Failed to execute ESL command '{command}' on {host}:{port}: {e}")
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
>>>>>>> 642b5a2a01afc3a19796c4f49f1737db7fe86dc0
