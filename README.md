# dokumenteraren

Första fungerande version av ett privat dokumentarkiv för lokal drift. Appen körs som container på port `12006` och sparar dokument, metadata, extraherad text, importer och exporter under en bindad datakatalog.

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
- `uploads/` med krypterade originaldokument
- `derived/` med krypterad extraherad text
- `exports/` med krypterade exportartefakter
- `import_failed/` med krypterad quarantine för misslyckade importer
- `keys/` med installationsnyckel när `APP_MASTER_KEY` inte sätts via env

Arkiverade dokument, extraherade texter, exportartefakter, originalfilnamn, titlar, taggar och extraherad metadata krypteras med per-dokumentnycklar. Dokumentnycklar wrapas med ägarens användarnyckel, och användarnyckeln skyddas av appens installationsnyckel. Om `APP_MASTER_KEY` eller `DOKUMENTERAREN_MASTER_KEY` inte är satt genererar appen `/data/keys/install.key`; den måste följa med vid återställning.

Delade Postgres/MariaDB/Valkey-resurser används inte i första versionen. SQLite + krypterade artefakter under `/data` uppfyller backupkravet enklare och håller dokument och metadata i samma backupmål.

## Importkatalog

Lägg filer i `./data/import`. Appen scannar katalogen vid start och därefter periodiskt. En fil importeras när storlek/mtime är stabil över två scan eller när en `.ready`-markör finns.

Lyckad import validerar formatet, hashar filen, extraherar metadata/text, skriver krypterade artefakter till arkivet och tar bort plaintext-filen från `import/`. Otillåtna eller trasiga filer flyttas till krypterad quarantine under `import_failed/` och syns i importstatus.

Vid startup sätter appen importkatalogen skrivbar för hosten så filer kan droppas in i bind-mounten även när containern har skapat katalogen först.

Schemalagd backup bör undvika `./data/import` eller hålla den tom, eftersom filer där är okrypterade tills appen har hunnit sluka dem.

## Formatstöd

Tillåtna format:

- Text/data: `txt`, `md`, `rtf`, `csv`, `tsv`, `json`, `xml`, `yaml`, `yml`, `ini`, `conf`, `log`
- PDF: `pdf`
- Microsoft Office: `docx`, `docm`, `dotx`, `dotm`, `xlsx`, `xlsm`, `xltx`, `xltm`, `pptx`, `pptm`, `potx`, `potm`, `ppsx`, `ppsm`, äldre `doc`, `xls`, `ppt`, `dot`, `xlt`, `pot`
- OpenDocument/LibreOffice/OpenOffice: `odt`, `ods`, `odp`, `ott`, `ots`, `otp`, flat XML-formaten `fodt`, `fods`, `fodp`
- Bilder: `jpg`, `jpeg`, `png`, `webp`, `tif`, `tiff`, `bmp`, `gif`, `heic`
- E-post/webb: `eml`, `html`, `htm`

Okända format blockeras. Format som kan arkiveras men inte texttolkas får status `archived_only`.

## LAN API

Skapa en API-token under `Settings`. Använd den som bearer token.
Den nya token visas en gång efter skapande och skickas inte i redirect-URL:en.

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

Importstatus:

```bash
curl -H "Authorization: Bearer dk_..." http://localhost:12006/api/v1/imports
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

Nedladdningen streamas som vanlig ZIP efter explicit användaråtgärd. Artefakten som sparas under `/data/exports` är krypterad (`.zip.enc`).

## Acceptansverifiering

Efter build kan kärnflödena verifieras i samma container som driftmiljön:

```bash
docker compose run --rm dokumenteraren python scripts/verify_acceptance.py
```

Skriptet kör mot en temporär datakatalog och verifierar auth/lösenordsbyte, API-upload, indexering/sök för vanliga format inklusive Office macro/template-varianter och flat OpenDocument, importkatalog, kryptering i vila, disabled AI-chat med redaktion, JSON/CSV/ZIP-export och säkra ZIP-filnamn.

## Driftanteckningar

- Health endpoint: `GET /healthz`
- Max uploadstorlek kan sättas med `MAX_UPLOAD_BYTES`, default 50 MB.
- Sessionsecret bör sättas med `SESSION_SECRET` i env.
- Appen är avsedd för privat/lokalt nät och kan läggas bakom lokal HTTPS-proxy på `dokumenteraren.theshire.lan`.
- Sätt `SECURE_COOKIES=true` när appen körs bakom HTTPS/TLS-proxy. HSTS-header sätts när inkommande request eller `X-Forwarded-Proto` är `https`.
