# Data, Backup och Säkerhet

## Backup

Backa upp `./data`.

Den innehåller:

- `app.db`
- `uploads/` med krypterade originaldokument
- `derived/` med krypterad extraherad text
- `exports/` med krypterade exportartefakter
- `import_failed/` med krypterad quarantine
- `keys/` med installationsnyckel om ingen master key satts via env
- `logs/` med driftloggar, inklusive fail2ban-loggen

Backa normalt inte upp `./import`. Den katalogen är till för inkommande filer innan appen importerat och krypterat dem.

## Master Key

Om `APP_MASTER_KEY` eller `DOKUMENTERAREN_MASTER_KEY` inte sätts genererar appen:

```text
/data/keys/install.key
```

Den filen behövs vid återställning. Förloras den kan krypterad data inte läsas.

## Säkerhetsmodell

Byggstenar:

- sessionsinloggning
- tvingat byte av första adminlösenord
- CSRF-skydd på formulär
- bearer token för LAN API
- isolerade dokumentytor per vanlig användare
- explicit delad läsrätt via accepterade inbjudningar
- admin utan direkt filåtkomst i adminläge
- manuell adminreset via Docker-CLI, inte via webben
- IP-gated adminimpersonering för support
- auditlogg med särskilda loginhändelser, IP och GeoIP-status
- separat fail2ban-logg som inte visas i UI
- säker filnamnshantering
- extension allowlist
- kryptering av dokument och extraherad text
- checksummor före och efter kryptering
- AI avstängt som standard
- redaktion innan AI-anrop

Rekommendationer:

- kör bakom HTTPS om appen nås utanför localhost
- sätt stark `SESSION_SECRET`
- backa upp `./data`
- skydda API-token som ett lösenord
- exponera inte appen publikt utan extra proxy, auth och åtkomstkontroller
