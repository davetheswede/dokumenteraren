# Fail2ban

`dokumenteraren` skriver misslyckade inloggningar till en separat driftlogg:

```text
/data/logs/fail2ban-auth.log
```

Loggen visas inte i användargränssnittet. Varje rad har ett stabilt format:

```text
2026-05-15T12:00:00+00:00 LOGIN_FAILED ip=203.0.113.10 username=namn path=/login
```

## Exempelkonfiguration

Exempel finns direkt i repot:

```text
fail2ban/filter.d/dokumenteraren.conf
fail2ban/jail.d/dokumenteraren.local.example
```

Kopiera dem till hostens fail2ban-kataloger:

```bash
sudo cp fail2ban/filter.d/dokumenteraren.conf /etc/fail2ban/filter.d/dokumenteraren.conf
sudo cp fail2ban/jail.d/dokumenteraren.local.example /etc/fail2ban/jail.d/dokumenteraren.local
```

Gör sedan appens logg läsbar från hostens fail2ban. Ett enkelt alternativ är en symlink:

```bash
sudo mkdir -p /var/log/dokumenteraren
sudo ln -sf "$(pwd)/data/logs/fail2ban-auth.log" /var/log/dokumenteraren/fail2ban-auth.log
sudo systemctl reload fail2ban
sudo fail2ban-client status dokumenteraren
```

Justera `maxretry`, `findtime` och `bantime` i jail-filen efter hur appen exponeras.
