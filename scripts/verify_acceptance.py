from __future__ import annotations

import html
import io
import json
import os
import posixpath
import re
import sys
import tempfile
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def configure_isolated_runtime() -> tempfile.TemporaryDirectory[str]:
    data_dir = tempfile.TemporaryDirectory(prefix="dokumenteraren-acceptance-")
    os.environ["DATA_DIR"] = data_dir.name
    os.environ["SESSION_SECRET"] = "acceptance-test-secret"
    os.environ["MAX_UPLOAD_BYTES"] = str(1_000_000)
    return data_dir


runtime_dir = configure_isolated_runtime()

from docx import Document as DocxDocument  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from odf.opendocument import OpenDocumentSpreadsheet, OpenDocumentText  # noqa: E402
from odf.table import Table, TableCell, TableRow  # noqa: E402
from odf.text import P  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from PIL import Image  # noqa: E402
from pptx import Presentation  # noqa: E402

from app import db  # noqa: E402
from app.crypto import ENC_PREFIX  # noqa: E402
from app.main import app  # noqa: E402
from app.security import redact_text  # noqa: E402
from app.services import importer  # noqa: E402
from app.services.export import safe_zip_member  # noqa: E402


CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def csrf(response) -> str:
    match = CSRF_RE.search(response.text)
    assert match, "CSRF-token saknas i formulär."
    return html.unescape(match.group(1))


