import logging
from xml.etree.ElementTree import Element, SubElement, tostring
from typing import Dict, Optional, Any
from src.core.database import execute_query, execute_query_one
from src.core.config import settings

logger = logging.getLogger("pbx.xml_curl.directory")

NOT_FOUND_XML = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<document type="freeswitch/xml">
  <section name="result">
    <result status="not found"/>
  </section>
</document>"""


async def handle_directory_request(form_data: Dict[str, Any]) -> str:
    """
    Handles section=directory XML-CURL requests from FreeSWITCH.
    Dynamically generates SIP authentication directory XML based on PostgreSQL tenant & extension data.
    """
    domain_name = form_data.get("domain") or form_data.get("key_value") or form_data.get("SIP-Auth-Realm")
    user_id = form_data.get("user") or form_data.get("SIP-Auth-User")

    # Fix Zoiper "double-@" bug: when outbound proxy is set separately, Zoiper sends
    # user="1001@pbx.aikyamlabs.local" and domain="127.0.0.1". Strip the embedded domain
    # from user_id so auth lookup works correctly.
    if user_id and "@" in user_id:
        embedded_user, embedded_domain = user_id.split("@", 1)
        logger.info(f"mod_xml_curl Directory: stripping embedded domain from user: '{user_id}' -> '{embedded_user}' (domain hint: '{embedded_domain}')")
        # If domain_name is an IP and embedded_domain is a real FQDN, prefer the FQDN
        if domain_name and (domain_name == "127.0.0.1" or domain_name == "localhost") and "." in embedded_domain and not embedded_domain.replace(".", "").isdigit():
            domain_name = embedded_domain
        user_id = embedded_user

    logger.info(f"mod_xml_curl Directory request: domain='{domain_name}', user='{user_id}'")

    if not domain_name:
        return NOT_FOUND_XML

    # 1. Lookup Tenant by sip_domain or domain
    tenant = await execute_query_one(
        "SELECT id, name, domain, sip_domain FROM tenants WHERE (sip_domain = :d OR domain = :d) AND enabled = true AND deleted_at IS NULL",
        {"d": domain_name}
    )

    # Fallback to primary production tenant (pbx.aikyamlabs.local) for IP or localhost registrations
    if not tenant:
        tenant = await execute_query_one(
            "SELECT id, name, domain, sip_domain FROM tenants WHERE (sip_domain = 'pbx.aikyamlabs.local' OR domain = 'pbx.aikyamlabs.local') AND enabled = true AND deleted_at IS NULL"
        )

    # Fallback to first active tenant if still not found
    if not tenant:
        tenant = await execute_query_one(
            "SELECT id, name, domain, sip_domain FROM tenants WHERE enabled = true AND deleted_at IS NULL ORDER BY created_at ASC LIMIT 1"
        )

    if not tenant:
        logger.warning(f"mod_xml_curl Directory: Tenant not found for domain '{domain_name}'")
        return NOT_FOUND_XML

    tenant_id = str(tenant["id"])
    sip_domain = tenant["sip_domain"]

    # 2. Fetch extension(s)
    if user_id:
        extensions = await execute_query(
            """
            SELECT extension_number, display_name, email, sip_password, voicemail_pin,
                   caller_id_name, caller_id_number, outbound_caller_id, enabled
            FROM extensions
            WHERE tenant_id = :tenant_id AND extension_number = :user_id AND enabled = true AND deleted_at IS NULL
            """,
            {"tenant_id": tenant_id, "user_id": user_id}
        )
    else:
        # Fetch all active extensions for this domain
        extensions = await execute_query(
            """
            SELECT extension_number, display_name, email, sip_password, voicemail_pin,
                   caller_id_name, caller_id_number, outbound_caller_id, enabled
            FROM extensions
            WHERE tenant_id = :tenant_id AND enabled = true AND deleted_at IS NULL
            """,
            {"tenant_id": tenant_id}
        )

    if not extensions:
        logger.warning(f"mod_xml_curl Directory: No active extension found for user='{user_id}' in tenant '{tenant_id}'")
        return NOT_FOUND_XML

    # 3. Construct XML Document
    doc = Element("document", type="freeswitch/xml")
    section = SubElement(doc, "section", name="directory")

    # Support both the queried domain (which may be an IP or FQDN) and the tenant's canonical sip_domain
    domains_to_create = [domain_name]
    if sip_domain and sip_domain != domain_name:
        domains_to_create.append(sip_domain)

    # Standard Sofia dial-string allows FreeSWITCH to locate the live Sofia registration contact
    sofia_dial_string = "{presence_id=${dialed_user}@${dialed_domain}}${sofia_contact(${dialed_user}@${dialed_domain})}"

    for d_name in domains_to_create:
        domain_elem = SubElement(section, "domain", name=d_name)

        # Domain level params
        d_params = SubElement(domain_elem, "params")
        SubElement(d_params, "param", name="dial-string", value=sofia_dial_string)

        groups = SubElement(domain_elem, "groups")
        group = SubElement(groups, "group", name="default")
        users = SubElement(group, "users")

        for ext in extensions:
            ext_num = ext["extension_number"]
            sip_pwd = ext["sip_password"]
            vm_pin = ext.get("voicemail_pin") or "1234"
            cid_name = ext.get("caller_id_name") or ext.get("display_name") or ext_num
            cid_num = ext.get("caller_id_number") or ext_num
            outbound_cli = ext.get("outbound_caller_id") or cid_num
            email_str = ext.get("email") or ""

            u_elem = SubElement(users, "user", id=ext_num)

            # User Parameters (Password & Auth)
            u_params = SubElement(u_elem, "params")
            SubElement(u_params, "param", name="password", value=sip_pwd)
            SubElement(u_params, "param", name="vm-password", value=vm_pin)

            # User Dialplan Variables
            u_vars = SubElement(u_elem, "variables")
            # Enforce strict multi-tenant dialplan context isolation
            SubElement(u_vars, "variable", name="user_context", value=f"tenant-{tenant_id}")
            SubElement(u_vars, "variable", name="effective_caller_id_name", value=cid_name)
            SubElement(u_vars, "variable", name="effective_caller_id_number", value=cid_num)
            SubElement(u_vars, "variable", name="outbound_caller_id_name", value=cid_name)
            SubElement(u_vars, "variable", name="outbound_caller_id_number", value=outbound_cli)
            SubElement(u_vars, "variable", name="accountcode", value=tenant_id)
            SubElement(u_vars, "variable", name="tenant_id", value=tenant_id)
            SubElement(u_vars, "variable", name="user_email", value=email_str)

    xml_header = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    return xml_header + tostring(doc, encoding="utf-8").decode("utf-8")
