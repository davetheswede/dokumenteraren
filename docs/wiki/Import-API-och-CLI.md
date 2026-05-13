# Import, API och CLI

## Importvägar

`dokumenteraren` kan ta in dokument via:

- webbuppladdning
- importkatalog
- POP3
- IMAP
- LAN API
- CLI-klient

## Importkatalog

Lägg filer i:

```text
./import
```

Appen scannar katalogen vid start och periodiskt. En fil importeras när storlek och mtime är stabila över två scan, eller när en `.ready`-markör finns.

## Mailimport

Mailimporten är en klient, inte en e-postserver.

Under `Settings` kan du konfigurera ett dedikerat POP3- eller IMAP-konto. Appen pollar kontot, importerar attachments och raderar hanterade mail från importkontot för att undvika importloopar.

Beteende:

- attachments importeras som dokument
- små inline-bilder kan ignoreras
- mail utan attachments kan sparas som `.eml`
- otillåtna attachments loggas som `failed`
- hanterade mail raderas efter lyckad hantering

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

## CLI

CLI:t kräver bara Python 3 och standardbiblioteket.

```bash
install -m 755 cli/dokumenteraren-upload.py ~/.local/bin/dokumenteraren-upload
```

```bash
export DOKUMENTERAREN_URL=http://192.168.0.12:12006
export DOKUMENTERAREN_TOKEN=dk_...
```

```bash
dokumenteraren-upload ~/Dokument/kvitto.pdf --template receipt --tags "kvitto,2026"
dokumenteraren-upload --list-templates
```
