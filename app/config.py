from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", "./data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DERIVED_DIR = DATA_DIR / "derived"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "app.db"

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
SESSION_SECRET = os.getenv("SESSION_SECRET") or os.getenv("APP_SECRET_KEY") or "dev-change-me"

ALLOWED_EXTENSIONS = {
    "txt",
    "md",
    "rtf",
    "csv",
    "tsv",
    "json",
    "xml",
    "yaml",
    "yml",
    "ini",
    "conf",
    "log",
    "pdf",
    "docx",
    "xlsx",
    "pptx",
    "doc",
    "xls",
    "ppt",
    "odt",
    "ods",
    "odp",
    "ott",
    "ots",
    "otp",
    "jpg",
    "jpeg",
    "png",
    "webp",
    "tif",
    "tiff",
    "bmp",
    "gif",
    "heic",
    "eml",
    "html",
    "htm",
}


def ensure_data_dirs() -> None:
    for path in (DATA_DIR, UPLOAD_DIR, DERIVED_DIR, EXPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)
