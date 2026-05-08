from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from passlib.context import CryptContext

from . import crypto
from .config import DB_PATH, ensure_data_dirs

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    ensure_data_dirs()
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                must_change_password INTEGER NOT NULL DEFAULT 0,
                user_key_wrapped TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS api_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                last_used_at TEXT
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                text_path TEXT,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                mime_type TEXT NOT NULL,
                extension TEXT NOT NULL,
                template_id TEXT,
                tags TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                extracted_text TEXT NOT NULL DEFAULT '',
                extraction_status TEXT NOT NULL,
                uploaded_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS document_keys (
                document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
                owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                wrapped_key TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS import_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL,
                document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
                sha256 TEXT,
                created_at TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                title,
                tags,
                metadata,
                content,
                content='',
                tokenize='unicode61 remove_diacritics 2'
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        migrate_schema(conn)
        seed_admin(conn)
        seed_settings(conn)
        migrate_plaintext_documents(conn)


def migrate_schema(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "user_key_wrapped" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN user_key_wrapped TEXT")
    for user in conn.execute("SELECT id FROM users WHERE user_key_wrapped IS NULL OR user_key_wrapped = ''").fetchall():
        conn.execute(
            "UPDATE users SET user_key_wrapped = ? WHERE id = ?",
            (wrap_key(crypto.random_key()), user["id"]),
        )


def migrate_plaintext_documents(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT d.* FROM documents d
        LEFT JOIN document_keys k ON k.document_id = d.id
        WHERE k.document_id IS NULL
        """
    ).fetchall()
    if not rows:
        return
    for row in rows:
        document_key = crypto.random_key()
        storage_path = Path(row["storage_path"])
        if storage_path.exists() and not storage_path.read_bytes().startswith(crypto.ENC_PREFIX.encode("ascii")):
            encrypted_path = storage_path.with_name(storage_path.name + ".enc")
            encrypted_path.write_bytes(crypto.encrypt_bytes(storage_path.read_bytes(), document_key))
            storage_path.unlink(missing_ok=True)
            storage_path = encrypted_path

        text_path = Path(row["text_path"]) if row["text_path"] else None
        extracted_text = row["extracted_text"] or ""
        if text_path and text_path.exists() and not text_path.read_bytes().startswith(crypto.ENC_PREFIX.encode("ascii")):
            if not extracted_text:
                extracted_text = text_path.read_text(encoding="utf-8", errors="replace")
            encrypted_text_path = text_path.with_name(text_path.name + ".enc")
            encrypted_text_path.write_bytes(crypto.encrypt_bytes(extracted_text.encode("utf-8"), document_key))
            text_path.unlink(missing_ok=True)
            text_path = encrypted_text_path

        metadata_json = row["metadata_json"] or "{}"
        try:
            json.loads(metadata_json)
        except json.JSONDecodeError:
            metadata_json = "{}"

        conn.execute(
            """
            UPDATE documents
            SET storage_path = ?, text_path = ?, metadata_json = ?, extracted_text = ?
            WHERE id = ?
            """,
            (
                str(storage_path),
                str(text_path) if text_path else "",
                crypto.encrypt_text(metadata_json, document_key),
                crypto.encrypt_text(extracted_text, document_key),
                row["id"],
            ),
        )
        set_document_key(conn, row["id"], row["uploaded_by"], document_key)
    conn.execute("DELETE FROM documents_fts")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.commit()
    conn.execute("VACUUM")


def seed_admin(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT id, user_key_wrapped FROM users WHERE username = ?", ("admin",)).fetchone()
    if existing:
        if not existing["user_key_wrapped"]:
            conn.execute(
                "UPDATE users SET user_key_wrapped = ? WHERE id = ?",
                (wrap_key(crypto.random_key()), existing["id"]),
            )
        return
    conn.execute(
        """
        INSERT INTO users (username, password_hash, role, must_change_password, user_key_wrapped, created_at)
        VALUES (?, ?, 'admin', 1, ?, ?)
        """,
        ("admin", pwd_context.hash("12345"), wrap_key(crypto.random_key()), utc_now()),
    )


def seed_settings(conn: sqlite3.Connection) -> None:
    defaults = {
        "ai_provider": "disabled",
        "ai_enabled": "false",
        "ai_last_test_ok": "false",
        "ai_openai_model": "gpt-4o-mini",
        "ai_openai_base_url": "https://api.openai.com/v1",
        "ai_claude_model": "claude-3-5-haiku-latest",
        "ai_ollama_base_url": "http://host.docker.internal:11434",
        "ai_ollama_model": "llama3.1",
        "ai_timeout_seconds": "30",
    }
    for key, value in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, utc_now()),
        )


def get_user_by_username(username: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_user(user_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def update_password(user_id: int, password: str) -> None:
    with connect() as conn:
        row = conn.execute("SELECT user_key_wrapped FROM users WHERE id = ?", (user_id,)).fetchone()
        wrapped_key = row["user_key_wrapped"] if row and row["user_key_wrapped"] else wrap_key(crypto.random_key())
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0, user_key_wrapped = ? WHERE id = ?",
            (pwd_context.hash(password), wrapped_key, user_id),
        )


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_api_token(user_id: int, name: str) -> str:
    token = f"dk_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO api_tokens (user_id, name, token_hash, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, name.strip() or "LAN API", token_hash, utc_now()),
        )
    return token


def authenticate_token(token: str) -> sqlite3.Row | None:
    if not token or not token.startswith("dk_"):
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT users.* FROM api_tokens
            JOIN users ON users.id = api_tokens.user_id
            WHERE api_tokens.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE api_tokens SET last_used_at = ? WHERE token_hash = ?",
                (utc_now(), token_hash),
            )
        return row


def list_api_tokens(user_id: int) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT id, name, created_at, last_used_at FROM api_tokens WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()


def get_settings() -> dict[str, str]:
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


def set_settings(values: dict[str, Any]) -> None:
    with connect() as conn:
        for key, value in values.items():
            conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, "" if value is None else str(value), utc_now()),
            )


def upsert_document_fts(conn: sqlite3.Connection, rowid: int, title: str, tags: str, metadata: str, content: str) -> None:
    conn.execute("DELETE FROM documents_fts WHERE rowid = ?", (rowid,))
    # Store only non-sensitive routing fields in FTS. Body search decrypts in the service layer.
    conn.execute(
        "INSERT INTO documents_fts (rowid, title, tags, metadata, content) VALUES (?, ?, ?, ?, ?)",
        (rowid, title, tags or "", "", ""),
    )


def db_path_for_display() -> str:
    return str(Path(DB_PATH))


def wrap_key(key: bytes) -> str:
    return crypto.encrypt_bytes(key).decode("ascii")


def unwrap_key(wrapped_key: str) -> bytes:
    return crypto.decrypt_bytes(wrapped_key.encode("ascii"))


def set_document_key(conn: sqlite3.Connection, document_id: int, owner_user_id: int, key: bytes) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO document_keys (document_id, owner_user_id, wrapped_key, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (document_id, owner_user_id, wrap_key(key), utc_now()),
    )


def get_document_key(document_id: int) -> bytes | None:
    with connect() as conn:
        row = conn.execute("SELECT wrapped_key FROM document_keys WHERE document_id = ?", (document_id,)).fetchone()
    if not row:
        return None
    return unwrap_key(row["wrapped_key"])


def record_import_event(filename: str, status: str, message: str, document_id: int | None = None, sha256: str | None = None) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO import_events (filename, status, message, document_id, sha256, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (filename, status, message, document_id, sha256, utc_now()),
        )


def list_import_events(limit: int = 25) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM import_events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
