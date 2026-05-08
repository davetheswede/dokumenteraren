from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path


class MailConfigurationError(RuntimeError):
    pass


def smtp_configured() -> bool:
    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "MAIL_FROM"]
    return all(os.getenv(key) for key in required)


def send_mail(
    to_addr: str,
    subject: str,
    text: str,
    attachment: Path | None = None,
    attachment_bytes: bytes | None = None,
    attachment_name: str = "dokumenteraren_export.zip",
) -> None:
    if not smtp_configured():
        raise MailConfigurationError("SMTP är inte konfigurerat i env.")

    host = os.environ["SMTP_HOST"]
    port = int(os.getenv("SMTP_PORT", "587"))
    secure = os.getenv("SMTP_SECURE", "false").lower() == "true"
    username = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    from_addr = os.getenv("MAIL_FROM", "noreply@ath0.se")

    message = EmailMessage()
    message["From"] = from_addr
    message["To"] = to_addr
    message["Subject"] = subject
    message.set_content(text)
    if attachment_bytes is not None:
        message.add_attachment(attachment_bytes, maintype="application", subtype="zip", filename=attachment_name)
    elif attachment:
        data = attachment.read_bytes()
        message.add_attachment(data, maintype="application", subtype="octet-stream", filename=attachment.name)

    context = ssl.create_default_context()
    if secure:
        with smtplib.SMTP_SSL(host, port, timeout=15, context=context) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls(context=context)
            smtp.login(username, password)
            smtp.send_message(message)
