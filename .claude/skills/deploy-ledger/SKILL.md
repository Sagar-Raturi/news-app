---
name: deploy-ledger
description: Guide the owner step by step through deploying The Ledger on the chosen stack — GoDaddy domain, Cloudflare DNS/security/backups, Hostinger VPS (KVM 2, Ubuntu 24.04) running the Docker production stack, Brevo email, Sentry, UptimeRobot, healthchecks.io — first as staging, then live. Use when the user asks to deploy, go live, set up the domain/DNS/server/email/backups/monitoring, continue or check deployment, update the live site, or asks what the next deployment step is.
---

# Deploy The Ledger: GoDaddy + Cloudflare + Hostinger

This is the concrete deployment path the owner chose (2026-10-09). Background
(architecture, every setting, incident runbook) is in `docs/DEPLOYMENT.md`;
this file is the step-by-step route through it.

## How to guide the owner (read first)

1. **Find where we are.** Read `docs/DEPLOY_LOG.md` (progress, domain, server
   IP, decisions; never secrets). Resume at the first phase not marked done.
   After finishing a phase, tick it there with the date and any facts the next
   session needs (IP address, domain, which options were chosen).
2. **One phase at a time.** The owner is not a developer: give click-by-click
   steps, say what they should see, and confirm each phase works before
   starting the next. Say what each paid step costs before they buy.
3. **Secrets never go through the chat.** Never ask the owner to paste a
   password, API key, SMTP key, DSN or secret key into the conversation. They
   type them into the provider's dashboard or into `.env.production` on the
   server with `nano`. Secrets the server can generate (Django secret key,
   database password) are written straight into the file by a command that
   doesn't print them. If a secret is pasted into chat anyway, tell them to
   revoke it and make a new one.
4. **Accounts and payments are the owner's.** Claude can't create accounts,
   enter card details or accept terms; give the steps and wait.
