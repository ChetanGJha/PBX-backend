import os
import smtplib
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formatdate

from src.core.database import execute_query_one

logger = logging.getLogger("pbx.email_service")


def format_duration(seconds: int) -> str:
    """Format call duration in seconds to MM:SS or HH:MM:SS."""
    if seconds <= 0:
        return "00:00"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def build_email_message(
    smtp_cfg: dict,
    to_email: str,
    subject: str,
    html_body: str,
    attachment_path: Optional[str] = None
) -> MIMEMultipart:
    """
    Constructs a standard MIME multipart message with UTF-8 HTML body
    and optional audio/wav attachment.
    """
    from_name = smtp_cfg.get("from_name") or "PBX Voicemail"
    from_email = smtp_cfg.get("from_email") or "voicemail@pbx.local"

    msg = MIMEMultipart("mixed")
    if from_name:
        msg["From"] = f"{from_name} <{from_email}>"
    else:
        msg["From"] = from_email

    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)

    # Attach HTML Body
    html_part = MIMEText(html_body, "html", "utf-8")
    msg.attach(html_part)

    # Attach Audio File if specified and exists
    if attachment_path and os.path.exists(attachment_path):
        try:
            with open(attachment_path, "rb") as f:
                audio_data = f.read()
            audio_part = MIMEBase("audio", "wav")
            audio_part.set_payload(audio_data)
            encoders.encode_base64(audio_part)
            filename = os.path.basename(attachment_path)
            audio_part.add_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"'
            )
            msg.attach(audio_part)
            logger.info(f"Attached audio file '{filename}' ({len(audio_data)} bytes) to email for {to_email}")
        except Exception as att_err:
            logger.warning(f"Failed to attach voicemail audio '{attachment_path}': {att_err}")

    return msg


def _sync_send_smtp(smtp_cfg: dict, msg: MIMEMultipart, to_email: str) -> Tuple[bool, str]:
    """
    Synchronous SMTP delivery helper invoked via asyncio.to_thread.
    """
    host = smtp_cfg.get("smtp_host", "localhost")
    port = int(smtp_cfg.get("smtp_port") or 587)
    username = smtp_cfg.get("smtp_username")
    password = smtp_cfg.get("smtp_password")
    use_tls = bool(smtp_cfg.get("use_tls", True))

    server = None
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            if use_tls:
                server.ehlo()
                server.starttls()
                server.ehlo()

        if username and password:
            server.login(username, password)

        server.send_message(msg)
        logger.info(f"SMTP email successfully delivered to '{to_email}' via {host}:{port}")
        return True, ""
    except Exception as exc:
        err_msg = str(exc)
        logger.error(f"SMTP delivery failed to '{to_email}' via {host}:{port} - {err_msg}")
        return False, err_msg
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass


