from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path

from .. import crypto
from ..config import EXPORT_DIR
from .documents import document_to_dict, get_document, read_original_bytes, search_documents


ZIP_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


def export_metadata_json(rows) -> str:
    return json.dumps([document_to_dict(row) for row in rows], ensure_ascii=False, indent=2)


def export_metadata_csv(rows) -> str:
    output: list[str] = []
    fieldnames = [
        "id",
        "title",
        "original_filename",
        "sha256",
        "md5_plain",
        "sha256_encrypted",
        "md5_encrypted",
        "size_bytes",
        "mime_type",
        "extension",
        "template_id",
        "tags",
        "extraction_status",
        "created_at",
    ]
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: document_to_dict(row)[key] for key in fieldnames})
    output.append(buffer.getvalue())
    return "".join(output)


def safe_zip_member(prefix: str, filename: str, document_id: int) -> str:
    safe_prefix = prefix.strip("/").replace("\\", "/")
    if "/" in safe_prefix or safe_prefix in {"", ".", ".."}:
        raise ValueError("Ogiltigt ZIP-prefix.")

    leaf = Path(filename.replace("\\", "/")).name.strip()
    leaf = ZIP_SAFE_SEGMENT_RE.sub("_", leaf).strip("._")
    if not leaf:
        leaf = "document"
    leaf = leaf[:180]
    return f"{safe_prefix}/{document_id}_{leaf}"


def selected_rows(document_ids: list[int], user_id: int | None = None):
    if not document_ids:
        return search_documents(user_id=user_id)
    return [row for row in (get_document(doc_id, user_id) for doc_id in document_ids) if row]


def create_zip_bytes(document_ids: list[int], user_id: int | None = None) -> bytes:
    rows = selected_rows(document_ids, user_id=user_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        manifest = []
        for row in rows:
            info = document_to_dict(row)
            manifest.append(info)
            archive.writestr(
                safe_zip_member("original", row["original_filename"], row["id"]),
                read_original_bytes(row, user_id=user_id),
            )
            archive.writestr(f"metadata/{row['id']}.json", json.dumps(info, ensure_ascii=False, indent=2))
            archive.writestr(f"text/{row['id']}.md", row["extracted_text"] or "")
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return buffer.getvalue()


def create_zip(document_ids: list[int], user_id: int | None = None) -> Path:
    """Persist an encrypted export artifact for audit/backup, never plaintext."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / "dokumenteraren_export.zip.enc"
    path.write_bytes(crypto.encrypt_bytes(create_zip_bytes(document_ids, user_id=user_id)))
    return path