5. **Server commands.** After phase 4 Claude can run commands on the server
   from this computer with `ssh ledger '…'`, each approved by the owner.
   Interactive commands that ask for a password (`createsuperuser`, `nano`)
   are run by the owner in their own terminal (`ssh ledger`). Before anything
   destructive (`down -v`, deleting volumes, `restore.sh --yes`, changing the
   live domain's DNS), say exactly what it does and get a clear yes.
6. **Code changes** still follow `CLAUDE.md` (tests, one item per commit). Deploy
   only tagged releases (phase 9).

## The stack and why

| Piece | Choice | Cost | Why |
|---|---|---|---|
| Domain | **GoDaddy** (`.in` and `.com`) | ~₹1,000–1,500/yr each | Kept separate from hosting, so moving servers never touches the domain |
| DNS, HTTPS proxy, firewall | **Cloudflare** Free | Free | Fast DNS, hides the server's IP, blocks attacks |
| Server | **Hostinger VPS KVM 2** (2 vCPU, 8 GB, 100 GB NVMe), Ubuntu 24.04, 12-month term | ~₹799–929/mo + 18% GST, paid upfront | Best value; rupee billing with UPI; 8 GB fits the database on the same server |
| Database | **PostgreSQL in Docker on the server** (`bundled-db`) | Included | Saves ~₹1,300+/mo of managed database; backed up nightly off the server |
| Sending email | **Brevo** Free (300/day) | Free | Complaint acknowledgements and staff notices |
| Receiving email | **Cloudflare Email Routing** | Free | grievance@, contact@, corrections@ forward to the owner's Gmail |
| Backups | **Cloudflare R2** (`ledger-backups`, 30 days) + **healthchecks.io** | Free tiers (R2: 10 GB) | Copies off the server every night; alert if a night is missed |
| Admin protection | **Cloudflare Zero Trust Access** (one-time PIN) | Free (≤50 users) | A second sign-in step before anyone reaches /admin/ (the privacy policy promises it) |
| Errors | **Sentry** Developer plan | Free | Email when the site or the agents fail |
| Uptime | **UptimeRobot** Free | Free | Alert when the site is down |
| Code | **GitHub** (private repository) | Free | The server downloads tagged releases with a read-only deploy key |
| Password manager | **Bitwarden** Free | Free | Holds every login and the copy of `.env.production` |

Running cost: roughly ₹1,100–1,300/month (server + GST) plus the domains. The
Anthropic API is extra when bought (see `docs/DEPLOYMENT.md` section 4).

---

## Phase 0: Before starting

Have ready: the final publication name (trademark checked on IP India's public
search), a card or UPI, the GST number if the business has one, a Gmail
address for receiving reader mail, and a phone for two-factor codes. Install
**Bitwarden** (browser extension and phone app) and store every password from
here on in it. Turn on two-factor authentication for every account below.

The repository is currently **public** on GitHub. Make it private before going
further (GitHub → repository → Settings → General → Danger Zone → Change
visibility → Private); the server will use a deploy key (phase 9).

## Phase 1: Buy the domain at GoDaddy

1. godaddy.com (the India site, prices in ₹) → search the name → add the
   `.in` and the `.com` to the cart.
2. In the cart: **1 year** (or longer), **remove every add-on**: email,
   Microsoft 365, website builder, hosting, SSL certificate, "premium DNS".
   Cloudflare provides HTTPS and DNS for free. Keep domain privacy only if it
   is free.
3. Pay; create the GoDaddy account; turn on two-step verification
   (Account → Login & PIN).
4. My Products → each domain → turn **auto-renew on** (an expired domain takes
   the site down).

Done when: both domains appear under My Products.

## Phase 2: Move DNS to Cloudflare

1. dash.cloudflare.com → sign up → turn on two-factor (My Profile → Authentication).
2. **Add a domain** → enter the `.in` domain → plan **Free**.
3. Cloudflare scans the existing records. Delete any `A` / `CNAME` records
   pointing at GoDaddy's parking page (`@`, `www`); there's nothing to keep.
4. Cloudflare shows **two nameservers** (like `ada.ns.cloudflare.com`).
5. GoDaddy → My Products → the domain → **DNS** → **Nameservers** → Change
   nameservers → "I'll use my own nameservers" → enter both → Save. If
   GoDaddy says DNSSEC is on, turn DNSSEC off first.
6. Wait for Cloudflare's "your domain is now active" email (minutes to a few
   hours). Repeat 2–6 for the `.com`.
7. In Cloudflare, for the `.in` domain:
   - SSL/TLS → Overview → **Full (strict)**
   - SSL/TLS → Edge Certificates → **Always Use HTTPS: on**, **Minimum TLS: 1.2**
   - Speed → leave **Rocket Loader off** (it rewrites scripts and can break the admin).

Done when: Cloudflare shows the domain as **Active**.

## Phase 3: Buy the Hostinger VPS

1. hostinger.in → VPS Hosting → **KVM 2** → term **12 months**. Before paying,
   add GST details if you have them (account billing details) so the invoice
   carries them. Pay with UPI or card.
2. The setup wizard in hPanel:
   - **Location:** India if offered; otherwise the nearest (Singapore). Confirm at checkout.
   - **Operating system:** "Plain OS" → **Ubuntu 24.04 LTS** (not a control
     panel, not an app template; we install Docker ourselves).
   - **Root password:** generate a long one in Bitwarden.
   - **SSH key:** add the public key from phase 4 now if you have it (or later
     in hPanel → VPS → Settings → SSH keys).
3. In hPanel → VPS → overview, note the **IPv4 address**. Write it in
   `docs/DEPLOY_LOG.md`.
4. hPanel → VPS → Backups: leave Hostinger's weekly backup on (extra safety;
   the nightly off-server backup in phase 10 is the main one).

Done when: the VPS shows "Running" with Ubuntu 24.04.

## Phase 4: SSH key and first login (on the owner's Windows PC)

In a PowerShell terminal:

```powershell
ssh-keygen -t ed25519 -C "ledger-server"          # Enter for the default file; a passphrase is optional
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub  # copy this line into hPanel → VPS → Settings → SSH keys
ssh root@<IP>                                     # answer "yes" to the fingerprint question; type exit to leave
```

