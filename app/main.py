from __future__ import annotations

import json
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import db
from .catalog import DOCUMENT_TEMPLATES, TEMPLATE_BY_ID
from .config import BASE_DIR, SESSION_SECRET
from .security import get_csrf_token, page_guard, redact_text, require_api_user, session_user, verify_csrf
from .services import ai, export, mail
from .services.documents import document_to_dict, get_document, save_upload, search_documents

app = FastAPI(title="dokumenteraren")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.on_event("startup")
def startup() -> None:
    db.init_db()


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
        }
    )
    return templates.TemplateResponse(template, context, status_code=status_code)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
@app.get("/documents", response_class=HTMLResponse)
def index(request: Request, q: str = "", template_id: str = "", status: str = "", tag: str = ""):
    guard = page_guard(request)
    if guard:
        return guard
    rows = search_documents(q=q, template_id=template_id, status=status, tag=tag)
    return render(
        request,
        "archive.html",
        {"documents": rows, "q": q, "template_id": template_id, "status": status, "tag": tag},
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
    file: UploadFile = File(...),
    template_id: str = Form(""),
    tags: str = Form(""),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    guard = page_guard(request)
    if guard:
        return guard
    user = session_user(request)
    document_id = await save_upload(file, user["id"], template_id, tags)
    return RedirectResponse(f"/documents/{document_id}", status_code=303)


@app.get("/documents/{document_id}", response_class=HTMLResponse)
def document_detail(request: Request, document_id: int):
    guard = page_guard(request)
    if guard:
        return guard
    row = get_document(document_id)
    if not row:
        raise HTTPException(status_code=404)
    metadata = json.loads(row["metadata_json"] or "{}")
    return render(request, "document_detail.html", {"document": row, "metadata": metadata})


@app.get("/documents/{document_id}/download")
def download_document(request: Request, document_id: int):
    guard = page_guard(request)
    if guard:
        return guard
    row = get_document(document_id)
    if not row:
        raise HTTPException(status_code=404)
    return FileResponse(row["storage_path"], filename=row["original_filename"], media_type=row["mime_type"])


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
def settings_page(request: Request, message: str = "", error: str = "", new_token: str = ""):
    guard = admin_guard(request)
    if guard:
        return guard
    settings = db.get_settings()
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
    return RedirectResponse(f"/settings?new_token={token}", status_code=303)


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
    path = export.create_zip(document_ids)
    return FileResponse(path, filename=path.name, media_type="application/zip")


@app.post("/export/mail")
def export_mail(request: Request, to_addr: str = Form(...), ids: str = Form(""), csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    guard = page_guard(request)
    if guard:
        return guard
    try:
        document_ids = [int(part) for part in ids.split(",") if part.strip().isdigit()]
        path = export.create_zip(document_ids)
        mail.send_mail(to_addr, "Export från dokumenteraren", "Bifogat finns vald export.", attachment=path)
    except Exception as exc:
        return RedirectResponse(f"/settings?error=Exportmail misslyckades: {exc.__class__.__name__}", status_code=303)
    return RedirectResponse("/settings?message=Export skickad via mail.", status_code=303)


@app.get("/api/v1/templates")
def api_templates(user=Depends(require_api_user)):
    return DOCUMENT_TEMPLATES


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
