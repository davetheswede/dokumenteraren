# dokumenteraren

![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED)
![Python](https://img.shields.io/badge/Python-3.12-3776AB)
![License](https://img.shields.io/badge/license-MIT-green)
![Self hosted](https://img.shields.io/badge/self--hosted-local--first-111827)

`dokumenteraren` är ett privat, self-hosted dokumentarkiv för viktiga filer: försäkringar, kvitton, bankhandlingar, juridik, tekniska hemligheter, mailbilagor och annat man vill kunna hitta igen.

Appen är vibecodad tillsammans med AI. Jag är IT-arkitekt, inte programmerare till vardags, och projektet är ett sätt att lyfta in arkitekturtänk, driftkrav, informationssäkerhet och användarflöden i en konkret app.

## Varför

Målet är inte att ersätta ett stort DMS. Målet är att ha ett praktiskt privat arkiv som:

- går att köra själv i Docker
- sparar data i en enkel backupvänlig katalog
- krypterar dokument och metadata i vila
- kan importera filer via webb, API, importkatalog, POP3 och IMAP
- klassificerar dokument med mallar och taggar
- gör det möjligt att prata med valda dokument via valfri AI-provider

## Funktioner

- Inloggning med initial admin och tvingat lösenordsbyte.
- Kryptering i vila med per-dokumentnycklar.
- Webbaserad uppladdning med mall per fil.
- Arkivlista med sök, mallfilter, statusfilter och taggar.
- Redigering av mall och taggar i efterhand.
- Permanent radering av felaktiga poster.
- Checksummor före och efter kryptering.
- Dublettkontroll via SHA-256.
- Importkatalog utanför backupdata.
- POP3/IMAP-import av attachments.
- EML-arkivering när mail saknar attachments.
- Automatisk mallgissning och taggar som `automatiskt sorterad`.
- JSON, CSV och ZIP-export.
- LAN API med bearer token.
- Minimal CLI-klient för uppladdning från andra maskiner.
- Opt-in AI-chat mot OpenAI, Claude eller Ollama.
- Redaktion av känsliga mönster innan AI-anrop.

## Snabbstart

```bash
git clone <repo-url> dokumenteraren
cd dokumenteraren
cp .env.example .env
docker compose up --build -d
curl http://localhost:12006/healthz
```

Öppna sedan:

```text
http://localhost:12006
```

Första konto:

- användare: `admin`
- lösenord: `12345`

Appen kräver lösenordsbyte innan arkivet kan användas.

## Installation Med Docker

Skapa `.env`:

```env
SESSION_SECRET=byt-denna-till-en-lang-slumpstrang
SECURE_COOKIES=false
MAIL_FROM=noreply@example.test
```

Starta:

```bash
docker compose up --build -d
```

Standardport är `12006`.

Vill du köra bakom HTTPS-proxy:

```env
SECURE_COOKIES=true
```

Se till att proxyn skickar `X-Forwarded-Proto: https`.

## Data Och Backup

`docker-compose.yml` monterar:

```text
./data   -> /data
./import -> /import
```

Backa upp `./data`. Den innehåller:

- `app.db`
- `uploads/` med krypterade originaldokument
- `derived/` med krypterad extraherad text
- `exports/` med krypterade exportartefakter
- `import_failed/` med krypterad quarantine
- `keys/` med installationsnyckel om ingen master key satts via env

`./import` är avsiktligt separat. Där kan okrypterade filer ligga kort innan appen slukar dem, så den katalogen bör inte ingå i vanlig dokumentbackup.

Viktigt: om `APP_MASTER_KEY` eller `DOKUMENTERAREN_MASTER_KEY` inte sätts genererar appen `/data/keys/install.key`. Den måste följa med vid återställning.

## Importvägar

### Webb

Gå till `Ladda upp`, välj en eller flera filer och sätt mall per fil.

### Importkatalog

Lägg filer i:

```text
./import
```

Appen scannar katalogen vid start och periodiskt. En fil importeras när storlek/mtime är stabil över två scan, eller när en `.ready`-markör finns.

### Mailimport

Mailimporten är en klient, inte en e-postserver.

Under `Settings` kan du konfigurera ett dedikerat POP3- eller IMAP-konto. Appen pollar kontot, importerar attachments och raderar hanterade mail från importkontot.

Beteende:

- attachments importeras som dokument
- små inline-bilder kan ignoreras
- mail utan attachments kan sparas som `.eml`
- otillåtna attachments loggas som `failed`
- hanterade mail raderas för att undvika importloopar

## Dokumentmallar

Appen levereras med många mallar för privat dokumenthantering, bland annat:

- försäkringstyper, inklusive hund, katt, resa, båt, bostadsrätt och värdesaker
- bank, kredit, bolån, ISK, fondkonto och värdepapper
- kvitton, garanti, skatt, anställning, medicin och juridik
- tekniska dokument som lösenordsvalv, API-nycklar, SSH-nycklar, TLS-certifikat, DNS och backupplaner

Mallarna används för filtrering, auto-klassificering och sammanhang i dokumentvyn.

## LAN API

Skapa en API-token under `Settings`. Token visas en gång.

Lista dokument:

```bash
curl -H "Authorization: Bearer dk_..." \
  http://localhost:12006/api/v1/documents
```

Ladda upp dokument:

```bash
curl -X POST http://localhost:12006/api/v1/documents \
  -H "Authorization: Bearer dk_..." \
  -F "file=@/path/till/dokument.pdf" \
  -F "template_id=receipt" \
  -F "tags=kvitto,2026"
```

Lista mallar:

```bash
curl -H "Authorization: Bearer dk_..." \
  http://localhost:12006/api/v1/templates
```

Importstatus:

```bash
curl -H "Authorization: Bearer dk_..." \
  http://localhost:12006/api/v1/imports
```

## CLI-Klient

CLI:t kräver bara Python 3 och standardbiblioteket.

Installera på en annan maskin:

```bash
install -m 755 cli/dokumenteraren-upload.py ~/.local/bin/dokumenteraren-upload
```

Sätt miljövariabler:

```bash
export DOKUMENTERAREN_URL=http://192.168.0.12:12006
export DOKUMENTERAREN_TOKEN=dk_...
```

Ladda upp:

```bash
dokumenteraren-upload ~/Dokument/kvitto.pdf --template receipt --tags "kvitto,2026"
```

Flera filer:

```bash
dokumenteraren-upload ~/Skannat/*.pdf --tags "skannat,inkorg"
```

Lista mallar:

```bash
dokumenteraren-upload --list-templates
```

## AI-Chat

AI är avstängt från start.

En admin måste:

1. välja provider under `Settings`
2. spara nödvändiga nycklar eller URL:er
3. köra ett lyckat anslutningstest

Stödda providers:

- disabled
- OpenAI
- Claude
- Ollama

Redaktion är på som standard. Appen maskar personnummerliknande mönster, e-post, telefon, IBAN/kontonummer och egna ord/fraser innan text skickas till AI.

## SMTP

SMTP används för testmail och ZIP-export via mail.

Exempel:

```env
SMTP_HOST=mail.example.test
SMTP_PORT=587
SMTP_SECURE=false
SMTP_USER=noreply@example.test
SMTP_PASS=byt-denna
MAIL_FROM=noreply@example.test
```

Hårdkoda aldrig lösenord i appkoden.

## Export

Webb-UI:t erbjuder:

- metadata som JSON
- metadata som CSV
- ZIP-export med originalfiler, metadata, extraherad text och manifest

Nedladdningen streamas som vanlig ZIP efter explicit användaråtgärd. Artefakten som sparas under `/data/exports` är krypterad.

## Säkerhetsmodell

Det här är en privat self-hosted app, inte en färdig SaaS-produkt.

Byggstenar:

- sessionsinloggning
- CSRF på formulär
- bearer token för LAN API
- säker filnamnshantering
- extension allowlist
- kryptering av dokument och metadata
- checksummor före och efter kryptering
- inga AI-anrop utan aktiv konfiguration
- hemligheter maskas i settings-UI:t

Rekommendationer:

- kör bakom HTTPS om appen nås utanför localhost
- sätt stark `SESSION_SECRET`
- backa upp `./data`
- skydda API-token som ett lösenord
- exponera inte appen publikt utan extra hårdning, proxy och åtkomstkontroller

## Verifiering

Kör acceptance-testet i samma container som driftmiljön:

```bash
docker compose run --rm dokumenteraren python scripts/verify_acceptance.py
```

Testet verifierar bland annat:

- auth och lösenordsbyte
- API-tokenflöde
- upload och multi-upload
- mall per fil
- tagg- och mallredigering
- radering av dokument
- indexering och sök
- importkatalog
- mailimportens MIME/attachment-flöde
- kryptering i vila
- checksum metadata
- AI disabled-läge och redaktion
- JSON/CSV/ZIP-export
- säkra ZIP-filnamn

## Utveckling

```bash
python3 -m py_compile app/main.py
docker compose build dokumenteraren
docker compose run --rm dokumenteraren python scripts/verify_acceptance.py
```

## Licens

MIT. Se [LICENSE](LICENSE).
