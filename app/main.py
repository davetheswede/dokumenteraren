from __future__ import annotations

import asyncio
import json
import secrets
import time
from pathlib import Path
from threading import Lock

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import db
from .catalog import DOCUMENT_TEMPLATES, TEMPLATE_BY_ID
from .config import BASE_DIR, SECURE_COOKIES, SESSION_SECRET
from .security import get_csrf_token, page_guard, redact_text, require_api_user, session_user, verify_csrf
from .services import ai, export, importer, mail, mail_importer
from .services.documents import (
    delete_document,
    document_to_dict,
    get_document,
    read_original_bytes,
    save_upload,
    search_documents,
    update_document_classification,
    update_document_tags,
    verify_document_checksums,
)

app = FastAPI(title="dokumenteraren")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax", https_only=SECURE_COOKIES)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
API_TOKEN_FLASH_TTL_SECONDS = 300
_api_token_flash: dict[str, tuple[str, float]] = {}
_api_token_flash_lock = Lock()


def store_api_token_flash(token: str) -> str:
    now = time.monotonic()
    flash_id = secrets.token_urlsafe(16)
    with _api_token_flash_lock:
        expired = [flash_id for flash_id, (_, expires_at) in _api_token_flash.items() if expires_at <= now]
        for expired_id in expired:
            _api_token_flash.pop(expired_id, None)
        _api_token_flash[flash_id] = (token, now + API_TOKEN_FLASH_TTL_SECONDS)
    return flash_id


def pop_api_token_flash(flash_id: str) -> str:
    if not flash_id:
        return ""
    with _api_token_flash_lock:
        token, expires_at = _api_token_flash.pop(flash_id, ("", 0.0))
    if expires_at <= time.monotonic():
        return ""
    return token


