# dokumenteraren

Första fungerande version av ett privat dokumentarkiv för lokal drift. Appen körs som container på port `12006` och sparar dokument, SQLite-databas, extraherad text och exporter under en bindad datakatalog.

## Start

```bash
docker compose build
docker compose up -d
curl http://localhost:12006/healthz
```

Öppna sedan `http://localhost:12006`.

Första konto:

- Användare: `admin`
- Lösenord: `12345`

Appen kräver lösenordsbyte innan arkivet kan användas.

## Backup

`docker-compose.yml` binder `./data:/data`. Säkerhetskopiera katalogen `./data` för att få med:

- `app.db`
- `uploads/` med originaldokument
- `derived/` med extraherad text
- `exports/` med skapade exportfiler

Delade Postgres/MariaDB/Valkey-resurser används inte i första versionen. SQLite + `/data` uppfyller backupkravet enklare och håller dokument och metadata i samma backupmål.

## Formatstöd

Tillåtna format:

- Text/data: `txt`, `md`, `rtf`, `csv`, `tsv`, `json`, `xml`, `yaml`, `yml`, `ini`, `conf`, `log`
- PDF: `pdf`
- Microsoft Office: `docx`, `xlsx`, `pptx`, äldre `doc`, `xls`, `ppt`
- OpenDocument/LibreOffice/OpenOffice: `odt`, `ods`, `odp`, `ott`, `ots`, `otp`
- Bilder: `jpg`, `jpeg`, `png`, `webp`, `tif`, `tiff`, `bmp`, `gif`, `heic`
- E-post/webb: `eml`, `html`, `htm`

Okända format blockeras. Format som kan arkiveras men inte texttolkas får status `archived_only`.

## LAN API

Skapa en API-token under `Settings`. Använd den som bearer token.

Lista dokument:

```bash
curl -H "Authorization: Bearer dk_..." http://localhost:12006/api/v1/documents
```

Ladda upp dokument:

```bash
curl -X POST http://localhost:12006/api/v1/documents \
  -H "Authorization: Bearer dk_..." \
  -F "file=@/path/till/dokument.pdf" \
  -F "template_id=car_insurance" \
  -F "tags=bil,försäkring"
```

Lista mallar:

```bash
curl -H "Authorization: Bearer dk_..." http://localhost:12006/api/v1/templates
```

## AI-settings

AI är avstängt från start och inga externa AI-anrop görs förrän en admin:

1. väljer provider under `Settings`,
2. sparar nödvändiga nycklar eller URL:er,
3. kör ett lyckat anslutningstest.

Providers i första versionen:

- `disabled`
- `openai`
- `claude`
- `ollama`

Redaktion är på som standard i chatflödet. Filter maskar personnummerliknande mönster, e-post, telefon, IBAN/kontonummer och egna ord/fraser.

## SMTP2GO

Mail läses från env. Hårdkoda inte lösenord i appkoden.

```env
SMTP_HOST=mail-eu.smtp2go.com
SMTP_PORT=587
SMTP_SECURE=false
SMTP_USER=noreply@ath0.se
SMTP_PASS=...
MAIL_FROM=noreply@ath0.se
```

När dessa finns kan `Settings` skicka testmail och ZIP-export via SMTP.

## Export

Webb-UI:t erbjuder:

- `GET /export/metadata.json`
- `GET /export/metadata.csv`
- `GET /export/zip`

ZIP-export innehåller originalfiler, metadata, extraherad text och manifest.

## Acceptansverifiering

Efter build kan kärnflödena verifieras i samma container som driftmiljön:

```bash
docker compose run --rm dokumenteraren python scripts/verify_acceptance.py
```

Skriptet kör mot en temporär datakatalog och verifierar auth/lösenordsbyte, API-import, indexering/sök för vanliga format, disabled AI-chat med redaktion, JSON/CSV/ZIP-export och säkra ZIP-filnamn.

## Driftanteckningar

- Health endpoint: `GET /healthz`
- Max uploadstorlek kan sättas med `MAX_UPLOAD_BYTES`, default 50 MB.
- Sessionsecret bör sättas med `SESSION_SECRET` i env.
- Appen är avsedd för privat/lokalt nät och kan senare läggas bakom lokal proxy på `dokumenteraren.theshire.lan`.
