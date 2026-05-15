from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from fastapi import HTTPException

from .. import crypto, db
from ..config import IMPORT_DIR, IMPORT_FAILED_DIR
from ..security import safe_filename
from .classification import auto_classify
from .documents import existing_document_id_for_content, save_document_bytes


_seen: dict[Path, tuple[int, int]] = {}


def import_owner_user_id() -> int:
    settings = db.get_settings()
    configured = settings.get("import_owner_user_id", "").strip()
    if configured.isdigit():
        user = db.get_user(int(configured))
        if user and user["role"] != "admin" and user["status"] == "active":
            return int(user["id"])
    david = db.get_user_by_username("David")
    if david and david["role"] != "admin" and david["status"] == "active":
        db.set_settings({"import_owner_user_id": str(david["id"])})
        return int(david["id"])
    raise RuntimeError("Import kräver en aktiv icke-admin-användare som importägare.")


def is_ready(path: Path) -> bool:
    if path.suffix == ".ready":
        return False
    ready_marker = path.with_name(f"{path.name}.ready")
    if ready_marker.exists():
        return True
    stat = path.stat()
    signature = (stat.st_size, int(stat.st_mtime))
    previous = _seen.get(path)
    _seen[path] = signature
    return previous == signature


def process_import_once() -> list[dict[str, object]]:
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for path in sorted(IMPORT_DIR.iterdir()):
        if not path.is_file() or not is_ready(path):
            continue
        results.append(process_import_file(path))
    return results


def process_import_file(path: Path) -> dict[str, object]:
    original_name = safe_filename(path.name.removesuffix(".ready"))
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    try:
        existing_id = existing_document_id_for_content(content)
        if existing_id:
            path.unlink(missing_ok=True)
            path.with_name(f"{path.name}.ready").unlink(missing_ok=True)
            db.record_import_event(original_name, "duplicate", "Dubblett hoppades över.", existing_id, digest)
            return {"filename": original_name, "status": "duplicate", "document_id": existing_id}
        template_id, tags = auto_classify(original_name, default_tags="import", source_tag="filimport")
        document_id = save_document_bytes(content, original_name, import_owner_user_id(), template_id, tags, mime_type=None)
    except Exception as exc:
        failed_path = IMPORT_FAILED_DIR / f"{digest[:16]}_{original_name}.enc"
        failed_path.write_bytes(crypto.encrypt_bytes(content))
        path.unlink(missing_ok=True)
        path.with_name(f"{path.name}.ready").unlink(missing_ok=True)
        status = "failed"
        message = "Import misslyckades."
        if isinstance(exc, HTTPException):
            message = str(exc.detail)
        db.record_import_event(original_name, status, message, None, digest)
        return {"filename": original_name, "status": status, "message": message}

    path.unlink(missing_ok=True)
    path.with_name(f"{path.name}.ready").unlink(missing_ok=True)
    db.record_import_event(original_name, "imported", "Importerad och krypterad.", document_id, digest)
    return {"filename": original_name, "status": "imported", "document_id": document_id}


async def import_loop(interval_seconds: int = 5) -> None:
    while True:
        try:
            process_import_once()
        except Exception:
            # Importfel per fil registreras ovan. Loopen ska inte dö på ett oväntat filsystemfel.
            pass
        await asyncio.sleep(interval_seconds)
