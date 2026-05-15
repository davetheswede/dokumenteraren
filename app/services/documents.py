from __future__ import annotations

import hashlib
import json
import mimetypes
import tempfile
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from .. import crypto
from .. import db
from ..config import ALLOWED_EXTENSIONS, DERIVED_DIR, MAX_UPLOAD_BYTES, UPLOAD_DIR
from ..security import safe_filename
from .extraction import extract_document


async def save_upload(file: UploadFile, user_id: int, template_id: str | None, tags: str | None) -> int:
    submitted_name = file.filename or "document"
    safe_name = safe_filename(submitted_name)
    content = await file.read()
    mime_type = file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    return save_document_bytes(content, safe_name, user_id, template_id, tags, mime_type=mime_type)


def existing_document_id_for_content(content: bytes) -> int | None:
    digest = hashlib.sha256(content).hexdigest()
    with db.connect() as conn:
        row = conn.execute("SELECT id FROM documents WHERE sha256 = ? ORDER BY id LIMIT 1", (digest,)).fetchone()
    return int(row["id"]) if row else None


def save_document_bytes(
    content: bytes,
    submitted_name: str,
    user_id: int,
    template_id: str | None = "",
    tags: str | None = "",
    mime_type: str | None = None,
) -> int:
    safe_name = safe_filename(submitted_name)
    extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filtypen är inte tillåten.")

    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Filen är för stor.")
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filen är tom.")

    digest = hashlib.sha256(content).hexdigest()
    md5_plain = hashlib.md5(content, usedforsecurity=False).hexdigest()
    stored_name = f"{uuid.uuid4().hex}.blob.enc"
    storage_path = UPLOAD_DIR / stored_name
    document_key = crypto.random_key()

    with tempfile.TemporaryDirectory(prefix="dokumenteraren-extract-") as tmpdir:
        plaintext_path = Path(tmpdir) / safe_name
        plaintext_path.write_bytes(content)
        extraction = extract_document(plaintext_path, extension, safe_name)

    encrypted_content = crypto.encrypt_bytes(content, document_key)
    storage_path.write_bytes(encrypted_content)
    sha256_encrypted = hashlib.sha256(encrypted_content).hexdigest()
    md5_encrypted = hashlib.md5(encrypted_content, usedforsecurity=False).hexdigest()
    text_path = DERIVED_DIR / f"{Path(stored_name).stem}.txt.enc"
    text_path.write_bytes(crypto.encrypt_bytes(extraction.text.encode("utf-8"), document_key))

    title = Path(safe_name).stem[:200] or safe_name
    mime_type = mime_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    metadata_json = json.dumps(extraction.metadata, ensure_ascii=False, sort_keys=True)
    encrypted_metadata = crypto.encrypt_text(metadata_json, document_key)
    encrypted_text = crypto.encrypt_text(extraction.text, document_key)

    with db.connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO documents (
                title, original_filename, stored_filename, storage_path, text_path, sha256, size_bytes,
                md5_plain, sha256_encrypted, md5_encrypted, mime_type, extension, template_id, tags, metadata_json, extracted_text, extraction_status,
                uploaded_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                crypto.encrypt_text(title, document_key),
                crypto.encrypt_text(safe_name, document_key),
                stored_name,
                str(storage_path),
                str(text_path),
                digest,
                len(content),
                md5_plain,
                sha256_encrypted,
                md5_encrypted,
                mime_type,
                extension,
                template_id or "",
                crypto.encrypt_text(tags or "", document_key),
                encrypted_metadata,
                encrypted_text,
                extraction.status,
                user_id,
                db.utc_now(),
            ),
        )
        document_id = int(cursor.lastrowid)
        db.set_document_key(conn, document_id, user_id, document_key)
        db.upsert_document_fts(conn, document_id, "", "", "", "")
    return document_id


def get_document(document_id: int, user_id: int | None = None, *, allow_admin: bool = False):
    with db.connect() as conn:
        if user_id is None or allow_admin:
            row = conn.execute("SELECT d.*, 'owner' AS access_permission FROM documents d WHERE d.id = ?", (document_id,)).fetchone()
        else:
            row = conn.execute(
                """
                SELECT d.*, a.permission AS access_permission
                FROM documents d
                JOIN document_access a ON a.document_id = d.id
                WHERE d.id = ? AND a.user_id = ?
                """,
                (document_id, user_id),
            ).fetchone()
    return decrypt_document_row(row, user_id=user_id) if row else None


def delete_document(document_id: int, user_id: int | None = None) -> bool:
    with db.connect() as conn:
        if user_id is None:
            row = conn.execute("SELECT storage_path, text_path FROM documents WHERE id = ?", (document_id,)).fetchone()
        else:
            row = conn.execute(
                """
                SELECT d.storage_path, d.text_path
                FROM documents d
                JOIN document_access a ON a.document_id = d.id
                WHERE d.id = ? AND a.user_id = ? AND a.permission = 'owner'
                """,
                (document_id, user_id),
            ).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM document_keys WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM document_access WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))

    for path_value in (row["storage_path"], row["text_path"]):
        if not path_value:
            continue
        try:
            Path(path_value).unlink(missing_ok=True)
        except OSError:
            pass
    return True


def update_document_classification(document_id: int, template_id: str, tags: str, user_id: int | None = None) -> bool:
    permission = db.document_permission(document_id, user_id) if user_id is not None else "owner"
    if permission != "owner":
        return False
    key = db.get_document_key(document_id, user_id)
    if not key:
        return False
    with db.connect() as conn:
        row = conn.execute("SELECT id FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE documents SET template_id = ?, tags = ? WHERE id = ?",
            (template_id or "", crypto.encrypt_text(tags or "", key), document_id),
        )
    return True


