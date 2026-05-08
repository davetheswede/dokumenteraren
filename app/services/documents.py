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
    stored_name = f"{uuid.uuid4().hex}_{safe_name}.enc"
    storage_path = UPLOAD_DIR / stored_name
    document_key = crypto.random_key()

    with tempfile.TemporaryDirectory(prefix="dokumenteraren-extract-") as tmpdir:
        plaintext_path = Path(tmpdir) / safe_name
        plaintext_path.write_bytes(content)
        extraction = extract_document(plaintext_path, extension, safe_name)

    storage_path.write_bytes(crypto.encrypt_bytes(content, document_key))
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
                mime_type, extension, template_id, tags, metadata_json, extracted_text, extraction_status,
                uploaded_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                safe_name,
                stored_name,
                str(storage_path),
                str(text_path),
                digest,
                len(content),
                mime_type,
                extension,
                template_id or "",
                tags or "",
                encrypted_metadata,
                encrypted_text,
                extraction.status,
                user_id,
                db.utc_now(),
            ),
        )
        document_id = int(cursor.lastrowid)
        db.set_document_key(conn, document_id, user_id, document_key)
        db.upsert_document_fts(conn, document_id, title, tags or "", metadata_json, extraction.text)
    return document_id


def get_document(document_id: int):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    return decrypt_document_row(row) if row else None


def search_documents(q: str = "", template_id: str = "", status: str = "", tag: str = ""):
    params: list[object] = []
    sql = "SELECT d.* FROM documents d"
    where: list[str] = []
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
    if tag:
        where.append("d.tags LIKE ?")
        params.append(f"%{tag}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY d.created_at DESC LIMIT 250"
    with db.connect() as conn:
        rows = [decrypt_document_row(row) for row in conn.execute(sql, params).fetchall()]
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
    return rows


def document_to_dict(row) -> dict[str, object]:
    return {
        "id": row["id"],
        "title": row["title"],
        "original_filename": row["original_filename"],
        "sha256": row["sha256"],
        "size_bytes": row["size_bytes"],
        "mime_type": row["mime_type"],
        "extension": row["extension"],
        "template_id": row["template_id"],
        "tags": row["tags"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
        "extraction_status": row["extraction_status"],
        "created_at": row["created_at"],
    }


def decrypt_document_row(row) -> dict[str, object]:
    document = dict(row)
    key = db.get_document_key(int(document["id"]))
    if key:
        document["metadata_json"] = crypto.decrypt_text(document["metadata_json"] or "{}", key)
        document["extracted_text"] = crypto.decrypt_text(document["extracted_text"] or "", key)
    return document


def read_original_bytes(row) -> bytes:
    key = db.get_document_key(int(row["id"]))
    path = Path(row["storage_path"])
    if not path.exists():
        raise FileNotFoundError(row["storage_path"])
    return crypto.decrypt_file(path, key) if key else path.read_bytes()


def read_text_bytes(row) -> bytes:
    key = db.get_document_key(int(row["id"]))
    path_value = row.get("text_path") if isinstance(row, dict) else row["text_path"]
    if not path_value:
        return (row["extracted_text"] or "").encode("utf-8")
    path = Path(path_value)
    if not path.exists():
        return (row["extracted_text"] or "").encode("utf-8")
    return crypto.decrypt_file(path, key) if key else path.read_bytes()
