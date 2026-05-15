from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", "./data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DERIVED_DIR = DATA_DIR / "derived"
EXPORT_DIR = DATA_DIR / "exports"
LOG_DIR = DATA_DIR / "logs"
IMPORT_DIR = Path(os.getenv("IMPORT_DIR", "./import")).resolve()
IMPORT_FAILED_DIR = DATA_DIR / "import_failed"
KEYS_DIR = DATA_DIR / "keys"
INDEX_DIR = DATA_DIR / "indexes"
DB_PATH = DATA_DIR / "app.db"
FAIL2BAN_AUTH_LOG = Path(os.getenv("FAIL2BAN_AUTH_LOG", str(LOG_DIR / "fail2ban-auth.log"))).resolve()

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
SESSION_SECRET = os.getenv("SESSION_SECRET") or os.getenv("APP_SECRET_KEY") or "dev-change-me"
SECURE_COOKIES = os.getenv("SECURE_COOKIES", "false").lower() == "true"

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
    "docm",
    "dotx",
    "dotm",
    "xlsx",
    "xlsm",
    "xltx",
    "xltm",
    "pptx",
    "pptm",
    "potx",
    "potm",
    "ppsx",
    "ppsm",
    "doc",
    "xls",
    "ppt",
    "dot",
    "xlt",
    "pot",
    "odt",
    "ods",
    "odp",
    "ott",
    "ots",
    "otp",
    "fodt",
    "fods",
    "fodp",
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
    for path in (DATA_DIR, UPLOAD_DIR, DERIVED_DIR, EXPORT_DIR, IMPORT_DIR, IMPORT_FAILED_DIR, KEYS_DIR, INDEX_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
    try:
        IMPORT_DIR.chmod(0o777)
    except OSError:
        pass
