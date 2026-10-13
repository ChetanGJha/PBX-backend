import os
import socket
import logging
from typing import Dict, Any, List, Optional
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
from src.core.config import settings

logger = logging.getLogger("pbx.services.gateway_sync")


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
    os.makedirs(fallback, exist_ok=True)
    return fallback


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
    """
    host = settings.FREESWITCH_ESL_HOST
    port = settings.FREESWITCH_ESL_PORT
    password = settings.FREESWITCH_ESL_PASSWORD
    
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
