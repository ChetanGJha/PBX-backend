import logging
from fastapi import APIRouter, Request, Response
from src.xml_curl.directory import handle_directory_request

logger = logging.getLogger("pbx.xml_curl.router")

router = APIRouter(prefix="/freeswitch", tags=["FreeSWITCH mod_xml_curl"])

NOT_FOUND_XML = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<document type="freeswitch/xml">
  <section name="result">
    <result status="not found"/>
  </section>
</document>"""


@router.post("/xml")
async def handle_xml_curl(request: Request):
    """
    Main HTTP POST handler for FreeSWITCH mod_xml_curl integration.
    FreeSWITCH sends form-encoded parameter requests for directory, dialplan, configuration, etc.
    """
    try:
        form_data = await request.form()
        form_dict = {k: v for k, v in form_data.items()}

        section = form_dict.get("section")
        key_name = form_dict.get("key_name")
        key_value = form_dict.get("key_value")

        logger.info(f"mod_xml_curl request received: section='{section}', key_name='{key_name}', key_value='{key_value}'")

        if section == "directory":
            xml_response = await handle_directory_request(form_dict)
            return Response(content=xml_response, media_type="text/xml")
        
        # Other sections (dialplan, configuration) will return default/not_found until configured dynamically in Phase 3
        logger.debug(f"Unhandled mod_xml_curl section: '{section}'")
        return Response(content=NOT_FOUND_XML, media_type="text/xml")

    except Exception as exc:
        logger.error(f"Error handling mod_xml_curl request: {exc}", exc_info=True)
        return Response(content=NOT_FOUND_XML, media_type="text/xml")