Then add a shortcut so `ssh ledger` works (Claude can write this file):
`C:\Users\<you>\.ssh\config`

```
Host ledger
    HostName <IP>
    User ledger
    IdentityFile ~/.ssh/id_ed25519
Host ledger-root
    HostName <IP>
    User root
    IdentityFile ~/.ssh/id_ed25519
```

Done when: `ssh ledger-root` logs in without a password.

## Phase 5: Secure the server and install Docker

Claude runs these with `ssh ledger-root '…'` (owner approves). Ubuntu 24.04's
SSH service is called `ssh`.

```bash
# Updates, firewall tools, automatic security updates, Indian time
apt update && DEBIAN_FRONTEND=noninteractive apt -y upgrade
apt -y install ufw fail2ban unattended-upgrades git curl
dpkg-reconfigure -f noninteractive unattended-upgrades
timedatectl set-timezone Asia/Kolkata

# Deploy user "ledger": SSH key login only; docker access; sudo without a
# password (it has none, and docker access is root-equivalent anyway)
adduser --disabled-password --gecos "" ledger
usermod -aG sudo ledger
echo "ledger ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/ledger && chmod 440 /etc/sudoers.d/ledger
install -d -m 700 -o ledger -g ledger /home/ledger/.ssh
install -m 600 -o ledger -g ledger /root/.ssh/authorized_keys /home/ledger/.ssh/authorized_keys

# 2 GB swap as a safety net
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
grep -q swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab

# Docker (official script) and compose plugin
curl -fsSL https://get.docker.com | sh
usermod -aG docker ledger

# Firewall: SSH, HTTP, HTTPS (and HTTP/3) only
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp && ufw --force enable
```

**Check `ssh ledger` works from a new terminal before the next step**, then
lock SSH down. The file is named `00-…` because Ubuntu's cloud image ships
`50-cloud-init.conf` with `PasswordAuthentication yes`, and the first setting
read wins:

```bash
printf "PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n" > /etc/ssh/sshd_config.d/00-ledger.conf
sshd -t && systemctl restart ssh
sshd -T | grep -Ei '^(passwordauthentication|permitrootlogin)'   # expect "no" for both
```

From now on use `ssh ledger` (root login is off; `sudo` works for the ledger
user). Hostinger's browser terminal in hPanel still works if SSH ever breaks.

Done when: `ssh ledger 'docker run --rm hello-world'` prints "Hello from Docker!".

## Phase 6: Email

**Receiving first (Cloudflare Email Routing)**, so the addresses on the
Contact and Grievance pages work and Brevo's confirmation email can arrive:
1. Cloudflare → the domain → **Email** → Email Routing → enable. Let it add
   its MX and SPF records.
2. Destination address: the owner's Gmail (confirm the email Cloudflare sends).
3. Routing rules: `grievance@`, `contact@`, `corrections@`, `newsroom@`,
   `privacy@` → that Gmail (or a catch-all).

**Sending (Brevo):**
1. brevo.com → sign up (Free) → two-factor on.
2. Senders, Domains & Dedicated IPs → **Domains** → Add a domain → the `.in`
   domain → authenticate it. Brevo lists DNS records (a `brevo-code` TXT,
   DKIM records, a DMARC TXT): add each one in Cloudflare → DNS → Records,
   exactly as shown, **proxy off (grey cloud)**. Back in Brevo, press
   Verify / Authenticate.
3. **One SPF record only:** if Brevo asks for SPF too, edit Cloudflare's
   existing SPF TXT into a single record:
   `v=spf1 include:_spf.mx.cloudflare.net include:spf.brevo.com ~all`.
4. Senders → add `newsroom@<domain>` and confirm it from Gmail.
5. SMTP & API → **SMTP** → note the **login** (`…@smtp-brevo.com`) and
   **Generate a new SMTP key**; store both in Bitwarden. They go into
   `.env.production` in phase 9 (`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`).

