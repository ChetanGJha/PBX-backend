import logging
from src.core.database import execute_query, execute_query_one

logger = logging.getLogger("pbx.xml_curl.dialplan")

async def handle_dialplan_request(form_dict: dict) -> str:
    destination_number = form_dict.get("Caller-Destination-Number", "")
    context = form_dict.get("Caller-Context", "default")
    domain_name = form_dict.get("domain", form_dict.get("variable_domain_name", ""))

    logger.info(f"Generating dynamic dialplan XML for destination='{destination_number}', context='{context}', domain='{domain_name}'")

    tenant = await execute_query_one(
        "SELECT id, domain FROM tenants WHERE (domain = :d OR sip_domain = :d) AND deleted_at IS NULL AND enabled = true",
        {"d": domain_name}
    )

    tenant_id = tenant["id"] if tenant else None

    did_route = await execute_query_one(
        """SELECT destination_type, destination, did_number
           FROM call_routes
           WHERE route_type = 'inbound_did' AND enabled = true
             AND (did_number = :num OR regex_pattern = :num OR :num LIKE '%' || did_number)
             AND (tenant_id IS NULL OR tenant_id = CAST(:t_id AS uuid))
           ORDER BY priority ASC LIMIT 1""",
        {"num": destination_number, "t_id": tenant_id}
    )

    if did_route:
        dest_type = did_route["destination_type"]
        dest = did_route["destination"]

        xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<document type="freeswitch/xml">
  <section name="dialplan" description="Dynamic Inbound DID Route">
    <context name="{context}">
      <extension name="inbound_did_{destination_number}">
        <condition field="destination_number" expression="^{destination_number}$">
          <action application="set" data="domain_name={domain_name}"/>
"""
        if dest_type == "extension":
            xml += f'          <action application="bridge" data="user/{dest}@{domain_name}"/>\n'
        elif dest_type == "queue":
            xml += f'          <action application="callcenter" data="{dest}@{domain_name}"/>\n'
        elif dest_type == "voicemail":
            xml += f'          <action application="voicemail" data="default {domain_name} {dest}"/>\n'
        else:
            xml += f'          <action application="bridge" data="user/{dest}@{domain_name}"/>\n'

        xml += """        </condition>
      </extension>
    </context>
  </section>
</document>"""
        return xml

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<document type="freeswitch/xml">
  <section name="dialplan" description="Dynamic Tenant Extension Dialplan">
    <context name="{context}">
      <extension name="local_extension">
        <condition field="destination_number" expression="^(\\d{{3,5}})$">
          <action application="set" data="dialed_extension=$1"/>
          <action application="bridge" data="user/$1@{domain_name}"/>
        </condition>
      </extension>
    </context>
  </section>
</document>"""
