import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from src.core.email_service import (
    build_email_message,
    send_email_smtp,
    get_smtp_settings,
    send_voicemail_notification,
    format_duration
)


def test_format_duration():
    assert format_duration(0) == '00:00'
    assert format_duration(25) == '00:25'
    assert format_duration(65) == '01:05'
    assert format_duration(3665) == '01:01:05'


def test_build_email_message_without_attachment():
    smtp_cfg = {
        'from_email': 'pbx@example.com',
        'from_name': 'Acme PBX'
    }
    msg = build_email_message(
        smtp_cfg=smtp_cfg,
        to_email='alice@example.com',
        subject='New Voicemail',
        html_body='<p>You have a new voicemail</p>',
        attachment_path=None
    )
    assert msg['From'] == 'Acme PBX <pbx@example.com>'
    assert msg['To'] == 'alice@example.com'
    assert msg['Subject'] == 'New Voicemail'
    
    payload = msg.get_payload()
    assert isinstance(payload, list)
    content_types = [part.get_content_type() for part in payload]
    assert 'text/html' in content_types
    assert 'audio/wav' not in content_types


def test_build_email_message_with_attachment():
    smtp_cfg = {
        'from_email': 'pbx@example.com',
        'from_name': 'Acme PBX'
    }
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tf:
        tf.write(b'RIFF dummy wav data')
        temp_wav = tf.name

    try:
        msg = build_email_message(
            smtp_cfg=smtp_cfg,
            to_email='bob@example.com',
            subject='Voicemail with Audio',
            html_body='<p>Audio attached</p>',
            attachment_path=temp_wav
        )
        content_types = [part.get_content_type() for part in msg.get_payload()]
        assert 'text/html' in content_types
        assert 'audio/wav' in content_types
        
        attachment_part = [p for p in msg.get_payload() if p.get_content_type() == 'audio/wav'][0]
        assert os.path.basename(temp_wav) in attachment_part.get('Content-Disposition')
    finally:
        if os.path.exists(temp_wav):
            os.remove(temp_wav)


@pytest.mark.asyncio
async def test_get_smtp_settings_tenant_specific():
    fake_tenant_settings = {
        'id': '11111111-1111-1111-1111-111111111111',
        'tenant_id': '22222222-2222-2222-2222-222222222222',
        'smtp_host': 'smtp.tenant.com',
        'smtp_port': 587,
        'from_email': 'voicemail@tenant.com'
    }
    with patch('src.core.email_service.execute_query_one', new_callable=AsyncMock) as mock_query:
        mock_query.return_value = fake_tenant_settings
        settings, is_global = await get_smtp_settings('22222222-2222-2222-2222-222222222222')
        assert settings == fake_tenant_settings
        assert is_global is False


@pytest.mark.asyncio
async def test_get_smtp_settings_fallback_to_global():
    fake_global_settings = {
        'id': 'global-1111',
        'tenant_id': None,
        'smtp_host': 'smtp.globalpbx.com',
        'smtp_port': 587,
        'from_email': 'pbx@globalpbx.com'
    }
    with patch('src.core.email_service.execute_query_one', new_callable=AsyncMock) as mock_query:
        mock_query.side_effect = [None, fake_global_settings]
        settings, is_global = await get_smtp_settings('some-tenant-id')
        assert settings == fake_global_settings
        assert is_global is True


@pytest.mark.asyncio
async def test_send_email_smtp_success():
    smtp_cfg = {
        'smtp_host': 'smtp.test.com',
        'smtp_port': 587,
        'smtp_username': 'user',
        'smtp_password': 'pass',
        'from_email': 'pbx@test.com',
        'from_name': 'PBX',
        'use_tls': True
    }
    with patch('smtplib.SMTP') as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        success, err = await send_email_smtp(
            smtp_cfg=smtp_cfg,
            to_email='test@user.com',
            subject='Test Subject',
            html_body='<b>Test</b>'
        )
        assert success is True
        assert err == ''
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with('user', 'pass')
        mock_server.send_message.assert_called_once()
        mock_server.quit.assert_called_once()


@pytest.mark.asyncio
async def test_send_email_smtp_connection_failure():
    smtp_cfg = {
        'smtp_host': 'smtp.badhost.com',
        'smtp_port': 587,
        'from_email': 'pbx@test.com'
    }
    with patch('smtplib.SMTP', side_effect=Exception('Connection refused')):
        success, err = await send_email_smtp(
            smtp_cfg=smtp_cfg,
            to_email='test@user.com',
            subject='Test',
            html_body='<b>Test</b>'
        )
        assert success is False
        assert 'Connection refused' in err


@pytest.mark.asyncio
async def test_send_voicemail_notification_delete_after_email():
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tf:
        tf.write(b'wav file content')
        temp_wav = tf.name

    mock_vb = {
        'email_notification': True,
        'email_attach_file': True,
        'email_address': 'user@domain.com',
        'delete_after_email': True,
        'ext_email': 'user@domain.com',
        'display_name': 'Agent 1001',
        'tenant_name': 'Acme Corp'
    }
    mock_smtp = {
        'smtp_host': 'smtp.test.com',
        'smtp_port': 587,
        'from_email': 'pbx@test.com'
    }

    with patch('src.core.email_service.execute_query_one', new_callable=AsyncMock) as mock_query,          patch('src.core.email_service.get_smtp_settings', new_callable=AsyncMock) as mock_get_smtp,          patch('src.core.email_service.send_email_smtp', new_callable=AsyncMock) as mock_send:
        
        mock_query.return_value = mock_vb
        mock_get_smtp.return_value = (mock_smtp, False)
        mock_send.return_value = (True, '')

        await send_voicemail_notification(
            extension_number='1001',
            caller_id_number='9001',
            caller_id_name='MicroSIP',
            file_path=temp_wav,
            duration=12,
            tenant_id='tenant-123'
        )

        mock_send.assert_called_once()
        assert not os.path.exists(temp_wav)