async def send_email_smtp(
    smtp_cfg: dict,
    to_email: str,
    subject: str,
    html_body: str,
    attachment_path: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Asynchronously sends an email via SMTP in a background thread to prevent
    blocking the event loop.
    """
    msg = build_email_message(smtp_cfg, to_email, subject, html_body, attachment_path)
    return await asyncio.to_thread(_sync_send_smtp, smtp_cfg, msg, to_email)


async def get_smtp_settings(tenant_id: Optional[str]) -> Tuple[Optional[dict], bool]:
    """
    Hierarchical resolution of SMTP settings:
    1. Tenant-specific settings (tenant_id = :tenant_id) -> returns (settings, False)
    2. Global PBX settings (tenant_id IS NULL) -> returns (settings, True)
    3. If neither found -> returns (None, False)
    """
    # 1. Check Tenant-specific
    if tenant_id:
        try:
            tenant_row = await execute_query_one(
                """
                SELECT id, tenant_id, smtp_host, smtp_port, smtp_username,
                       smtp_password, from_email, from_name, use_tls, updated_at
                FROM email_settings
                WHERE tenant_id = CAST(:tid AS uuid)
                """,
                {"tid": tenant_id}
            )
            if tenant_row:
                return dict(tenant_row), False
        except Exception as e:
            logger.warning(f"Error querying tenant SMTP settings for {tenant_id}: {e}")

    # 2. Fallback to Global default
    try:
        global_row = await execute_query_one(
            """
            SELECT id, tenant_id, smtp_host, smtp_port, smtp_username,
                   smtp_password, from_email, from_name, use_tls, updated_at
            FROM email_settings
            WHERE tenant_id IS NULL
            LIMIT 1
            """
        )
        if global_row:
            return dict(global_row), True
    except Exception as e:
        logger.warning(f"Error querying global SMTP settings: {e}")

    return None, False


def build_voicemail_html(
    extension_number: str,
    caller_id_number: str,
    caller_id_name: str,
    duration: int,
    tenant_name: str,
    received_at: str
) -> str:
    """Builds a responsive, elegant HTML email template for voicemail notifications."""
    dur_str = format_duration(duration)
    caller_display = f"{caller_id_name} ({caller_id_number})" if caller_id_name and caller_id_name != caller_id_number else caller_id_number

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>New Voicemail Received</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #0f172a;
      color: #f8fafc;
      margin: 0;
      padding: 24px;
    }}
    .container {{
      max-width: 580px;
      margin: 0 auto;
      background-color: #1e293b;
      border-radius: 12px;
      overflow: hidden;
      border: 1px solid #334155;
      box-shadow: 0 10px 25px rgba(0,0,0,0.5);
    }}
    .header {{
      background: linear-gradient(135deg, #2563eb, #7c3aed);
      padding: 24px 28px;
      text-align: left;
    }}
    .header h1 {{
      margin: 0;
      font-size: 20px;
      font-weight: 700;
      color: #ffffff;
      letter-spacing: -0.5px;
    }}
    .header p {{
      margin: 4px 0 0 0;
      font-size: 13px;
      color: #cbd5e1;
    }}
    .content {{
      padding: 28px;
    }}
    .meta-box {{
      background-color: #0f172a;
      border: 1px solid #334155;
      border-radius: 8px;
      margin-bottom: 24px;
      overflow: hidden;
    }}
    .meta-row {{
      display: flex;
      padding: 12px 16px;
      border-bottom: 1px solid #1e293b;
    }}
    .meta-row:last-child {{
      border-bottom: none;
    }}
    .meta-label {{
      width: 140px;
      font-size: 13px;
      font-weight: 600;
      color: #94a3b8;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .meta-val {{
      flex: 1;
      font-size: 14px;
      font-weight: 500;
      color: #f1f5f9;
    }}
    .highlight {{
      color: #38bdf8;
      font-weight: 600;
    }}
    .notice {{
      background-color: rgba(56, 189, 248, 0.1);
      border-left: 4px solid #38bdf8;
      padding: 12px 16px;
      border-radius: 4px;
      font-size: 13px;
      color: #bae6fd;
      line-height: 1.5;
    }}
    .footer {{
      padding: 16px 28px;
      background-color: #172033;
      border-top: 1px solid #334155;
      font-size: 12px;
      color: #64748b;
      text-align: center;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>New Voicemail Message</h1>
      <p>{tenant_name} PBX System Notification</p>
    </div>
    <div class="content">
      <div class="meta-box">
        <div class="meta-row">
          <div class="meta-label">Recipient Ext</div>
          <div class="meta-val highlight">{extension_number}</div>
        </div>
        <div class="meta-row">
          <div class="meta-label">Caller</div>
          <div class="meta-val">{caller_display}</div>
        </div>
        <div class="meta-row">
          <div class="meta-label">Duration</div>
          <div class="meta-val">{dur_str}</div>
        </div>
        <div class="meta-row">
          <div class="meta-label">Date & Time</div>
          <div class="meta-val">{received_at} UTC</div>
        </div>
      </div>
      <div class="notice">
        Audio recording has been attached to this email. You can also dial <strong>*97</strong> from your phone to access your voicemail inbox.
      </div>
    </div>
    <div class="footer">
      This is an automated notification from your PBX phone system. Please do not reply directly to this email.
    </div>
  </div>
</body>
</html>"""


async def send_voicemail_notification(
    extension_number: str,
    caller_id_number: str,
    caller_id_name: str,
    file_path: str,
    duration: int,
    tenant_id: str
) -> None:
    """
    Main asynchronous worker called when a voicemail is recorded.
    1. Looks up recipient extension email and voicemail settings.
    2. Resolves tenant or global SMTP configuration.
    3. Builds and sends email with audio attachment (if configured).
    4. Handles delete_after_email cleanup if configured.
    """
    try:
        logger.info(f"Processing voicemail email dispatch for ext={extension_number}, tenant={tenant_id}")

        # 1. Lookup Voicemail Box settings and extension
        vm_box = await execute_query_one(
            """
            SELECT vb.email_notification, vb.email_attach_file, vb.email_address, vb.delete_after_email,
                   e.email as ext_email, e.display_name, t.name as tenant_name
            FROM voicemail_boxes vb
            JOIN extensions e ON vb.extension_id = e.id
            JOIN tenants t ON e.tenant_id = t.id
            WHERE vb.mailbox = :mailbox AND vb.tenant_id = CAST(:tid AS uuid)
            """,
            {"mailbox": extension_number, "tid": tenant_id}
        )

        tenant_name = "PBX"
        email_notification = True
        email_attach_file = True
        delete_after_email = False
        target_email = None

        if vm_box:
            email_notification = bool(vm_box.get("email_notification", True))
            email_attach_file = bool(vm_box.get("email_attach_file", True))
            delete_after_email = bool(vm_box.get("delete_after_email", False))
            target_email = vm_box.get("email_address") or vm_box.get("ext_email")
            tenant_name = vm_box.get("tenant_name") or tenant_name
        else:
            # Fallback: check extension directly
            ext_row = await execute_query_one(
                """
                SELECT e.email as ext_email, e.display_name, t.name as tenant_name
                FROM extensions e
                JOIN tenants t ON e.tenant_id = t.id
                WHERE e.extension_number = :ext AND e.tenant_id = CAST(:tid AS uuid)
                """,
                {"ext": extension_number, "tid": tenant_id}
            )
            if ext_row:
                target_email = ext_row.get("ext_email")
                tenant_name = ext_row.get("tenant_name") or tenant_name

        if not email_notification:
            logger.info(f"Email notification is disabled for ext {extension_number}; skipping email dispatch.")
            return

        if not target_email:
            logger.warning(f"No recipient email found for extension {extension_number} in tenant {tenant_id}; skipping email dispatch.")
            return

        # 2. Resolve SMTP Settings (Tenant -> Global fallback)
        smtp_cfg, is_global = await get_smtp_settings(tenant_id)
        if not smtp_cfg:
            logger.warning(
                f"No SMTP settings configured for tenant {tenant_id} or global PBX. "
                f"Voicemail for {extension_number} could not be emailed."
            )
            return

        source_info = "global PBX fallback" if is_global else f"tenant {tenant_id}"
        logger.info(f"Using SMTP server {smtp_cfg.get('smtp_host')} from {source_info} to email {target_email}")

        # 3. Construct Message
        subject = f"New Voicemail from {caller_id_name or caller_id_number} ({format_duration(duration)})"
        received_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        html_body = build_voicemail_html(
            extension_number=extension_number,
            caller_id_number=caller_id_number,
            caller_id_name=caller_id_name,
            duration=duration,
            tenant_name=tenant_name,
            received_at=received_at
        )

        attachment = file_path if (email_attach_file and file_path and os.path.exists(file_path)) else None

        # 4. Dispatch Email
        success, error_msg = await send_email_smtp(
            smtp_cfg=smtp_cfg,
            to_email=target_email,
            subject=subject,
            html_body=html_body,
            attachment_path=attachment
        )

        # 5. Post-send cleanup
        if success:
            logger.info(f"Voicemail notification email successfully sent to {target_email}")
            if delete_after_email and file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted voicemail file '{file_path}' after email delivery (delete_after_email=True)")
                except Exception as del_err:
                    logger.warning(f"Failed to delete voicemail file '{file_path}': {del_err}")
        else:
            logger.error(f"Failed to send voicemail notification email to {target_email}: {error_msg}")

    except Exception as exc:
        logger.error(f"Unexpected error in send_voicemail_notification: {exc}", exc_info=True)
