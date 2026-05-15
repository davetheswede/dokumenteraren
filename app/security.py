from __future__ import annotations

import re
import secrets
import ipaddress
from html import escape
from typing import Iterable

from fastapi import HTTPException, Request, status
from starlette.responses import RedirectResponse

from . import db
from .config import FAIL2BAN_AUTH_LOG


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


def actor_user(request: Request):
    admin_user_id = request.session.get("admin_user_id")
    if admin_user_id:
        return db.get_user(int(admin_user_id))
    return session_user(request)


def effective_user(request: Request):
    user = session_user(request)
    if not user:
        return None
    impersonated_user_id = request.session.get("impersonated_user_id")
    if user["role"] == "admin" and impersonated_user_id:
        impersonated = db.get_user(int(impersonated_user_id))
        if impersonated and impersonated["role"] != "admin" and impersonated["status"] == "active":
            return impersonated
    return user


def is_impersonating(request: Request) -> bool:
    user = session_user(request)
    return bool(user and user["role"] == "admin" and request.session.get("impersonated_user_id"))


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        candidate = forwarded.split(",", 1)[0].strip()
        if candidate:
            return candidate
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else ""


def geoip_lookup(ip: str, database_path: str = "") -> dict[str, str]:
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return {"geo_country": "", "geo_city": "", "geo_status": "ogiltig ip"}
    if parsed.is_private or parsed.is_loopback or parsed.is_link_local:
        return {"geo_country": "", "geo_city": "", "geo_status": "privat nät"}
    if database_path:
        try:
            import geoip2.database  # type: ignore

            with geoip2.database.Reader(database_path) as reader:
                response = reader.city(ip)
                return {
                    "geo_country": response.country.iso_code or "",
                    "geo_city": response.city.name or "",
                    "geo_status": "ok",
                }
        except Exception:
            return {"geo_country": "", "geo_city": "", "geo_status": "geoip misslyckades"}
    return {"geo_country": "", "geo_city": "", "geo_status": "okänd"}


def ip_allowed(ip: str, allowlist: str) -> bool:
    values = [part.strip() for part in allowlist.replace("\n", ",").split(",") if part.strip()]
    if not values:
        return False
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for value in values:
        try:
            if "/" in value:
                if parsed in ipaddress.ip_network(value, strict=False):
                    return True
            elif parsed == ipaddress.ip_address(value):
                return True
        except ValueError:
            continue
    return False


def write_fail2ban_login_failed(ip: str, username: str, path: str = "/login") -> None:
    safe_ip = re.sub(r"[^A-Fa-f0-9:.,_-]+", "_", (ip or "").strip())[:80] or "-"
    safe_username = re.sub(r"[^A-Za-z0-9_.@+-]+", "_", (username or "").strip())[:120] or "-"
    FAIL2BAN_AUTH_LOG.parent.mkdir(parents=True, exist_ok=True)
    with FAIL2BAN_AUTH_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"LOGIN_FAILED ip={safe_ip} username={safe_username} path={path}\n")


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