def make_pdf(text: str) -> bytes:
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{index} 0 obj\n".encode("ascii"))
        output.write(obj)
        output.write(b"\nendobj\n")
    xref = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets:
        output.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.write(
        f"trailer << /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return output.getvalue()


def make_docx(text: str) -> bytes:
    buffer = io.BytesIO()
    doc = DocxDocument()
    doc.add_paragraph(text)
    doc.save(buffer)
    return buffer.getvalue()


def make_xlsx(text: str) -> bytes:
    buffer = io.BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Verifiering"
    sheet.append(["typ", "innehåll"])
    sheet.append(["xlsx", text])
    workbook.save(buffer)
    return buffer.getvalue()


def make_pptx(text: str) -> bytes:
    buffer = io.BytesIO()
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    text_box = slide.shapes.add_textbox(0, 0, 5_000_000, 1_000_000)
    text_box.text = text
    presentation.save(buffer)
    return buffer.getvalue()


def make_odt(text: str) -> bytes:
    buffer = io.BytesIO()
    doc = OpenDocumentText()
    doc.text.addElement(P(text=text))
    doc.save(buffer)
    return buffer.getvalue()


def make_ods(text: str) -> bytes:
    buffer = io.BytesIO()
    doc = OpenDocumentSpreadsheet()
    table = Table(name="Verifiering")
    row = TableRow()
    cell = TableCell()
    cell.addElement(P(text=text))
    row.addElement(cell)
    table.addElement(row)
    doc.spreadsheet.addElement(table)
    doc.save(buffer)
    return buffer.getvalue()


def make_flat_odf(text: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  office:mimetype="application/vnd.oasis.opendocument.text">
  <office:body><office:text><text:p>{text}</text:p></office:text></office:body>
</office:document>
""".encode("utf-8")


def make_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (24, 16), color=(80, 120, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


SAMPLES: list[tuple[str, bytes, str, bool]] = [
    ("text-token.txt", b"uniktext alfa person 19800101-1234\n", "uniktext", True),
    ("markdown-token.md", b"# Rubrik\nunikmarkdown beta\n", "unikmarkdown", True),
    ("forsakring.pdf", make_pdf("unikpdf krock villkor"), "unikpdf", True),
    ("word.docx", make_docx("unikdocx avtal"), "unikdocx", True),
    ("macro-word.docm", make_docx("unikdocm avtal"), "unikdocm", True),
    ("sheet.xlsx", make_xlsx("unikxlsx kvitto"), "unikxlsx", True),
    ("macro-sheet.xlsm", make_xlsx("unikxlsm kvitto"), "unikxlsm", True),
    ("presentation.pptx", make_pptx("unikpptx villkor"), "unikpptx", True),
    ("open.odt", make_odt("unikodt journal"), "unikodt", True),
    ("open.ods", make_ods("unikods kalkyl"), "unikods", True),
    ("flat.fodt", make_flat_odf("unikfodt anteckning"), "unikfodt", True),
    ("rich.rtf", b"{\\rtf1\\ansi unikrtf garanti}", "unikrtf", True),
    ("data.csv", b"kolumn\nunikcsv\n", "unikcsv", True),
    ("data.json", b'{"nyckel":"unikjson"}', "unikjson", True),
    ("data.yaml", b"nyckel: unikyaml\n", "unikyaml", True),
    ("mail.eml", b"Subject: Test\nFrom: a@example.test\nTo: b@example.test\n\nunikeml meddelande", "unikeml", True),
    ("photo.png", make_png(), "width", False),
]


def assert_zip_member_safe(name: str) -> None:
    assert not name.startswith(("/", "\\")), f"ZIP-namn är absolut: {name}"
    assert "\\" not in name, f"ZIP-namn innehåller backslash: {name}"
    assert ":" not in name.split("/", 1)[0], f"ZIP-namn innehåller drive/prefix: {name}"
    normalized = posixpath.normpath(name)
    assert normalized == name, f"ZIP-namn normaliserar bort segment: {name}"
    assert ".." not in Path(name).parts, f"ZIP-namn innehåller parentsegment: {name}"


def assert_data_dir_has_no_plaintext(tokens: list[bytes]) -> None:
    data_root = Path(runtime_dir.name)
    for path in data_root.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        for token in tokens:
            assert token not in data, f"{token!r} finns i klartext på disk i {path}"


def main() -> None:
    try:
        db.init_db()
        with TestClient(app) as client:
            unauthenticated = client.get("/export/zip", follow_redirects=False)
            assert unauthenticated.status_code == 303 and unauthenticated.headers["location"] == "/login"
            api_unauthenticated = client.get("/api/v1/documents")
            assert api_unauthenticated.status_code == 401

            login_page = client.get("/login")
            login = client.post(
                "/login",
                data={"username": "admin", "password": "12345", "csrf_token": csrf(login_page)},
                follow_redirects=False,
            )
            assert login.status_code == 303 and login.headers["location"] == "/change-password"
            blocked = client.get("/", follow_redirects=False)
            assert blocked.status_code == 303 and blocked.headers["location"] == "/change-password"

            change_page = client.get("/change-password")
            changed = client.post(
                "/change-password",
                data={
                    "current_password": "12345",
                    "new_password": "acceptance-12345",
                    "confirm_password": "acceptance-12345",
                    "csrf_token": csrf(change_page),
                },
                follow_redirects=False,
            )
            assert changed.status_code == 303 and changed.headers["location"] == "/"

            token = db.create_api_token(1, "acceptance")
            uploaded_ids: list[int] = []
            for filename, content, token_word, must_index in SAMPLES:
                response = client.post(
                    "/api/v1/documents",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": (filename, content)},
                    data={"template_id": "receipt", "tags": "acceptance,import"},
                )
                assert response.status_code == 200, f"{filename}: {response.text}"
                payload = response.json()
                uploaded_ids.append(payload["id"])
                assert Path(payload["original_filename"]).name == payload["original_filename"]
                assert (Path(runtime_dir.name) / "uploads").exists()
                if must_index:
                    assert payload["extraction_status"] == "indexed", f"{filename} indexerades inte."
                    search = client.get(
                        "/api/v1/documents",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"q": token_word},
                    )
                    assert search.status_code == 200
                    assert any(row["id"] == payload["id"] for row in search.json()), f"{filename} saknas i sök."
                else:
                    assert payload["extraction_status"] in {"indexed", "archived_only"}
                    assert "width" in payload["metadata"] and "height" in payload["metadata"]

            traversal = client.post(
                "/api/v1/documents",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": ("../../hemligt\\konto.txt", b"uniktraversal 070-123 45 67 konto\n")},
            )
            assert traversal.status_code == 200
            traversal_payload = traversal.json()
            uploaded_ids.append(traversal_payload["id"])
            assert traversal_payload["original_filename"] == "konto.txt"

            forbidden = client.post(
                "/api/v1/documents",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": ("malware.exe", b"nej")},
            )
            assert forbidden.status_code == 400

            too_large = client.post(
                "/api/v1/documents",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": ("large.txt", b"x" * 1_000_001)},
            )
            assert too_large.status_code == 413

            chat_page = client.get("/chat")
            chat = client.post(
                "/chat",
                data={
                    "csrf_token": csrf(chat_page),
                    "question": "Vad står i dokumentet?",
                    "document_ids": str(uploaded_ids[0]),
                    "redact": "on",
                },
            )
            assert chat.status_code == 400
            assert "AI är inte aktiverat" in chat.text
            assert "19800101-1234" not in chat.text
            assert "[MASKAT_PERSONNUMMER]" in chat.text
            assert redact_text("me@example.test +46 70 123 45 67 SE4550000000058398257466").count("[MASK") >= 3

            metadata_json = client.get("/export/metadata.json")
            assert metadata_json.status_code == 200
            assert len(metadata_json.json()) >= len(uploaded_ids)
            metadata_csv = client.get("/export/metadata.csv")
            assert metadata_csv.status_code == 200 and "original_filename" in metadata_csv.text

            exported = client.get("/export/zip", params={"ids": ",".join(map(str, uploaded_ids))})
            assert exported.status_code == 200
            with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                names = archive.namelist()
                assert "manifest.json" in names
                assert any(name.startswith("original/") and name.endswith("konto.txt") for name in names)
                for name in names:
                    assert_zip_member_safe(name)
                manifest = json.loads(archive.read("manifest.json"))
                assert any(item["original_filename"] == "konto.txt" for item in manifest)

            assert safe_zip_member("original", "../../..\\CON.txt", 99) == "original/99_CON.txt"

            settings_page = client.get("/settings")
            assert settings_page.status_code == 200
            assert "Disabled" in settings_page.text
            provider_forms = [
                {
                    "ai_provider": "openai",
                    "ai_openai_api_key": "sk-acceptance-secret",
                    "ai_openai_model": "gpt-test",
                    "ai_openai_base_url": "http://127.0.0.1:9/v1",
                },
                {
                    "ai_provider": "claude",
                    "ai_claude_api_key": "claude-acceptance-secret",
                    "ai_claude_model": "claude-test",
                },
                {
                    "ai_provider": "ollama",
                    "ai_ollama_base_url": "http://127.0.0.1:11434",
                    "ai_ollama_model": "llama-test",
                },
            ]
            for form in provider_forms:
                settings_page = client.get("/settings")
                ai_saved = client.post(
                    "/settings/ai",
                    data={"csrf_token": csrf(settings_page), **form},
                    follow_redirects=False,
                )
                assert ai_saved.status_code == 303
                settings = db.get_settings()
                assert settings["ai_provider"] == form["ai_provider"]
                assert settings["ai_enabled"] == "false" and settings["ai_last_test_ok"] == "false"
                masked_page = client.get("/settings")
                assert "acceptance-secret" not in masked_page.text

            import_dir = Path(runtime_dir.name) / "import"
            import_dir.mkdir(exist_ok=True)
            db.init_db()
            assert import_dir.stat().st_mode & 0o002, "Importkatalogen ska vara skrivbar från hosten."
            imported_file = import_dir / "slukad-import.txt"
            imported_file.write_bytes(b"unikimport hemlig landing zone")
            importer.process_import_once()
            import_results = importer.process_import_once()
            assert any(item["status"] == "imported" for item in import_results)
            assert not imported_file.exists(), "Lyckad import ska tas bort från importkatalogen."
            imported_search = client.get(
                "/api/v1/documents",
                headers={"Authorization": f"Bearer {token}"},
                params={"q": "unikimport"},
            )
            assert imported_search.status_code == 200
            assert any(row["original_filename"] == "slukad-import.txt" for row in imported_search.json())

            blocked_import = import_dir / "blockerad.exe"
            blocked_import.write_bytes(b"unikblockerad plaintext ska inte ligga kvar")
            importer.process_import_once()
            failed_results = importer.process_import_once()
            assert any(item["status"] == "failed" for item in failed_results)
            assert not blocked_import.exists(), "Misslyckad import ska inte ligga kvar i importkatalogen."
            failed_files = list((Path(runtime_dir.name) / "import_failed").glob("*.enc"))
            assert failed_files and failed_files[-1].read_bytes().startswith(ENC_PREFIX.encode("ascii"))

            export_artifact = Path(runtime_dir.name) / "exports" / "dokumenteraren_export.zip.enc"
            assert export_artifact.exists() and export_artifact.read_bytes().startswith(ENC_PREFIX.encode("ascii"))

            assert_data_dir_has_no_plaintext(
                [
                    b"uniktext alfa",
                    b"unikdocx avtal",
                    b"unikxlsx kvitto",
                    b"unikimport hemlig",
                    b"unikblockerad plaintext",
                ]
            )

        print(f"ACCEPTANCE_OK data_dir={runtime_dir.name}")
    finally:
        runtime_dir.cleanup()


if __name__ == "__main__":
    main()