def insecure_transport_warning(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.url.hostname or ""
    if forwarded_proto == "https" or host in {"localhost", "127.0.0.1", "::1"}:
        return ""
    return "Direkt HTTP utanför localhost upptäckt. Använd HTTPS/TLS-proxy för LAN-domänen innan känsliga dokument hanteras."


def insecure_transport_warning_header(request: Request) -> str:
    return "Direct HTTP outside localhost detected. Use HTTPS/TLS proxy for LAN document access." if insecure_transport_warning(request) else ""


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.headers.get("x-forwarded-proto", request.url.scheme) == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    warning = insecure_transport_warning_header(request)
    if warning:
        response.headers["X-Dokumenteraren-Transport-Warning"] = warning
    return response


@app.on_event("startup")
async def startup() -> None:
    db.init_db()
    importer.process_import_once()
    asyncio.create_task(importer.import_loop())
    asyncio.create_task(mail_importer.import_loop())


def render(request: Request, template: str, context: dict | None = None, status_code: int = 200) -> HTMLResponse:
    context = context or {}
    user = session_user(request)
    settings = db.get_settings()
    context.update(
        {
            "request": request,
            "user": user,
            "csrf_token": get_csrf_token(request),
            "templates_catalog": DOCUMENT_TEMPLATES,
            "template_by_id": TEMPLATE_BY_ID,
            "ai_status": ai.public_ai_status(settings),
            "smtp_configured": mail.smtp_configured(),
            "import_events": db.list_import_events(8),
            "transport_warning": insecure_transport_warning(request),
        }
    )
    return templates.TemplateResponse(template, context, status_code=status_code)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
@app.get("/documents", response_class=HTMLResponse)
def index(request: Request, q: str = "", template_id: str = "", status: str = "", tag: str = "", message: str = ""):
    guard = page_guard(request)
    if guard:
        return guard
    rows = search_documents(q=q, template_id=template_id, status=status, tag=tag)
    return render(
        request,
        "archive.html",
        {"documents": rows, "q": q, "template_id": template_id, "status": status, "tag": tag, "message": message},
    )


def admin_guard(request: Request):
    guard = page_guard(request)
    if guard:
        return guard
    user = session_user(request)
    if not user or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin krävs.")
    return None


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if session_user(request):
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html")


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    user = db.get_user_by_username(username.strip())
    if not user or not db.verify_password(password, user["password_hash"]):
        return render(request, "login.html", {"error": "Fel användarnamn eller lösenord."}, status_code=401)
    request.session["user_id"] = user["id"]
    return RedirectResponse("/change-password" if user["must_change_password"] else "/", status_code=303)


@app.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/change-password", response_class=HTMLResponse)
def change_password_page(request: Request):
    guard = page_guard(request, allow_password_change=True)
    if guard:
        return guard
    return render(request, "change_password.html")


@app.post("/change-password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    guard = page_guard(request, allow_password_change=True)
    if guard:
        return guard
    user = session_user(request)
    if not db.verify_password(current_password, user["password_hash"]):
        return render(request, "change_password.html", {"error": "Nuvarande lösenord stämmer inte."}, status_code=400)
    if len(new_password) < 8:
        return render(request, "change_password.html", {"error": "Nytt lösenord behöver vara minst 8 tecken."}, status_code=400)
    if new_password != confirm_password:
        return render(request, "change_password.html", {"error": "Lösenorden matchar inte."}, status_code=400)
    db.update_password(user["id"], new_password)
    return RedirectResponse("/", status_code=303)


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    guard = page_guard(request)
    if guard:
        return guard
    return render(request, "upload.html")


@app.post("/upload")
async def upload_document(
    request: Request,
):
    form = await request.form()
    csrf_token = str(form.get("csrf_token") or "")
    verify_csrf(request, csrf_token)
    guard = page_guard(request)
    if guard:
        return guard
    user = session_user(request)
    uploads = [
        item
        for item in [*form.getlist("files"), *form.getlist("file")]
        if hasattr(item, "filename") and hasattr(item, "read") and getattr(item, "filename", "")
    ]
    template_ids = [str(value) for value in form.getlist("template_id")]
    tags = str(form.get("tags") or "")

    if not uploads:
        return render(request, "upload.html", {"error": "Välj minst en fil."}, status_code=400)

    document_ids: list[int] = []
    for index, upload in enumerate(uploads):
        template_id = template_ids[index] if index < len(template_ids) else (template_ids[0] if template_ids else "")
        document_ids.append(await save_upload(upload, user["id"], template_id, tags))

    if len(document_ids) == 1:
        return RedirectResponse(f"/documents/{document_ids[0]}", status_code=303)
    return RedirectResponse(f"/?message={len(document_ids)} dokument arkiverades.", status_code=303)


@app.get("/documents/{document_id}", response_class=HTMLResponse)
def document_detail(request: Request, document_id: int, message: str = ""):
    guard = page_guard(request)
    if guard:
        return guard
    row = get_document(document_id)
    if not row:
        raise HTTPException(status_code=404)
    metadata = json.loads(row["metadata_json"] or "{}")
    messages = {"tags-updated": "Taggar uppdaterade.", "classification-updated": "Mall och taggar uppdaterade."}
    return render(
        request,
        "document_detail.html",
        {"document": row, "metadata": metadata, "checksum_status": verify_document_checksums(row), "message": messages.get(message, "")},
    )


@app.post("/documents/{document_id}/classification")
def document_classification_update(
    request: Request,
    document_id: int,
    template_id: str = Form(""),
    tags: str = Form(""),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    guard = page_guard(request)
    if guard:
        return guard
    if template_id and template_id not in TEMPLATE_BY_ID:
        raise HTTPException(status_code=400, detail="Okänd dokumentmall.")
    if not update_document_classification(document_id, template_id, tags):
        raise HTTPException(status_code=404)
    return RedirectResponse(f"/documents/{document_id}?message=classification-updated", status_code=303)


@app.post("/documents/{document_id}/tags")
def document_tags_update(request: Request, document_id: int, tags: str = Form(""), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    guard = page_guard(request)
    if guard:
        return guard
    if not update_document_tags(document_id, tags):
        raise HTTPException(status_code=404)
    return RedirectResponse(f"/documents/{document_id}?message=tags-updated", status_code=303)


@app.post("/documents/{document_id}/delete")
def document_delete(request: Request, document_id: int, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    guard = page_guard(request)
    if guard:
        return guard
    if not delete_document(document_id):
        raise HTTPException(status_code=404)
    return RedirectResponse("/?message=Dokumentet raderades.", status_code=303)


@app.get("/documents/{document_id}/download")
def download_document(request: Request, document_id: int):
    guard = page_guard(request)
    if guard:
        return guard
    row = get_document(document_id)
    if not row:
        raise HTTPException(status_code=404)
    return Response(
        read_original_bytes(row),
        media_type=row["mime_type"],
        headers={"Content-Disposition": f'attachment; filename="{row["original_filename"]}"'},
    )


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    guard = page_guard(request)
    if guard:
        return guard
    rows = search_documents()
    return render(request, "chat.html", {"documents": rows, "answer": None, "used_context": None})


@app.post("/chat", response_class=HTMLResponse)
async def chat_ask(
    request: Request,
    question: str = Form(...),
    document_ids: list[int] = Form(default=[]),
    redact: str | None = Form(default="on"),
    custom_redactions: str = Form(""),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    guard = page_guard(request)
    if guard:
        return guard
    rows = [row for row in (get_document(doc_id) for doc_id in document_ids) if row]
    if not rows:
        return render(request, "chat.html", {"documents": search_documents(), "error": "Välj minst ett dokument."}, status_code=400)
    parts = []
    for row in rows:
        text = (row["extracted_text"] or "")[:6000]
        if redact:
            terms = [term for term in custom_redactions.splitlines() if term.strip()]
            text = redact_text(text, terms)
        parts.append(f"## {row['title']} ({row['original_filename']})\n{text}")
    context = "\n\n".join(parts)[:24000]
    try:
        answer = await ai.ask_ai(question, context)
    except ai.AIConfigurationError as exc:
        return render(
            request,
            "chat.html",
            {"documents": search_documents(), "error": str(exc), "used_context": context, "question": question},
            status_code=400,
        )
    except Exception as exc:
        return render(
            request,
            "chat.html",
            {"documents": search_documents(), "error": f"AI-anropet misslyckades: {exc.__class__.__name__}", "used_context": context},
            status_code=502,
        )
    return render(
        request,
        "chat.html",
        {"documents": search_documents(), "answer": answer, "used_context": context, "question": question},
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, message: str = "", error: str = "", token_created: str = ""):
    guard = admin_guard(request)
    if guard:
        return guard
    settings = db.get_settings()
    new_token = pop_api_token_flash(token_created)
    return render(
        request,
        "settings.html",
        {
            "settings": settings,
            "api_tokens": db.list_api_tokens(session_user(request)["id"]),
            "message": message,
            "error": error,
            "new_token": new_token,
        },
    )


@app.post("/settings/ai")
def save_ai_settings(
    request: Request,
    ai_provider: str = Form(...),
    ai_openai_api_key: str = Form(""),
    ai_openai_model: str = Form(""),
    ai_openai_base_url: str = Form(""),
    ai_claude_api_key: str = Form(""),
    ai_claude_model: str = Form(""),
    ai_ollama_base_url: str = Form(""),
    ai_ollama_model: str = Form(""),
    ai_timeout_seconds: str = Form("30"),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    guard = admin_guard(request)
    if guard:
        return guard
    if ai_provider not in {"disabled", "openai", "claude", "ollama"}:
        raise HTTPException(status_code=400, detail="Ogiltig provider.")
    current = db.get_settings()
    values = {
        "ai_provider": ai_provider,
        "ai_enabled": "false",
        "ai_last_test_ok": "false",
        "ai_openai_model": ai_openai_model or current.get("ai_openai_model", "gpt-4o-mini"),
        "ai_openai_base_url": ai_openai_base_url or current.get("ai_openai_base_url", "https://api.openai.com/v1"),
        "ai_claude_model": ai_claude_model or current.get("ai_claude_model", "claude-3-5-haiku-latest"),
        "ai_ollama_base_url": ai_ollama_base_url or current.get("ai_ollama_base_url", "http://host.docker.internal:11434"),
        "ai_ollama_model": ai_ollama_model or current.get("ai_ollama_model", "llama3.1"),
        "ai_timeout_seconds": ai_timeout_seconds or "30",
    }
    if ai_openai_api_key:
        values["ai_openai_api_key"] = ai_openai_api_key
    if ai_claude_api_key:
        values["ai_claude_api_key"] = ai_claude_api_key
    db.set_settings(values)
    return RedirectResponse("/settings?message=AI-inställningar sparade. Kör test innan providern aktiveras.", status_code=303)


@app.post("/settings/ai/test")
async def test_ai_settings(request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    guard = admin_guard(request)
    if guard:
        return guard
    ok, message = await ai.test_provider()
    if ok:
        return RedirectResponse(f"/settings?message={message}", status_code=303)
    return RedirectResponse(f"/settings?error={message}", status_code=303)


@app.post("/settings/api-token")
def create_token(request: Request, token_name: str = Form("LAN API"), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    guard = admin_guard(request)
    if guard:
        return guard
    token = db.create_api_token(session_user(request)["id"], token_name)
    flash_id = store_api_token_flash(token)
    return RedirectResponse(f"/settings?token_created={flash_id}", status_code=303)


@app.post("/settings/mail-import")
def save_mail_import_settings(
    request: Request,
    mail_import_enabled: str | None = Form(default=None),
    mail_import_protocol: str = Form("pop3"),
    mail_import_host: str = Form(""),
    mail_import_port: str = Form(""),
    mail_import_ssl: str | None = Form(default=None),
    mail_import_username: str = Form(""),
    mail_import_password: str = Form(""),
    mail_import_folder: str = Form("INBOX"),
    mail_import_delete_after_handled: str | None = Form(default=None),
    mail_import_poll_interval_seconds: str = Form("300"),
    mail_import_max_messages: str = Form("10"),
    mail_import_min_inline_image_bytes: str = Form("10240"),
    mail_import_import_eml_without_attachments: str | None = Form(default=None),
    mail_import_default_tags: str = Form("mailimport"),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    guard = admin_guard(request)
    if guard:
        return guard
    if mail_import_protocol not in {"pop3", "imap"}:
        raise HTTPException(status_code=400, detail="Ogiltigt mailprotokoll.")
    current = db.get_settings()
    values = {
        "mail_import_enabled": "true" if mail_import_enabled else "false",
        "mail_import_protocol": mail_import_protocol,
        "mail_import_host": mail_import_host.strip(),
        "mail_import_port": mail_import_port.strip() or ("993" if mail_import_protocol == "imap" else "995"),
        "mail_import_ssl": "true" if mail_import_ssl else "false",
        "mail_import_username": mail_import_username.strip(),
        "mail_import_folder": mail_import_folder.strip() or "INBOX",
        "mail_import_delete_after_handled": "true" if mail_import_delete_after_handled else "false",
        "mail_import_poll_interval_seconds": mail_import_poll_interval_seconds.strip() or "300",
        "mail_import_max_messages": mail_import_max_messages.strip() or "10",
        "mail_import_min_inline_image_bytes": mail_import_min_inline_image_bytes.strip() or "10240",
        "mail_import_import_eml_without_attachments": "true" if mail_import_import_eml_without_attachments else "false",
        "mail_import_default_tags": mail_import_default_tags.strip() or "mailimport",
    }
    if mail_import_password:
        values["mail_import_password"] = mail_import_password
    elif current.get("mail_import_password"):
        values["mail_import_password"] = current["mail_import_password"]
    db.set_settings(values)
    return RedirectResponse("/settings?message=Mailimport sparad.", status_code=303)


@app.post("/settings/mail-import/test")
def test_mail_import_settings(request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    guard = admin_guard(request)
    if guard:
        return guard
    try:
        ok, message = mail_importer.test_connection()
    except Exception as exc:
        return RedirectResponse(f"/settings?error=Mailimport test misslyckades: {exc.__class__.__name__}", status_code=303)
    return RedirectResponse(f"/settings?{'message' if ok else 'error'}={message}", status_code=303)


@app.post("/settings/mail-import/poll")
def poll_mail_import(request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    guard = admin_guard(request)
    if guard:
        return guard
    try:
        results = mail_importer.process_mail_import_once(force=True)
    except Exception as exc:
        return RedirectResponse(f"/settings?error=Mailimport misslyckades: {exc.__class__.__name__}", status_code=303)
    return RedirectResponse(f"/settings?message=Mailimport körd: {len(results)} importhändelser.", status_code=303)


@app.post("/settings/test-mail")
def test_mail(request: Request, to_addr: str = Form(...), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    guard = admin_guard(request)
    if guard:
        return guard
    try:
        mail.send_mail(to_addr, "dokumenteraren testmail", "SMTP2GO är konfigurerat för dokumenteraren.")
    except Exception as exc:
        return RedirectResponse(f"/settings?error=Mail misslyckades: {exc.__class__.__name__}", status_code=303)
    return RedirectResponse("/settings?message=Testmail skickat.", status_code=303)


@app.get("/export/metadata.json")
def export_json(request: Request):
    guard = page_guard(request)
    if guard:
        return guard
    return JSONResponse([document_to_dict(row) for row in search_documents()])


@app.get("/export/metadata.csv")
def export_csv(request: Request):
    guard = page_guard(request)
    if guard:
        return guard
    return PlainTextResponse(export.export_metadata_csv(search_documents()), media_type="text/csv")


@app.get("/export/zip")
def export_zip(request: Request, ids: str = ""):
    guard = page_guard(request)
    if guard:
        return guard
    document_ids = [int(part) for part in ids.split(",") if part.strip().isdigit()]
    export.create_zip(document_ids)
    return Response(
        export.create_zip_bytes(document_ids),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="dokumenteraren_export.zip"'},
    )


@app.post("/export/mail")
def export_mail(request: Request, to_addr: str = Form(...), ids: str = Form(""), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    guard = page_guard(request)
    if guard:
        return guard
    try:
        document_ids = [int(part) for part in ids.split(",") if part.strip().isdigit()]
        export.create_zip(document_ids)
        mail.send_mail(
            to_addr,
            "Export från dokumenteraren",
            "Bifogat finns vald export.",
            attachment_bytes=export.create_zip_bytes(document_ids),
        )
    except Exception as exc:
        return RedirectResponse(f"/settings?error=Exportmail misslyckades: {exc.__class__.__name__}", status_code=303)
    return RedirectResponse("/settings?message=Export skickad via mail.", status_code=303)


@app.get("/api/v1/templates")
def api_templates(user=Depends(require_api_user)):
    return DOCUMENT_TEMPLATES


@app.get("/api/v1/imports")
def api_imports(user=Depends(require_api_user)):
    return [dict(row) for row in db.list_import_events()]


@app.get("/api/v1/documents")
def api_documents(user=Depends(require_api_user), q: str = "", template_id: str = "", status: str = "", tag: str = ""):
    return [document_to_dict(row) for row in search_documents(q=q, template_id=template_id, status=status, tag=tag)]


@app.post("/api/v1/documents")
async def api_upload_document(
    user=Depends(require_api_user),
    file: UploadFile = File(...),
    template_id: str = Form(""),
    tags: str = Form(""),
):
    document_id = await save_upload(file, user["id"], template_id, tags)
    row = get_document(document_id)
    return document_to_dict(row)
