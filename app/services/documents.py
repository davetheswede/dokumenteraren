from __future__ import annotations

import hashlib
import json
import mimetypes
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from .. import db
from ..config import ALLOWED_EXTENSIONS, DERIVED_DIR, MAX_UPLOAD_BYTES, UPLOAD_DIR
from ..security import safe_filename
from .extraction import extract_document


async def save_upload(file: UploadFile, user_id: int, template_id: str | None, tags: str | None) -> int:
    submitted_name = file.filename or "document"
    safe_name = safe_filename(submitted_name)
    extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filtypen är inte tillåten.")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Filen är för stor.")
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filen är tom.")

    digest = hashlib.sha256(content).hexdigest()
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    storage_path = UPLOAD_DIR / stored_name
    storage_path.write_bytes(content)

    extraction = extract_document(storage_path, extension, safe_name)
    text_path = DERIVED_DIR / f"{storage_path.stem}.txt"
    text_path.write_text(extraction.text, encoding="utf-8")

    title = Path(safe_name).stem[:200] or safe_name
    mime_type = file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    metadata_json = json.dumps(extraction.metadata, ensure_ascii=False, sort_keys=True)

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
                metadata_json,
                extraction.text,
                extraction.status,
                user_id,
                db.utc_now(),
            ),
        )
        document_id = int(cursor.lastrowid)
        db.upsert_document_fts(conn, document_id, title, tags or "", metadata_json, extraction.text)
    return document_id


def get_document(document_id: int):
    with db.connect() as conn:
        return conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()


def search_documents(q: str = "", template_id: str = "", status: str = "", tag: str = ""):
    params: list[object] = []
    sql = "SELECT d.* FROM documents d"
    where: list[str] = []
    if q.strip():
        sql += " JOIN documents_fts fts ON fts.rowid = d.id"
        where.append("documents_fts MATCH ?")
        params.append(q.strip())
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
        return conn.execute(sql, params).fetchall()


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
