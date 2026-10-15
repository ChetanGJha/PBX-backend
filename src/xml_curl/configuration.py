import logging
from xml.etree.ElementTree import Element, SubElement, tostring
from typing import Dict, Any, Optional
from src.core.database import execute_query, execute_query_one

logger = logging.getLogger("pbx.xml_curl.configuration")

STRATEGY_MAP = {
    "round_robin": "round-robin",
    "longest_idle": "longest-idle-agent",
    "ring_all": "ring-all",
    "top_down": "top-down",
    "sequential": "top-down",
}


async def generate_callcenter_conf_xml() -> str:
    """
    Dynamically generates FreeSWITCH mod_callcenter callcenter.conf XML from PostgreSQL queues table.
    Declares all queues, active agents, and tier mappings.
    """
    doc = Element("document", type="freeswitch/xml")
    section = SubElement(doc, "section", name="configuration", description="CallCenter Configuration")
    config = SubElement(section, "configuration", name="callcenter.conf", description="CallCenter")

    settings = SubElement(config, "settings")
    SubElement(settings, "param", name="odbc-dsn", value="")

    queues_elem = SubElement(config, "queues")

    # Built-in fallback queues
    q_default = SubElement(queues_elem, "queue", name="default")
    SubElement(q_default, "param", name="strategy", value="round-robin")
    SubElement(q_default, "param", name="moh-sound", value="local_stream://moh")
    SubElement(q_default, "param", name="time-base-score", value="system")
    SubElement(q_default, "param", name="max-wait-time", value="0")

    q_support = SubElement(queues_elem, "queue", name="support@default")
    SubElement(q_support, "param", name="strategy", value="longest-idle-agent")
    SubElement(q_support, "param", name="moh-sound", value="local_stream://moh")
    SubElement(q_support, "param", name="time-base-score", value="system")
    SubElement(q_support, "param", name="max-wait-time", value="0")

    # Fetch active queues from database
    db_queues = await execute_query(
        """
        SELECT q.id, q.name, q.queue_number, q.strategy, q.agent_timeout, q.wrap_up_time,
               q.max_wait_time, q.agents, q.tenant_id, t.sip_domain
        FROM queues q
        LEFT JOIN tenants t ON q.tenant_id = t.id
        WHERE q.enabled = true AND q.deleted_at IS NULL
        ORDER BY q.queue_number ASC
        """
    )

    agents_elem = SubElement(config, "agents")
    tiers_elem = SubElement(config, "tiers")

    registered_agents = set()

    for q in db_queues:
        q_num = str(q.get("queue_number") or "").strip()
        q_name = str(q.get("name") or "").strip()
        raw_strat = q.get("strategy") or "round_robin"
        strat = STRATEGY_MAP.get(raw_strat, "round-robin")
        q_timeout = q.get("agent_timeout") or 30
        q_wrapup = q.get("wrap_up_time") or 10
        q_max_wait = q.get("max_wait_time") or 300
        tenant_id = str(q.get("tenant_id") or "")
        sip_domain = q.get("sip_domain") or "pbx.terrixai.com"

        if not q_num:
            continue

        # Declare Queue by number
        queue_names = [q_num]
        if q_name and q_name != q_num:
            safe_name = q_name.replace(" ", "_")
            queue_names.append(safe_name)

        for q_entry_name in queue_names:
            q_elem = SubElement(queues_elem, "queue", name=q_entry_name)
            SubElement(q_elem, "param", name="strategy", value=strat)
            SubElement(q_elem, "param", name="moh-sound", value="local_stream://moh")
            SubElement(q_elem, "param", name="record-template", value=f"/var/lib/freeswitch/recordings/{tenant_id or '${tenant_id}'}/${{uuid}}.wav")
            SubElement(q_elem, "param", name="time-base-score", value="system")
            SubElement(q_elem, "param", name="max-wait-time", value=str(q_max_wait))
            SubElement(q_elem, "param", name="max-wait-time-with-no-agent", value="0")
            SubElement(q_elem, "param", name="tier-rules-apply", value="false")
            SubElement(q_elem, "param", name="tier-rule-wait-second", value="300")
            SubElement(q_elem, "param", name="tier-rule-wait-multiply-level", value="true")
            SubElement(q_elem, "param", name="tier-rule-no-agent-no-wait", value="false")
            SubElement(q_elem, "param", name="discard-abandoned-after", value="60")
            SubElement(q_elem, "param", name="abandoned-resume-allowed", value="false")

        # Parse agents
        raw_agents = q.get("agents") or ""
        agent_list = [a.split("@")[0].strip() for a in raw_agents.split(",") if a.strip()]

        for agent_num in agent_list:
            if agent_num not in registered_agents:
                registered_agents.add(agent_num)
                # Contact attempts agent on sip_domain and local user
                contact_str = f"[leg_timeout={q_timeout}]user/{agent_num}@{sip_domain},user/{agent_num}"
                SubElement(
                    agents_elem,
                    "agent",
                    name=agent_num,
                    type="callback",
                    contact=contact_str,
                    status="Available",
                    max_no_answer="3",
                    wrap_up_time=str(q_wrapup),
                    reject_delay_time="10",
                    busy_delay_time="10"
                )

            # Map agent tier to each queue name
            for q_entry_name in queue_names:
                SubElement(
                    tiers_elem,
                    "tier",
                    queue=q_entry_name,
                    agent=agent_num,
                    level="1",
                    position="1"
                )

    xml_header = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    return xml_header + tostring(doc, encoding="utf-8").decode("utf-8")


def generate_conference_conf_xml() -> str:
    """
    Generates standard FreeSWITCH mod_conference configuration profiles.
    """
    return """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<document type="freeswitch/xml">
  <section name="configuration" description="Conference Configuration">
    <configuration name="conference.conf" description="Audio Conference">
      <caller-controls>
        <group name="default">
          <control action="mute" digits="0"/>
          <control action="deaf mute" digits="*"/>
          <control action="energy up" digits="9"/>
          <control action="energy equ" digits="8"/>
          <control action="energy dn" digits="7"/>
          <control action="vol talk up" digits="3"/>
          <control action="vol talk zero" digits="2"/>
          <control action="vol talk dn" digits="1"/>
          <control action="vol listen up" digits="6"/>
          <control action="vol listen zero" digits="5"/>
          <control action="vol listen dn" digits="4"/>
          <control action="hangup" digits="#"/>
        </group>
      </caller-controls>
      <profiles>
        <profile name="default">
          <param name="domain" value="$${domain}"/>
          <param name="rate" value="8000"/>
          <param name="interval" value="20"/>
          <param name="energy-level" value="300"/>
          <param name="moh-sound" value="local_stream://moh"/>
          <param name="caller-controls" value="default"/>
          <param name="comfort-noise" value="true"/>
        </profile>
        <profile name="wideband">
          <param name="domain" value="$${domain}"/>
          <param name="rate" value="16000"/>
          <param name="interval" value="20"/>
          <param name="energy-level" value="300"/>
          <param name="moh-sound" value="local_stream://moh"/>
          <param name="caller-controls" value="default"/>
          <param name="comfort-noise" value="true"/>
        </profile>
        <profile name="cdquality">
          <param name="domain" value="$${domain}"/>
          <param name="rate" value="48000"/>
          <param name="interval" value="20"/>
          <param name="energy-level" value="300"/>
          <param name="moh-sound" value="local_stream://moh"/>
          <param name="caller-controls" value="default"/>
          <param name="comfort-noise" value="true"/>
        </profile>
      </profiles>
    </configuration>
  </section>
</document>"""
