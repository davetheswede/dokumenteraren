# Installation

## Docker Compose

```bash
git clone https://github.com/davetheswede/dokumenteraren.git
cd dokumenteraren
cp .env.example .env
docker compose up --build -d
curl http://localhost:12006/healthz
```

Öppna:

```text
http://localhost:12006
```

Första konto:

- användare: `admin`
- lösenord: `12345`

Appen kräver lösenordsbyte innan arkivet kan användas.

Vid multi-user-migreringen säkerställs även en vanlig användare med namnet `David`. Befintliga admin/importägda dokument flyttas till den användaren så att adminläget kan sakna direkt filåtkomst. Sätt `APP_DAVID_INITIAL_PASSWORD` i `.env` före första start om du vill välja annat initialvärde.

## Viktiga Miljövariabler

```env
SESSION_SECRET=byt-denna-till-en-lang-slumpstrang
SECURE_COOKIES=false
MAIL_FROM=noreply@example.test
FAIL2BAN_AUTH_LOG=/data/logs/fail2ban-auth.log
GEOIP_DATABASE_PATH=
```

Sätt `SECURE_COOKIES=true` om appen körs bakom HTTPS-proxy. Se då till att proxyn skickar `X-Forwarded-Proto: https`.

## Portar Och Volymer

Standardport:

```text
12006
```

Standardvolymer:

```text
./data   -> /data
./import -> /import
```

`./data` är arkiv och backupmål. `./import` är en separat inkorg för okrypterade inkommande filer.

Fail2ban-loggen ligger under `./data/logs/fail2ban-auth.log` och kan symlänkas till hostens `/var/log/dokumenteraren/`.