def update_document_tags(document_id: int, tags: str, user_id: int | None = None) -> bool:
    row = get_document(document_id, user_id)
    if not row:
        return False
    return update_document_classification(document_id, str(row["template_id"] or ""), tags, user_id)


def verify_document_checksums(row) -> dict[str, object]:
    storage_path = Path(row["storage_path"])
    result = {
        "ok": False,
        "plain_sha256_ok": False,
        "plain_md5_ok": False,
        "encrypted_sha256_ok": False,
        "encrypted_md5_ok": False,
        "message": "Originalfilen saknas i lagringen.",
    }
    if not storage_path.exists():
        return result
    encrypted_content = storage_path.read_bytes()
    key = db.get_document_key(int(row["id"]), int(row.get("access_user_id") or 0) or None)
    try:
        plain_content = crypto.decrypt_bytes(encrypted_content, key) if key else encrypted_content
    except Exception:
        result["message"] = "Krypterad fil kunde inte dekrypteras för verifiering."
        return result
    result["plain_sha256_ok"] = hashlib.sha256(plain_content).hexdigest() == row["sha256"]
    result["plain_md5_ok"] = hashlib.md5(plain_content, usedforsecurity=False).hexdigest() == (row.get("md5_plain") or "")
    result["encrypted_sha256_ok"] = hashlib.sha256(encrypted_content).hexdigest() == (row.get("sha256_encrypted") or "")
    result["encrypted_md5_ok"] = hashlib.md5(encrypted_content, usedforsecurity=False).hexdigest() == (row.get("md5_encrypted") or "")
    result["ok"] = all(
        [
            result["plain_sha256_ok"],
            result["plain_md5_ok"],
            result["encrypted_sha256_ok"],
            result["encrypted_md5_ok"],
        ]
    )
    result["message"] = "Checksummor verifierade." if result["ok"] else "Minst en checksum matchar inte lagrad metadata."
    return result


def search_documents(
    q: str = "",
    template_id: str = "",
    status: str = "",
    tag: str = "",
    user_id: int | None = None,
    *,
    allow_admin: bool = False,
):
    params: list[object] = []
    if user_id is not None and not allow_admin:
        sql = """
        SELECT d.*, a.permission AS access_permission
        FROM documents d
        JOIN document_access a ON a.document_id = d.id
        """
        where: list[str] = ["a.user_id = ?"]
        params.append(user_id)
    else:
        sql = "SELECT d.*, 'owner' AS access_permission FROM documents d"
        where = []
    if q.strip():
        # Encrypted body/metadata cannot be stored in SQLite FTS as plaintext.
        # Filter coarse fields in SQL and scan decrypted rows below.
        pass
    if template_id:
        where.append("d.template_id = ?")
        params.append(template_id)
    if status:
        where.append("d.extraction_status = ?")
        params.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY d.created_at DESC LIMIT 250"
    with db.connect() as conn:
        rows = [decrypt_document_row(row, user_id=user_id) for row in conn.execute(sql, params).fetchall()]
    query = q.strip().lower()
    if query:
        terms = [part for part in query.split() if part]
        rows = [
            row
            for row in rows
            if all(
                term
                in " ".join(
                    [
                        row["title"],
                        row["original_filename"],
                        row["tags"],
                        row["metadata_json"],
                        row["extracted_text"],
                    ]
                ).lower()
                for term in terms
            )
        ]
    if tag:
        tag_query = tag.lower()
        rows = [row for row in rows if tag_query in (row["tags"] or "").lower()]
    return rows


def document_to_dict(row) -> dict[str, object]:
    return {
        "id": row["id"],
        "title": row["title"],
        "original_filename": row["original_filename"],
        "sha256": row["sha256"],
        "md5_plain": row.get("md5_plain") or "",
        "sha256_encrypted": row.get("sha256_encrypted") or "",
        "md5_encrypted": row.get("md5_encrypted") or "",
        "size_bytes": row["size_bytes"],
        "mime_type": row["mime_type"],
        "extension": row["extension"],
        "template_id": row["template_id"],
        "tags": row["tags"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
        "extraction_status": row["extraction_status"],
        "created_at": row["created_at"],
    }


def decrypt_document_row(row, user_id: int | None = None) -> dict[str, object]:
    document = dict(row)
    document["access_user_id"] = user_id
    document["access_permission"] = document.get("access_permission") or db.document_permission(int(document["id"]), user_id) if user_id else "owner"
    key = db.get_document_key(int(document["id"]), user_id)
    if key:
        document["title"] = crypto.decrypt_text(document["title"] or "", key)
        document["original_filename"] = crypto.decrypt_text(document["original_filename"] or "", key)
        document["tags"] = crypto.decrypt_text(document["tags"] or "", key)
        document["metadata_json"] = crypto.decrypt_text(document["metadata_json"] or "{}", key)
        document["extracted_text"] = crypto.decrypt_text(document["extracted_text"] or "", key)
    return document


def read_original_bytes(row, user_id: int | None = None) -> bytes:
    key = db.get_document_key(int(row["id"]), user_id or int(row.get("access_user_id") or 0) or None)
    path = Path(row["storage_path"])
    if not path.exists():
        raise FileNotFoundError(row["storage_path"])
    return crypto.decrypt_file(path, key) if key else path.read_bytes()


def read_text_bytes(row) -> bytes:
    key = db.get_document_key(int(row["id"]), int(row.get("access_user_id") or 0) or None)
    path_value = row.get("text_path") if isinstance(row, dict) else row["text_path"]
    if not path_value:
        return (row["extracted_text"] or "").encode("utf-8")
    path = Path(path_value)
    if not path.exists():
        return (row["extracted_text"] or "").encode("utf-8")
    return crypto.decrypt_file(path, key) if key else path.read_bytes()
