#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path


def api_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def multipart_body(fields: dict[str, str], file_path: Path) -> tuple[bytes, str]:
    boundary = f"----dokumenteraren-{secrets.token_hex(16)}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    parts.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def request_json(url: str, token: str, *, method: str = "GET", body: bytes | None = None, content_type: str | None = None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {detail}") from exc
    return json.loads(data.decode("utf-8"))


def upload_file(base_url: str, token: str, file_path: Path, template_id: str, tags: str) -> dict[str, object]:
    fields = {"template_id": template_id, "tags": tags}
    body, content_type = multipart_body(fields, file_path)
    return request_json(api_url(base_url, "/api/v1/documents"), token, method="POST", body=body, content_type=content_type)


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload files to dokumenteraren over the LAN API.")
    parser.add_argument("files", nargs="*", type=Path, help="Files to upload.")
    parser.add_argument("--url", default=os.getenv("DOKUMENTERAREN_URL", "http://localhost:12006"), help="Base URL.")
    parser.add_argument("--token", default=os.getenv("DOKUMENTERAREN_TOKEN", ""), help="API token or DOKUMENTERAREN_TOKEN.")
    parser.add_argument("--template", default="", help="Template id, e.g. receipt or car_insurance.")
    parser.add_argument("--tags", default="", help="Comma-separated tags.")
    parser.add_argument("--list-templates", action="store_true", help="List available templates and exit.")
    parser.add_argument("--json", action="store_true", help="Print full JSON responses.")
    args = parser.parse_args()

    if not args.token:
        parser.error("--token or DOKUMENTERAREN_TOKEN is required.")

    if args.list_templates:
        templates = request_json(api_url(args.url, "/api/v1/templates"), args.token)
        for item in sorted(templates, key=lambda row: row["name"].lower()):
            print(f"{item['id']}\t{item['name']}")
        return 0

    if not args.files:
        parser.error("at least one file is required unless --list-templates is used.")

    exit_code = 0
    for file_path in args.files:
        if not file_path.is_file():
            print(f"skip: {file_path} is not a file", file=sys.stderr)
            exit_code = 1
            continue
        result = upload_file(args.url, args.token, file_path, args.template, args.tags)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"uploaded: {file_path} -> document #{result['id']} ({result['original_filename']})")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
