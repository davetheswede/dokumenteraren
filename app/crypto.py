from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import KEYS_DIR, ensure_data_dirs


ENC_PREFIX = "enc:v1:"
MASTER_KEY_PATH = KEYS_DIR / "install.key"


class CryptoError(RuntimeError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("ascii"))


def _normalize_key(value: str) -> bytes:
    raw = value.strip()
    try:
        decoded = _unb64(raw)
        if len(decoded) in {16, 24, 32}:
            return decoded
    except Exception:
        pass
    if len(raw) >= 32:
        return raw.encode("utf-8")[:32].ljust(32, b"\0")
    raise CryptoError("APP_MASTER_KEY måste vara minst 32 tecken eller base64-kodad AES-nyckel.")


def master_key() -> bytes:
    env_key = os.getenv("APP_MASTER_KEY") or os.getenv("DOKUMENTERAREN_MASTER_KEY")
    if env_key:
        return _normalize_key(env_key)

    ensure_data_dirs()
    if MASTER_KEY_PATH.exists():
        return _unb64(MASTER_KEY_PATH.read_text(encoding="ascii").strip())

    key = AESGCM.generate_key(bit_length=256)
    MASTER_KEY_PATH.write_text(_b64(key), encoding="ascii")
    try:
        MASTER_KEY_PATH.chmod(0o600)
        KEYS_DIR.chmod(0o700)
    except OSError:
        pass
    return key


def random_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def encrypt_bytes(data: bytes, key: bytes | None = None, associated_data: bytes | None = None) -> bytes:
    key = key or master_key()
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, data, associated_data)
    return ENC_PREFIX.encode("ascii") + _b64(nonce + ciphertext).encode("ascii")


def decrypt_bytes(data: bytes, key: bytes | None = None, associated_data: bytes | None = None) -> bytes:
    if not data.startswith(ENC_PREFIX.encode("ascii")):
        return data
    key = key or master_key()
    payload = _unb64(data.decode("ascii")[len(ENC_PREFIX) :])
    nonce, ciphertext = payload[:12], payload[12:]
    return AESGCM(key).decrypt(nonce, ciphertext, associated_data)


def encrypt_text(text: str, key: bytes | None = None, associated_data: bytes | None = None) -> str:
    return encrypt_bytes(text.encode("utf-8"), key, associated_data).decode("ascii")


def decrypt_text(text: str, key: bytes | None = None, associated_data: bytes | None = None) -> str:
    if not text.startswith(ENC_PREFIX):
        return text
    return decrypt_bytes(text.encode("ascii"), key, associated_data).decode("utf-8")


def encrypt_file(src: Path, dst: Path, key: bytes | None = None) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(encrypt_bytes(src.read_bytes(), key))


def decrypt_file(path: Path, key: bytes | None = None) -> bytes:
    return decrypt_bytes(path.read_bytes(), key)


def is_encrypted_bytes(data: bytes) -> bool:
    return data.startswith(ENC_PREFIX.encode("ascii"))