Done when: an email sent from another account to `contact@<domain>` arrives
in Gmail, and Brevo shows the domain as authenticated.

## Phase 7: Backup storage and the missed-backup alarm

**Cloudflare R2:**
1. Cloudflare → **R2 Object Storage** → enable (it may ask for a card; the
   free tier covers 10 GB).
2. Create bucket **`ledger-backups`**, location hint Asia-Pacific.
3. R2 → **Manage API tokens** → Create API token → permission **Object Read &
   Write**, **only bucket `ledger-backups`** → create. Store the **Access Key
   ID**, **Secret Access Key** and the **S3 endpoint**
   (`https://<account id>.r2.cloudflarestorage.com`) in Bitwarden.

**healthchecks.io:**
1. healthchecks.io → sign up (Free) → Add Check: name `ledger-backup`,
   period **1 day**, grace **3 hours** → notification by email.
2. Store its **ping URL** in Bitwarden.

Done when: the bucket exists and the token and ping URL are saved.

## Phase 8: Error tracking

sentry.io → sign up (Developer, free) → create a project, platform **Django**,
name `ledger` → store the **DSN** in Bitwarden. Alerts: Project → Settings →
Alerts → keep "email on new issues".

## Phase 9: Staging at `staging.<domain>`

**9.1 Release (Claude, owner approves).** Merge the working branch into `main`
through a pull request on GitHub, run the full test suite, and tag the release
(`v0.1.0`). Record the tag in the log.

**9.2 Code on the server.**

```bash
# Read-only deploy key for the private repository
ssh ledger 'ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N "" -C ledger-server && cat ~/.ssh/github_deploy.pub'
```

Owner: GitHub → repository → Settings → **Deploy keys** → Add → paste that
key, title "ledger server", **write access off**. Then:

```bash
ssh ledger 'printf "Host github.com\n  IdentityFile ~/.ssh/github_deploy\n  IdentitiesOnly yes\n" >> ~/.ssh/config && chmod 600 ~/.ssh/config'
ssh ledger 'sudo install -d -o ledger -g ledger /srv/ledger && ssh -o StrictHostKeyChecking=accept-new -T git@github.com; git clone git@github.com:Sagar-Raturi/news-app.git /srv/ledger && cd /srv/ledger && git checkout v0.1.0'
```

**9.3 Settings.** Claude creates the file and fills everything that isn't a
third-party secret:

```bash
ssh ledger 'cd /srv/ledger && cp .env.production.example .env.production && chmod 600 .env.production'
# Generated secrets, written without printing them:
ssh ledger 'cd /srv/ledger && K=$(openssl rand -base64 48 | tr -d "\n/+=") && sed -i "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$K|" .env.production'
ssh ledger 'cd /srv/ledger && P=$(openssl rand -hex 24) && sed -i -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$P|" -e "s|^DATABASE_URL=.*|DATABASE_URL=postgres://ledger:$P@db:5432/ledger|" .env.production'
```

Non-secret values for staging (Claude sets them with `sed`):
`DJANGO_ENV=staging`, `SITE_DOMAIN=staging.<domain>`,
`SITE_BASE_URL`/`WAGTAILADMIN_BASE_URL=https://staging.<domain>`,
`DJANGO_ALLOWED_HOSTS=staging.<domain>`, `ACME_EMAIL`, `APP_VERSION=v0.1.0`,
`NEWSDESK_WRITER=fake`, `DEFAULT_FROM_EMAIL="<Name> <newsroom@<domain>>"`,
`DJANGO_ADMINS`.

