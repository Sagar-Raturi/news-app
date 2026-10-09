# Deployment log

Progress through `.claude/skills/deploy-ledger/SKILL.md`. Facts only, **never
secrets** (no passwords, keys, tokens or DSNs; those live in Bitwarden and in
`.env.production` on the server).

## Facts

| What | Value |
|---|---|
| Domain (.in) | _not bought yet_ |
| Domain (.com) | _not bought yet_ |
| Server | Hostinger KVM 2, location: _?_ |
| Server IPv4 | _?_ |
| Deployed tag | _none_ |
| Staging address | _?_ |

## Phases

| # | Phase | Status | Date | Notes |
|---|---|---|---|---|
| 0 | Before starting (name, Bitwarden, repo private) | to do | | |
| 1 | Domain at GoDaddy | to do | | |
| 2 | DNS on Cloudflare | to do | | |
| 3 | Hostinger VPS | to do | | |
| 4 | SSH key and first login | to do | | |
| 5 | Secure server, Docker | to do | | |
| 6 | Email (Cloudflare Email Routing, Brevo) | to do | | |
| 7 | Backups storage (R2, healthchecks.io) | to do | | |
| 8 | Sentry | to do | | |
| 9 | Staging deploy and tests | to do | | |
| 10 | Nightly backups, restore drill, UptimeRobot | to do | | |
| 11 | Cloudflare Access for the admin | to do | | |
| 12 | Switch to production (behind a wall) | to do | | |
| 13 | Launch content, launch | to do | | |

## Notes

- 2026-10-09: stack chosen (GoDaddy, Cloudflare, Hostinger KVM 2 with the
  bundled database, Brevo, R2 backups). Backup and restore scripts written;
  first real run happens on staging (phase 10).
