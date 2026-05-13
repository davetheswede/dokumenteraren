from __future__ import annotations

import asyncio
import hashlib
import imaplib
import mimetypes
import poplib
import ssl
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import parseaddr
from typing import Protocol

from fastapi import HTTPException

from .. import db
from ..security import safe_filename
from .classification import auto_classify
from .documents import existing_document_id_for_content, save_document_bytes
from .importer import import_owner_user_id


class MailImportError(RuntimeError):
    pass


@dataclass(frozen=True)
class MailRef:
    id: str
    uid: str


class MailClient(Protocol):
    def list_messages(self, limit: int) -> list[MailRef]: ...
    def fetch_message(self, ref: MailRef) -> bytes: ...
    def delete_message(self, ref: MailRef) -> None: ...
    def close(self) -> None: ...


class PopMailClient:
    def __init__(self, settings: dict[str, str]) -> None:
        host = settings["mail_import_host"]
        port = int(settings.get("mail_import_port") or ("995" if settings.get("mail_import_ssl") == "true" else "110"))
        timeout = 30
        if settings.get("mail_import_ssl", "true") == "true":
            self.client = poplib.POP3_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
        else:
            self.client = poplib.POP3(host, port, timeout=timeout)
        self.client.user(settings["mail_import_username"])
        self.client.pass_(settings["mail_import_password"])

    def list_messages(self, limit: int) -> list[MailRef]:
        uid_lines = self.client.uidl()[1]
        refs = []
        for line in uid_lines[:limit]:
            parts = line.decode("utf-8", errors="replace").split()
            if len(parts) >= 2:
                refs.append(MailRef(parts[0], parts[1]))
        return refs

    def fetch_message(self, ref: MailRef) -> bytes:
        return b"\n".join(self.client.retr(int(ref.id))[1])

    def delete_message(self, ref: MailRef) -> None:
        self.client.dele(int(ref.id))

    def close(self) -> None:
        self.client.quit()


class ImapMailClient:
    def __init__(self, settings: dict[str, str]) -> None:
        host = settings["mail_import_host"]
        port = int(settings.get("mail_import_port") or ("993" if settings.get("mail_import_ssl") == "true" else "143"))
        if settings.get("mail_import_ssl", "true") == "true":
            self.client = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())
        else:
            self.client = imaplib.IMAP4(host, port)
        self.client.login(settings["mail_import_username"], settings["mail_import_password"])
        status, _ = self.client.select(settings.get("mail_import_folder") or "INBOX")
        if status != "OK":
            raise MailImportError("IMAP-folder kunde inte öppnas.")

    def list_messages(self, limit: int) -> list[MailRef]:
        status, data = self.client.search(None, "ALL")
        if status != "OK" or not data:
            return []
        ids = data[0].split()[:limit]
        refs = []
        for message_id in ids:
            status, uid_data = self.client.fetch(message_id, "(UID)")
            uid = message_id.decode("ascii")
            if status == "OK" and uid_data and isinstance(uid_data[0], bytes):
                parts = uid_data[0].decode("ascii", errors="replace").split()
                if "UID" in parts:
                    uid = parts[parts.index("UID") + 1].strip(")")
            refs.append(MailRef(message_id.decode("ascii"), uid))
        return refs

    def fetch_message(self, ref: MailRef) -> bytes:
        status, data = self.client.fetch(ref.id.encode("ascii"), "(RFC822)")
        if status != "OK" or not data:
            raise MailImportError("IMAP-meddelande kunde inte hämtas.")
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                return item[1]
        raise MailImportError("IMAP-meddelande saknade innehåll.")

    def delete_message(self, ref: MailRef) -> None:
        self.client.store(ref.id.encode("ascii"), "+FLAGS", "\\Deleted")
        self.client.expunge()

    def close(self) -> None:
        try:
            self.client.close()
        except imaplib.IMAP4.error:
            pass
        self.client.logout()


def configured(settings: dict[str, str] | None = None) -> bool:
    settings = settings or db.get_settings()
    return all(
        [
            settings.get("mail_import_host"),
            settings.get("mail_import_username"),
            settings.get("mail_import_password"),
            settings.get("mail_import_protocol") in {"pop3", "imap"},
        ]
    )


def build_client(settings: dict[str, str]) -> MailClient:
    if settings.get("mail_import_protocol") == "imap":
        return ImapMailClient(settings)
    return PopMailClient(settings)


def is_ignorable_inline_part(part: Message, filename: str, min_inline_image_bytes: int) -> bool:
    disposition = (part.get_content_disposition() or "").lower()
    content_type = part.get_content_type().lower()
    if disposition != "inline" or not content_type.startswith("image/"):
        return False
    payload = part.get_payload(decode=True) or b""
    return len(payload) < min_inline_image_bytes or not filename