The owner then runs `ssh ledger`, `nano /srv/ledger/.env.production`, and
pastes from Bitwarden: `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
`BACKUP_R2_ENDPOINT`, `BACKUP_R2_ACCESS_KEY_ID`, `BACKUP_R2_SECRET_ACCESS_KEY`,
`BACKUP_PING_URL`, `SENTRY_DSN` (Ctrl+O, Enter, Ctrl+X to save). Then save a
copy of the whole file in Bitwarden (secure note).

**9.4 DNS.** Cloudflare → DNS → add `A staging → <IP>` and
`A www.staging → <IP>`, both **DNS only (grey cloud)** so Caddy can get its
certificate directly.

**9.5 Start.**

```bash
ssh ledger 'cd /srv/ledger && docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build'
ssh ledger 'cd /srv/ledger && docker compose -f docker-compose.prod.yml --env-file .env.production ps'
ssh ledger 'cd /srv/ledger && docker compose -f docker-compose.prod.yml --env-file .env.production logs --tail 80 web caddy'
curl -s https://staging.<domain>/healthz/     # {"database": "ok", "redis": "ok"}
```

The first build takes several minutes; `web` runs the migrations and
`bootstrap_site` and turns "healthy" after that.

**9.6 First admin (owner, interactive).**

```bash
ssh ledger
cd /srv/ledger && docker compose -f docker-compose.prod.yml --env-file .env.production exec web python manage.py createsuperuser
```

**9.7 Turn on Cloudflare's proxy.** Once `https://staging.<domain>` works,
switch both staging records to **Proxied (orange cloud)**. Check the site
still loads (SSL mode is Full (strict)).

**9.8 Test on staging** (record results in the log):
- Home, a section, search, `/robots.txt` (must say `Disallow: /` on staging), `/sitemap.xml`
- Admin: Site settings → fill publisher and grievance details (test values
  are fine), publish the Grievance page, send a test complaint → the officer
  address and the complainant both get email (check Brevo → Logs if not)
- Write and publish a hand-written article with an image; add a correction
- AI articles: generate one with the fake agents; watch the live activity feed
- Sentry: `docker compose … exec web python manage.py shell -c "import sentry_sdk; sentry_sdk.capture_message('staging test'); sentry_sdk.flush()"` → appears in Sentry
- `docker compose … exec web python manage.py launch_check` runs

Done when: all of the above pass.

## Phase 10: Nightly backups, restore drill, uptime alerts

```bash
ssh ledger 'cd /srv/ledger && sh docker/backup.sh'        # first run by hand: watch it finish
ssh ledger '(crontab -l 2>/dev/null; echo "30 2 * * * cd /srv/ledger && sh docker/backup.sh >> /srv/ledger/backups/backup.log 2>&1") | crontab -'
```

Check: R2 → `ledger-backups/ledger/` has the `db-…dump` and `media-…tgz`;
healthchecks.io shows the check as up.

**Restore drill (staging only; confirm with the owner first; it replaces the
staging database):**

```bash
ssh ledger 'cd /srv/ledger && ls -t backups | head'
ssh ledger 'cd /srv/ledger && sh docker/restore.sh backups/db-<time>.dump backups/media-<time>.tgz --yes'
```

Then open the site and the admin. Record the date of the drill in the log;
repeat monthly (`docs/DEPLOYMENT.md` section 11).

**UptimeRobot:** uptimerobot.com → Free → New monitor → HTTP(s) →
`https://staging.<domain>/healthz/`, every 5 minutes, alert by email (and the
app). Switch it to the main domain in phase 12.

## Phase 11: Protect the admin (Cloudflare Access)

1. Cloudflare → **Zero Trust** → choose a team name → plan **Free** (it may ask
   for a card; it stays ₹0 for up to 50 users).
2. Settings → Authentication → keep **One-time PIN** on.
3. Access → Applications → **Add an application** → Self-hosted → name
   "Ledger admin" → add three destinations on `staging.<domain>`: path
   `admin`, path `django-admin`, path `newsdesk` → session 24 hours.
4. Policy: **Allow**, Include → **Emails** → the owner's address (and each
   staff member's).
5. Test in a private window: `/admin/` first shows Cloudflare's code prompt;
   the homepage doesn't.

Done when: the admin needs the emailed code, then the Wagtail login.

## Phase 12: Switch the server to production (behind a wall)

Staging data is test data, so production starts clean. **Confirm with the
owner before step 2: it deletes the staging database and images.**

