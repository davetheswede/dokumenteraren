# dokumenteraren

![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED)
![Python](https://img.shields.io/badge/Python-3.12-3776AB)
![License](https://img.shields.io/badge/license-ESIL%20v1.0-green)
![Self hosted](https://img.shields.io/badge/self--hosted-local--first-111827)
![Size](https://img.shields.io/badge/app-lightweight-64748b)

`dokumenteraren` är ett litet, self-hosted dokumentarkiv för viktiga filer: försäkringar, kvitton, bankhandlingar, juridik, tekniska hemligheter, mailbilagor och annat man vill kunna hitta igen utan att införa ett stort dokumenthanteringssystem.

Den korta versionen:

- lagra dokument med mallar, taggar, sök och permanent radering
- kryptera dokument, metadata och extraherad text i vila
- importera via webb, API, CLI, importmapp, POP3 och IMAP
- backa upp en begriplig `./data`-katalog, med `./import` separat
- prata med valda dokument via opt-in AI, med redaktion innan text skickas iväg
- kör lokalt i en Docker-container utan att behöva Postgres, Redis eller extern storage

Appen är vibecodad tillsammans med AI. Jag är IT-arkitekt, inte programmerare till vardags, och projektet är ett sätt att lyfta in arkitekturtänk, driftkrav, informationssäkerhet och användarflöden i en konkret app.

## Vad Den Gör

### Dokument

- Ladda upp en eller många filer i webbgränssnittet.
- Sätt mall per fil, till exempel försäkring, bank, avtal, kvitto, lösenordsvalv eller tekniskt dokument.
- Lägg på taggar och ändra både taggar och mall i efterhand.
- Sök, filtrera, öppna, exportera och radera felaktiga poster direkt i UI:t.
- Låt appen gissa mall och tagga automatiskt importerade dokument som `automatiskt sorterad`.

### Kryptering Och Integritet

- Originaldokument sparas krypterade.
- Extraherad text sparas krypterad.
- Metadata och känsliga inställningar krypteras där det är relevant.
- Appen sparar checksummor före och efter kryptering för verifiering och dublettkontroll.
- AI är avstängt från start och måste aktiveras aktivt.
- Text redigeras innan AI-anrop, så personnummerliknande värden, e-post, telefon, IBAN/kontonummer och egna mönster kan maskas.

### Import Och Automation

- Webbuppladdning för manuellt arbete.
- Importmapp för scanner, filsynk eller andra automationer.
- POP3/IMAP-klient för ett dedikerat importkonto.
- Attachments importeras som dokument.
- Mail utan attachments kan sparas som `.eml`.
- LAN API med bearer token.
- Minimal CLI-klient för att skicka in filer från andra maskiner.

### Backup

Backupmodellen är avsiktligt enkel:

```text
./data   = det du backar upp
./import = inkommande, tillfälliga filer som inte ska följa med i backup
```

`./data` innehåller SQLite-databasen, krypterade dokument, krypterad extraherad text, exportartefakter och installationsnyckel om ingen master key sätts via env.

### AI-Stöd

AI-delen är byggd som ett verktyg, inte som ett krav.

- Välj dokument att prata med.
- Se både filnamn, mall och taggar när du väljer källor.
- Använd OpenAI, Claude eller lokal Ollama.
- Lämna AI helt avstängt om arkivet ska vara strikt lokalt.
- Redaktion är på som standard innan text skickas till en extern provider.

## Filosofi

`dokumenteraren` börjar i drift och informationshantering, inte i maximal feature-lista.

- Det ska vara begripligt var data ligger.
- Det ska vara enkelt att backa upp och återställa.
- Import ska vara praktisk utan att appen blir en e-postserver.
- Dokument som redan är känsliga ska behandlas som känsliga från början.
- AI ska vara opt-in och synligt, inte en dold molnkoppling.
- Hushålls- och privatdokument ska vara förstaklassobjekt, inte bara generiska PDF:er.
- Tekniska hemligheter som API-nycklar, certifikat, backupplaner och lösenordsvalv ska kännas hemma i samma arkiv.

## Målgrupp

Den passar bäst för:

- personer och hushåll som vill ha ett privat viktigt-arkiv
- hemmalabbare och self-hosters som vill äga sin data
- IT-personer som blandar vanliga dokument med tekniska hemligheter
- små miljöer där enkel backup är viktigare än enterprise-workflows
- användare som vill kunna forwarda mail med bilagor till ett importkonto

Den passar sämre om du vill ha ett fullskaligt DMS med avancerade workflows, många användare, revisionsprocesser, scannerflöden och mogna OCR-regler. Då är paperless-ngx troligen rätt verktyg.

## Storlek

Målet är att appen ska vara lightweight i arkitektur och drift:

- en FastAPI-app
- SQLite som databas
- inga krav på Postgres, Redis, queue-system eller S3
- cirka 4 000 rader Python i app, CLI och acceptance-test
- cirka 15 MB källträd exklusive `.git`, `data`, `import`, verifieringsbilder och temporära filer
- en Docker-service i `docker-compose.yml`

Docker-imagen är inte minimal eftersom den innehåller praktiska dokumentverktyg som LibreOffice, Poppler och Tesseract för extraktion/OCR. Själva applikationsarkitekturen är däremot liten och enkel att förstå.

## Varför Finns Den?

Det finns redan bra dokumentarkiv. [paperless-ngx](https://docs.paperless-ngx.com/) är ett moget, kraftfullt dokumenthanteringssystem med OCR, tags, correspondents, document types, mail rules, workflows och mycket mer. [Papra](https://papra.app/en/) är ett modernare och enklare open source-alternativ med fokus på organisationer, taggar, sök och smidig arkivering.

`dokumenteraren` finns för ett lite annat behov: ett privat, självhostat arkiv för en person eller ett hushåll där viktiga dokument blandas med tekniska hemligheter, mailbilagor, försäkringspapper, bankdokument, API-nycklar, kvitton och “sånt där man absolut behöver hitta när något händer”.

## Hur Den Skiljer Sig

Det här är inte tänkt som en “bättre paperless-ngx” eller en “bättre Papra”. Det är en annan tradeoff.

| Område | dokumenteraren | paperless-ngx | Papra |
| --- | --- | --- | --- |
| Primärt fokus | Privat viktigt-arkiv för hushåll/person + tekniska dokument | Fullt dokumenthanteringssystem för pappersflöden och OCR | Modern dokumentarkivering med enkel organisation och taggar |
| Målgrupp | Hemmalabbare, IT-personer, arkitekter, privatpersoner med backupdisciplin | Användare som vill ha ett moget DMS med mycket automatik | Användare som vill ha ett enklare, modernt dokumentarkiv |
| Import | Webb, API, CLI, importkatalog, POP3, IMAP | Consumer-folder, mail, scanner/OCR-orienterade flöden | Self-hosted/hosted dokumentarkivering med taggar och regler |
| Klassificering | Många färdiga privata mallar: försäkring, bank, juridik, tekniska hemligheter | Tags, correspondents, document types, custom fields och matchning | Organisationer, taggar och taggregler |
| Hemligheter | Tekniska dokumenttyper som lösenordsvalv, SSH-nycklar, API-tokens, TLS, DNS | Möjligt att lagra, men inte appens uttalade designcentrum | Möjligt att lagra, men främst generell dokumentarkivering |
| Backupmodell | `./data` är backupmål, `./import` separat | Mer komplett DMS-struktur med egen konfiguration och storage-modell | Beroende på deployment/storage |
| AI | Avstängt som standard, valfri OpenAI/Claude/Ollama, redaktion först | AI är inte kärnflödet i huvudprojektet | Inte kärnpositioneringen |
| Filosofi | Enkel, lokal, begriplig, arkitekturstyrd | Feature-rikt, moget, konfigurerbart | Enkelt, modernt, mer produktifierat |

Välj paperless-ngx om du vill ha ett moget, battle-tested DMS med stark OCR-pipeline, correspondents, workflows och många administrationsmöjligheter. Välj Papra om du vill ha en modern och mer strömlinjeformad dokumentplattform. Testa `dokumenteraren` om du vill ha ett mindre, lokalt och privat arkiv där backup, kryptering, mailforwarding, API/CLI och “prata med mina dokument” är centrala från start.

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
git clone https://github.com/davetheswede/dokumenteraren.git
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

European Sovereign Infrastructure License (ESIL) v1.0. Se [LICENSE](LICENSE).
