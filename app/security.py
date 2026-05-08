from __future__ import annotations

import re
import secrets
from html import escape
from typing import Iterable

from fastapi import HTTPException, Request, status
from starlette.responses import RedirectResponse

from . import db


SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(filename: str) -> str:
    clean = filename.split("/")[-1].split("\\")[-1].strip().replace(" ", "_")
    clean = SAFE_NAME_RE.sub("_", clean)
    return clean[:180] or "document"


def get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def verify_csrf(request: Request, token: str | None) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not token or not secrets.compare_digest(expected, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ogiltig CSRF-token.")


def session_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get_user(int(user_id))


def page_guard(request: Request, allow_password_change: bool = False):
    user = session_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user["must_change_password"] and not allow_password_change:
        return RedirectResponse("/change-password", status_code=303)
    return None


def require_api_user(request: Request):
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer-token krävs.")
    user = db.authenticate_token(token.strip())
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ogiltig API-token.")
    return user


def redact_text(text: str, custom_terms: Iterable[str] = ()) -> str:
    patterns = [
        (r"\b\d{6}[-+]\d{4}\b", "[MASKAT_PERSONNUMMER]"),
        (r"\b\d{8}[-+]\d{4}\b", "[MASKAT_PERSONNUMMER]"),
        (r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[MASKAD_EPOST]"),
        (r"\b(?:\+?\d[\d\s().-]{7,}\d)\b", "[MASKAT_TELEFON]"),
        (r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", "[MASKAT_KONTO]"),
        (r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{0,4}\b", "[MASKAT_KONTO]"),
    ]
    redacted = text
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted, flags=re.IGNORECASE)
    for term in custom_terms:
        term = term.strip()
        if term:
            redacted = re.sub(re.escape(term), "[MASKAT_EGET_ORD]", redacted, flags=re.IGNORECASE)
    return redacted


def html_escape(value: object) -> str:
    return escape(str(value), quote=True)