def attachment_parts(message: Message, min_inline_image_bytes: int) -> list[tuple[str, bytes, str]]:
    attachments = []
    for index, part in enumerate(message.walk(), start=1):
        if part.is_multipart():
            continue
        filename = part.get_filename() or ""
        disposition = (part.get_content_disposition() or "").lower()
        if not filename and disposition != "attachment":
            continue
        if is_ignorable_inline_part(part, filename, min_inline_image_bytes):
            continue
        payload = part.get_payload(decode=True) or b""
        if not payload:
            continue
        content_type = part.get_content_type() or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        safe_name = safe_filename(filename or f"attachment-{index}")
        attachments.append((safe_name, payload, content_type))
    return attachments


def import_content(
    filename: str,
    content: bytes,
    *,
    content_type: str | None,
    subject: str,
    sender: str,
    default_tags: str,
    uid: str,
) -> dict[str, object]:
    digest = hashlib.sha256(content).hexdigest()
    existing_id = existing_document_id_for_content(content)
    if existing_id:
        db.record_import_event(filename, "duplicate", f"Mailimport dubblett ({uid}).", existing_id, digest)
        return {"filename": filename, "status": "duplicate", "document_id": existing_id}
    template_id, tags = auto_classify(filename, subject=subject, sender=sender, default_tags=default_tags, source_tag="mailimport")
    try:
        document_id = save_document_bytes(content, filename, import_owner_user_id(), template_id, tags, mime_type=content_type)
    except Exception as exc:
        message = "Mailattachment kunde inte importeras."
        if isinstance(exc, HTTPException):
            message = str(exc.detail)
        db.record_import_event(filename, "failed", f"{message} ({uid})", None, digest)
        return {"filename": filename, "status": "failed", "message": message}
    db.record_import_event(filename, "imported", f"Importerad från mail ({uid}).", document_id, digest)
    return {"filename": filename, "status": "imported", "document_id": document_id}


def process_message_bytes(raw_message: bytes, settings: dict[str, str], uid: str = "manual") -> list[dict[str, object]]:
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    subject = str(message.get("subject") or "")
    sender = parseaddr(str(message.get("from") or ""))[1]
    min_inline_image_bytes = int(settings.get("mail_import_min_inline_image_bytes") or "10240")
    default_tags = settings.get("mail_import_default_tags") or "mailimport"
    parts = attachment_parts(message, min_inline_image_bytes)
    if not parts and settings.get("mail_import_import_eml_without_attachments", "true") == "true":
        base_name = safe_filename(subject or "mail")
        parts = [(f"{base_name}.eml", raw_message, "message/rfc822")]
    results = [
        import_content(
            filename,
            content,
            content_type=content_type,
            subject=subject,
            sender=sender,
            default_tags=default_tags,
            uid=uid,
        )
        for filename, content, content_type in parts
    ]
    if not results:
        db.record_import_event(subject or uid, "failed", f"Mail utan importerbart innehåll ({uid}).", None, None)
        return [{"filename": subject or uid, "status": "failed", "message": "Mail utan importerbart innehåll."}]
    return results


def process_mail_import_once(force: bool = False) -> list[dict[str, object]]:
    settings = db.get_settings()
    if (not force and settings.get("mail_import_enabled") != "true") or not configured(settings):
        return []
    client = build_client(settings)
    results: list[dict[str, object]] = []
    handled = 0
    try:
        for ref in client.list_messages(int(settings.get("mail_import_max_messages") or "10")):
            raw_message = client.fetch_message(ref)
            message_results = process_message_bytes(raw_message, settings, uid=ref.uid)
            results.extend(message_results)
            handled += 1
            if settings.get("mail_import_delete_after_handled", "true") == "true":
                client.delete_message(ref)
    finally:
        client.close()
    db.set_settings(
        {
            "mail_import_last_status": f"{handled} mail hanterade, {len(results)} importhändelser.",
            "mail_import_last_run_at": db.utc_now(),
        }
    )
    return results


def test_connection(settings: dict[str, str] | None = None) -> tuple[bool, str]:
    settings = settings or db.get_settings()
    if not configured(settings):
        return False, "Mailimport är inte komplett konfigurerad."
    client = build_client(settings)
    try:
        count = len(client.list_messages(1))
    finally:
        client.close()
    return True, f"Mailanslutning OK. Minst {count} meddelande hittades vid test."


async def import_loop() -> None:
    while True:
        settings = db.get_settings()
        interval = max(30, int(settings.get("mail_import_poll_interval_seconds") or "300"))
        if settings.get("mail_import_enabled") == "true" and configured(settings):
            try:
                process_mail_import_once()
            except Exception as exc:
                db.set_settings(
                    {
                        "mail_import_last_status": f"Mailimport misslyckades: {exc.__class__.__name__}",
                        "mail_import_last_run_at": db.utc_now(),
                    }
                )
        await asyncio.sleep(interval)