1. Final backup: `ssh ledger 'cd /srv/ledger && sh docker/backup.sh'`.
2. `ssh ledger 'cd /srv/ledger && docker compose -f docker-compose.prod.yml --env-file .env.production down -v'`
3. Release: tag the version to launch (e.g. `v1.0.0`) and
   `ssh ledger 'cd /srv/ledger && git fetch --tags && git checkout v1.0.0'`.
4. Settings: `DJANGO_ENV=production`, `SITE_DOMAIN=<domain>`,
   `SITE_BASE_URL`/`WAGTAILADMIN_BASE_URL=https://<domain>`,
   `DJANGO_ALLOWED_HOSTS=<domain>,www.<domain>`, `APP_VERSION=v1.0.0`,
   `NEWSDESK_WRITER=anthropic` (plus `ANTHROPIC_API_KEY`, entered by the owner,
   if bought). Generate a **new** `DJANGO_SECRET_KEY` and database password
   (the commands in 9.3).
5. **Wall first:** in Zero Trust, add an Access application for the **whole
   domain** `<domain>` (and `www`), same email policy. Readers can't see the
   site until launch day.
6. DNS: `A @ → <IP>` and `A www → <IP>`, grey cloud. Delete the staging records
   (or leave them pointing nowhere useful; remove them).
7. Start (`up -d --build`), check `https://<domain>/healthz/`, then switch both
   records to orange (proxied).
8. Owner: `createsuperuser` (as in 9.6); update the admin Access application
   to the main domain's paths. Pause the UptimeRobot monitor until launch
   (the wall answers its checks with a login page).

## Phase 13: Launch content, then open the doors

Owner, in the admin (`https://<domain>/admin/`):
1. **Snippets → Authors:** real people only (name, role, bio, photo).
2. **Settings → Site settings:** publication name and tagline; Publisher
   details; Grievance redressal (officer living in India; the self-regulating
   body once joined). Leave "Demo notice" off.
3. **Pages:** review the draft About, How we use AI, Corrections, Contact,
   Grievance redressal pages and publish them; publish **Terms** and
   **Privacy** only after the lawyer's review.
4. Write or generate and approve the launch articles (hand-written articles
   work without an API key).
5. `ssh ledger 'cd /srv/ledger && docker compose -f docker-compose.prod.yml --env-file .env.production exec web python manage.py launch_check'`
   until it says **Ready to launch**; go through its "Also confirm" list.
6. Send one real complaint through the form; check both emails arrive.
7. **Launch:** delete the whole-domain Access application (keep the admin
   one). Point UptimeRobot at `https://<domain>/healthz/` and resume it.
8. Google: Search Console → add a **Domain** property → verify with the TXT
   record in Cloudflare → submit `https://<domain>/sitemap.xml` and
   `https://<domain>/news-sitemap.xml`. Then Google News Publisher Center.

Then tick PLAN items 49 and 50.

## Phase 14: Running it

**Deploy an update** (after it's tested locally and tagged):

```bash
ssh ledger 'cd /srv/ledger && sh docker/backup.sh && git fetch --tags && git checkout vX.Y.Z && sed -i "s|^APP_VERSION=.*|APP_VERSION=vX.Y.Z|" .env.production && docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build'
```

**Roll back:** check out the previous tag and run the same `up -d --build`; if
the bad release changed the database, restore the backup taken just before it
(`restore.sh`, confirm first).

**Look at logs:** `ssh ledger 'cd /srv/ledger && docker compose -f docker-compose.prod.yml --env-file .env.production logs --tail 100 web worker'`

**Routine:** server security updates install themselves; monthly: restore
drill on a copy, check R2 has 30 days of backups, `sudo apt upgrade` and a
reboot in a quiet hour; renew the Hostinger plan and domains before they
expire (auto-renew on). Incidents: `docs/DEPLOYMENT.md` section 12.

**Moving to another provider later:** new server → phases 4, 5, 9.2–9.5 →
`restore.sh` with the latest backup → change the Cloudflare `A` records to the
new IP → cancel the old server after a few days.
