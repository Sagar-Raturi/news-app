# Deployment playbook — The Ledger

How to take The Ledger from this repository to a live, paid news product, and
how to run it afterwards. It is written for the owner and whoever operates the
site. Sections marked **(to build)** describe work that is planned in
`PLAN.md` but not in the code yet; everything else describes what exists.

Contents

1. What we are shipping
2. Decisions to make first
3. Production architecture
4. Running costs
5. Engineering work before launch
6. Business, legal and compliance checklist
7. Accounts and services to set up
8. Configuration (environment variables)
9. First deployment, step by step
10. Go-live checklist
11. Day-to-day operations
12. Incident runbook
13. References

---

## 1. What we are shipping

| Area | At launch |
|---|---|
| Public site | Homepage, sections, articles, authors, tags, search, RSS, sitemaps, Google News sitemap (built) |
| AI newsroom | Topic scout suggests topics with briefs; agents research, write, fact-check and edit; the editor approves and publishes in the "AI articles" workspace (phase 3, partly built) |
| Reader accounts | Sign up, log in, verify email, reset password, optional Google sign-in, account page, data export and deletion **(to build)** |
| Paywall | Each article is free or for subscribers; registered readers get a few free premium reads a month; premium text is never sent to readers who aren't entitled **(to build)** |
| Subscriptions | Monthly and annual plans in rupees, paid by card or UPI AutoPay through Razorpay; renewals, cancellation, receipts **(to build)** |
| Images | Real, licensed photographs with credits; never the same image on two articles **(to build)** |
| Trust pages | Terms, privacy, refund and cancellation, contact and grievance officer, corrections, AI policy **(to build / update)** |

Launch is ready when every box in section 10 is ticked.

## 2. Decisions to make first

Recommendations are what this playbook assumes. Change any of them before the
build starts; log the outcome in `DECISIONS.md`.

| # | Decision | Recommendation | Why |
|---|---|---|---|
| 1 | Brand and domain | Decide the final name (The Ledger is a placeholder), run a trademark search, buy the `.com` and `.in` | The name appears in the site settings, emails, payment pages and Google News |
| 2 | Hosting | One virtual machine (Docker Compose) + managed PostgreSQL, in an Indian region (DigitalOcean Bengaluru or AWS Mumbai) | Cheapest setup that is still reliable; the database, the only thing you can't lose, is managed and backed up by the provider. Low latency for Indian readers |
| 3 | Payments | Razorpay Subscriptions (cards, UPI AutoPay) | Stripe accepts new Indian businesses by invitation only; Razorpay supports Indian recurring payments natively |
| 4 | What is free | News and explainers free; analysis for subscribers; the editor can override per article; registered readers get 3 free premium articles a month | Free news brings readers in from search and social; the analysis is what people pay for |
| 5 | Prices | Monthly and annual plans in INR (annual at roughly 10× monthly) | Set the actual prices yourself after looking at comparable Indian publications |
| 6 | Login methods | Email + password, plus "Sign in with Google" | Covers almost everyone; Google sign-in removes password friction |
| 7 | Images | Pexels and Wikimedia Commons now; a wire/agency photo subscription (PTI, ANI, Reuters or Getty) once revenue allows | Free, real, licensed photos today; news-event photos of real people need a wire service |
| 8 | Transactional email | Amazon SES (Mumbai) or Postmark | Verification, password reset and receipts must arrive reliably |
| 9 | Staff security | Two-factor authentication for every staff account | Admin accounts can publish to the whole site |
| 10 | AI models | Start every agent on Claude Opus 5.5; move research, outlining, SEO and summaries to Sonnet 5.5 if costs are high | Quality first; each agent's model can be changed in the admin without a deploy |

## 3. Production architecture

```
                       Readers / editors
                              │  HTTPS
                     ┌────────▼────────┐
                     │   Cloudflare    │  DNS, TLS, CDN for static files and media,
                     │                 │  firewall. Never caches logged-in pages.
                     └────────┬────────┘
                              │
 ┌────────────────────────────▼─────────────────────────────┐
 │  VM (Ubuntu 24.04, Docker Compose)                       │
 │                                                          │
 │  caddy ──► web: gunicorn + uvicorn workers (ASGI)        │
 │            Django + Wagtail, public site, admin, SSE     │
 │                                                          │
 │  worker: celery — AI agent runs, emails                  │
 │  beat:   celery beat — topic scout schedule,             │
 │          subscription expiry checks                      │
 │  redis:  Celery broker, cache, live event channel        │
 └──────┬───────────────────┬──────────────────┬────────────┘
        │                   │                  │
 ┌──────▼──────┐   ┌────────▼───────┐   ┌──────▼─────────────┐
 │ Managed     │   │ Object storage │   │ External services  │
 │ PostgreSQL  │   │ (S3/Spaces):   │   │ Anthropic API,     │
 │ backups +   │   │ images, media  │   │ Razorpay, email,   │
 │ point-in-   │   │ (versioned)    │   │ Pexels/Wikimedia,  │
 │ time restore│   └────────────────┘   │ Sentry             │
 └─────────────┘                        └────────────────────┘
```

Notes

- **web** runs as ASGI so the live agent activity feed (server-sent events)
  doesn't tie up a worker per viewer. Static files are served by WhiteNoise
  (already configured) and cached by Cloudflare.
- **Media** (images) moves from the container's disk to object storage, so
  the VM can be rebuilt at any time without losing anything.
- **Redis** holds nothing that can't be rebuilt (queue, cache, live events),
  so a container is fine; switch to a managed Redis when you add a second VM.
- **Scaling later:** add a second web VM behind a load balancer, move Redis to
  a managed service, and run workers on their own VM. Nothing in the code
  assumes a single machine except the Compose file.
- **Staging:** run a second, smaller copy of the same stack (its own database
  and bucket, Razorpay in test mode, `NEWSDESK_WRITER=fake` or a low-budget
  key) and deploy there first.

## 4. Running costs

Rough monthly figures to plan with. Check each provider's current pricing
before committing.

| Item | Approx. per month |
|---|---|
| VM, 2 vCPU / 4 GB (production) | US$24–48 |
| Managed PostgreSQL, smallest production tier with backups | US$15–60 |
| Object storage + transfer | US$5–10 |
| Staging (small VM + small database) | US$20–30 |
| Cloudflare, Sentry, uptime monitoring | Free tiers to start |
| Transactional email | Under US$20 at launch volumes |
| Domain names | About ₹2,000 a year |
| Razorpay | A percentage of each payment plus GST; see Razorpay's pricing page |
| **Claude API** | **The biggest variable.** Expect roughly US$1–3 per article for a full research + write + fact-check + edit run on Opus 5.5, and US$0.10–0.50 per revision. At 5 articles a day that is about US$150–450 a month. The workspace shows the real cost of every run |

Set a monthly spend limit for the API key in the Claude Console, and review
per-article costs in the workspace for the first few weeks.

## 5. Engineering work before launch

These map to `PLAN.md` (items 37–50). Recommended order: finish the AI
newsroom, harden for production, then accounts, paywall, payments, images and
the trust pages. Accounts, paywall, payments and images can all be built and
tested without an Anthropic API key (`NEWSDESK_WRITER=fake`).

### 5.1 Finish the AI newsroom (PLAN items 37–42)
- [ ] Live activity feed (SSE) in the workspace
- [ ] Full agent pipeline: orchestrator, researcher (web search), analyst,
      outliner, writer, fact-checker loop, editor, headline & SEO
- [ ] Topic scout as a core feature: scheduled and on-demand suggestions with
      ready briefs, accept/reject queue
- [ ] Feedback chat with targeted revisions; inline comments
- [ ] Agents, house style, section guidelines and prices editable in admin
- [ ] Retire the phase 2 commission screens

### 5.2 Production hardening (PLAN item 43)
- [ ] `docker-compose.prod.yml`: caddy, web (gunicorn + uvicorn workers, no
      code volume mount), worker, beat, redis; health checks; restart policies
- [ ] `config/asgi.py`; the image's default command becomes gunicorn, never
      `runserver`
- [ ] Settings: `DEBUG` off by default when `DJANGO_ENV=production`;
      HSTS, secure cookies, `SECURE_SSL_REDIRECT`, referrer policy, CSRF
      trusted origins; Redis cache; `SERVER_EMAIL`/`ADMINS`
- [ ] Media in object storage (`django-storages`), served via the CDN
- [ ] Real email backend (SMTP or SES) for verification, receipts and workflow mail
- [ ] Sentry for web and Celery errors; structured logs
- [ ] `/healthz/` endpoint (database + Redis check) for uptime monitoring
- [ ] Celery: late acknowledgement, time limits for agent tasks, `beat` schedule
- [ ] `seed_demo` refuses to run in production; demo logins removed
- [ ] Staff two-factor authentication
- [ ] Rate limiting on login, sign-up and password reset

### 5.3 Reader accounts (PLAN item 44)
- [ ] `django-allauth`: email login, email verification, password reset,
      Google sign-in
- [ ] Readers and staff kept apart: readers never get admin access; staff log
      in at `/admin/`, readers at `/account/login/`
- [ ] Account page: profile, subscription, receipts, newsletter preferences
- [ ] Data export and account deletion (DPDP Act)
- [ ] Masthead shows "Log in / Subscribe" or the reader's account menu

### 5.4 Paywall (PLAN item 45)
- [ ] `ArticlePage.access` (free / subscribers), defaulted by article type and
      set by the editor in the AI workspace before publishing
- [ ] Server-side truncation: non-entitled readers get the headline,
      standfirst and first paragraphs, then the subscribe prompt; the rest of
      the text is never in the HTML
- [ ] Metered allowance for registered readers (default 3 premium articles a
      month, configurable in site settings)
- [ ] Google paywalled-content structured data (`isAccessibleForFree: false`,
      `hasPart` → `.paywall`) in the article's NewsArticle JSON-LD
- [ ] RSS, sitemaps and search results never contain premium body text
- [ ] Cache rules: article pages vary by login; Cloudflare bypasses cache when
      the session cookie is present

### 5.5 Subscriptions and payments (PLAN item 46)
- [ ] Models: `Plan`, `Subscription` (status, period end, provider IDs),
      `PaymentEvent` (every webhook stored, processed once)
- [ ] Razorpay Subscriptions checkout (cards, UPI AutoPay), test mode first
- [ ] Webhook endpoint with signature verification; entitlement changes only
      from verified webhooks; daily reconciliation task
- [ ] Renewal, failed-payment grace period, cancellation (access until period
      end), refunds per the published policy
- [ ] Receipt and GST invoice emails; subscription reports in the admin

### 5.6 Images (PLAN item 47)
- [ ] Image metadata: source (Pexels, Wikimedia, wire, upload, illustration),
      source ID, photographer, licence, source URL, credit line
- [ ] "Picture editor" agent: searches Pexels and Wikimedia Commons from the
      article's subject, checks candidates by looking at them (Claude vision),
      proposes the best one with a caption; the editor approves it with the article
- [ ] Never repeated: unique source ID, perceptual-hash check against every
      image already used, and one live article per image (enforced on publish)
- [ ] Credits shown under every image; licence stored for audits
- [ ] Rules: no stock photos of identifiable people next to sensitive stories
      (crime, illness, poverty); real events and public figures need wire or
      properly licensed Wikimedia photos; generated illustrations only as a
      last resort and labelled "Illustration"
- [ ] Replace the generated demo images in `seed_demo`

> Unsplash requires its images to be hotlinked from its servers and a
> download ping per use; Pexels and Wikimedia allow storing the file, which
> fits Wagtail better. Check each provider's current terms before launch.

### 5.7 Trust pages and policy (PLAN item 48)
- [ ] Terms of use, Privacy policy, Refund and cancellation policy (with
      concrete timelines), Contact (legal name, address, phone, email)
- [ ] Grievance officer details and complaint form (IT Rules 2021)
- [ ] Corrections policy (exists on About) and a visible corrections note on
      corrected articles
- [ ] AI policy rewritten for agent-written articles: what agents do, that
      an editor approves every article, how images are sourced
- [ ] Consent notice for analytics and newsletters

## 6. Business, legal and compliance checklist

Not code, but launch depends on it. Take advice from a lawyer and a chartered
accountant; this list is a starting point, not legal advice.

- [ ] **Legal entity** (private limited company or LLP), PAN, current account
- [ ] **GST**: digital subscriptions are taxable; ask your CA about
      registration and invoicing (including readers outside India)
- [ ] **Payment gateway KYC**: Razorpay checks your website for terms,
      privacy, refund/cancellation policy (with timelines) and a contact page
      with a real address before activating live payments
- [ ] **IT Rules 2021, Part III (digital news publishers)**: follow the
      Norms of Journalistic Conduct, furnish your details to the Ministry of
      Information and Broadcasting, appoint an India-based grievance officer
      who decides complaints within 15 days, and join a self-regulatory body.
      A 2026 draft amendment proposes changes; check the current position
- [ ] **DPDP Act 2023 and DPDP Rules 2025**: rules notified in November 2025
      and phasing in over about 18 months (main obligations around May 2027).
      Build consent, data export/deletion and breach response in now rather
      than retrofitting
- [ ] **Copyright**: only licensed images; keep the licence record for each;
      quotes from other publications kept short and attributed
- [ ] **Trademark** for the publication name
- [ ] **Google News**: register in Publisher Center; submit sitemaps in
      Search Console

## 7. Accounts and services to set up

| Service | Used for | Notes |
|---|---|---|
| Domain registrar + Cloudflare | DNS, TLS, CDN, firewall | Point the domain's nameservers to Cloudflare |
| DigitalOcean or AWS | VM, managed PostgreSQL, object storage | Same region for all three |
| Anthropic (Claude Console) | AI agents | Create an API key; set a monthly spend limit; separate keys for staging and production |
| Razorpay | Subscriptions | Test mode keys first; live keys after KYC |
| Amazon SES or Postmark | Transactional email | Verify the sending domain (SPF, DKIM, DMARC) |
| Google Cloud | "Sign in with Google" | OAuth client for the production domain |
| Pexels, Wikimedia | Photos | Free API key for Pexels; Wikimedia needs a descriptive User-Agent |
| Sentry | Error tracking | One project for web + worker |
| Uptime monitor (e.g. UptimeRobot, Better Stack) | Alerts when the site is down | Check `/healthz/` and the homepage |
| GitHub | Code, deploy tags | Protect the main branch |

## 8. Configuration (environment variables)

Production settings live in `/srv/ledger/.env.production` on the server
(mode 600, never committed). Variables in **bold** are new and arrive with
the work in section 5.

| Variable | Example / note |
|---|---|
| `DJANGO_DEBUG` | `0` (defaults to on today: always set it) |
| `DJANGO_SECRET_KEY` | 50+ random characters; different per environment |
| `DJANGO_ALLOWED_HOSTS` | `theledger.in,www.theledger.in` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://theledger.in,https://www.theledger.in` |
| `DJANGO_SECURE_COOKIES` | `1` |
| `SITE_BASE_URL` | `https://theledger.in` (canonical URLs, sitemaps) |
| `WAGTAILADMIN_BASE_URL` | `https://theledger.in` |
| `DATABASE_URL` | `postgres://user:pass@host:25060/ledger?sslmode=require` |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` |
| `ANTHROPIC_API_KEY` | Production key |
| `NEWSDESK_WRITER` | `anthropic` (`fake` on staging if you want no API cost) |
| `NEWSDESK_MAX_TOKENS` | Optional; phase 2 writer limit |
| `DJANGO_EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend` |
| **`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`** | From SES/Postmark |
| **`DJANGO_ENV`** | `production` / `staging` |
| **`AWS_STORAGE_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `MEDIA_CDN_DOMAIN`** | Object storage for images |
| **`SENTRY_DSN`** | Error tracking |
| **`RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`** | Payments |
| **`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`** | Sign in with Google |
| **`PEXELS_API_KEY`** | Photo search |
| `RUN_MIGRATIONS` | `1` on web only, `0` on worker and beat |
| `SEED_DEMO` | Never set in production |

Rules: one set of secrets per environment; rotate any secret that was ever
pasted into chat, a ticket or a commit; keep a copy of the production `.env`
in a password manager, not on a laptop.

## 9. First deployment, step by step

Do this on staging first, then repeat for production.

1. **Server.** Create an Ubuntu 24.04 VM (2 vCPU / 4 GB) in the chosen Indian
   region with SSH-key login only. Then:
   ```bash
   sudo apt update && sudo apt -y upgrade
   sudo apt -y install unattended-upgrades ufw
   sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER
   ```
2. **Database.** Create managed PostgreSQL 16 in the same region and private
   network; enable daily backups and point-in-time recovery; allow
   connections only from the VM; create database `ledger` and an app user.
3. **Storage.** Create a private bucket for media with versioning on, and an
   access key limited to that bucket; put the CDN in front of it.
4. **DNS and TLS.** Add the domain to Cloudflare; `A` record for the apex and
   `www` → the VM's IP (proxied); SSL/TLS mode **Full (strict)**; Caddy
   obtains the origin certificate.
5. **Code.**
   ```bash
   sudo mkdir -p /srv/ledger && sudo chown $USER /srv/ledger
   git clone <repo> /srv/ledger && cd /srv/ledger
   git checkout v1.0.0            # always deploy a tag
   nano .env.production           # section 8; then: chmod 600 .env.production
   ```
6. **Start.**
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
   docker compose -f docker-compose.prod.yml logs -f web   # migrations + bootstrap_site run here
   ```
7. **First users.**
   ```bash
   docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
   ```
   In the admin: create the real editors (Editors group) and writers, set up
   2FA, set the site name and tagline in Settings → Site settings, give each
   section a default author, and review the house style and agents under
   Newsdesk AI.
8. **Content.** Do not run `seed_demo`. Publish the About, AI policy, terms,
   privacy, refund and contact pages. Generate and approve a handful of
   launch articles.
9. **Payments.** In Razorpay test mode: create the plans, set the webhook
   URL (`https://<domain>/payments/razorpay/webhook/`) and secret, buy a test
   subscription, cancel it, check the account page. Switch to live keys only
   after KYC approval.
10. **Smoke test** (section 10), then point real traffic at it.

## 10. Go-live checklist

Site and security
- [ ] `DJANGO_DEBUG=0`; error pages are the site's own 404/500
- [ ] HTTPS everywhere; `http://` and `www` redirect to the canonical domain
- [ ] `/admin/` login works only with 2FA; demo accounts don't exist
- [ ] `https://securityheaders.com` grade A or better
- [ ] Backups on; a test restore has been done (section 11)
- [ ] Sentry receives a test error from web and from the worker
- [ ] Uptime monitor alerts by email/phone

Readers and money
- [ ] Sign up, verify email, log in, reset password, Google sign-in
- [ ] Free article: full text for everyone
- [ ] Premium article logged out: teaser and subscribe prompt; the full text
      is **not** in the page source
- [ ] Metered reads count down and then stop
- [ ] Subscribe (test mode), get access immediately after the webhook,
      receive the receipt; cancel and keep access until the period ends
- [ ] Refund, terms, privacy and contact pages reachable from the footer and
      checkout

Newsroom
- [ ] Topic scout suggests topics; accept one; agents produce a draft with
      sources and fact-check flags; approve; publish; it appears on the
      homepage, section, sitemap and RSS (premium text excluded)
- [ ] Every published image has a credit and is used once
- [ ] API spend limit set; one full run's cost recorded

Search
- [ ] `robots.txt` allows crawling; `sitemap.xml` and `news-sitemap.xml` load
- [ ] Search Console verified, sitemaps submitted; Rich Results Test passes
      on a premium article
- [ ] Google News Publisher Center set up

## 11. Day-to-day operations

### Deploying an update
```bash
cd /srv/ledger
git fetch --tags && git checkout v1.2.0
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```
The web container runs migrations and `bootstrap_site` on start; worker and
beat restart with the new code. Deploy to staging first, smoke test, then
production. Tag every release; write migrations that the previous release can
still run against (add columns before using them; drop them a release later).

### Rolling back
1. `git checkout <previous tag>` and run the same `up -d --build`.
2. If the bad release ran a migration the old code can't handle, restore the
   database to just before the deploy (point-in-time recovery) — this loses
   anything written since, so prefer a fix-forward when possible.

### Backups and restore drill
- Database: managed daily backups + point-in-time recovery (keep at least 7 days).
- Media: bucket versioning.
- Once a month: restore the latest backup into staging and open a few articles
  and the admin. A backup you haven't restored is a hope, not a backup.

### Watching it
| Signal | Where | Act when |
|---|---|---|
| Errors | Sentry | Any new error on checkout, login or the webhook |
| Uptime | Uptime monitor | Any downtime alert |
| Agent runs | Workspace activity tab, Sentry | Several failed runs in a row (often API billing or rate limits) |
| AI spend | Claude Console, workspace costs | Monthly spend heading past the limit |
| Payments | Razorpay dashboard, admin reports | Webhook failures, subscriptions active in Razorpay but not on the site (run reconciliation) |
| Server | Provider dashboard | Disk over 80 %, memory pressure |

### Routine tasks
- Weekly: review the topic scout's queue and fact-check flag rates; check
  failed payments.
- Monthly: restore drill; review AI costs per article and models per agent;
  apply OS updates (`unattended-upgrades` handles security patches) and
  dependency updates on staging first.
- Every 6 months or after anyone leaves: rotate secrets and API keys.

## 12. Incident runbook

| Situation | Do this |
|---|---|
| Site down | Check the uptime alert and `docker compose ps`; `logs web`; restart the service; if the database is down, check the provider's status page |
| A published article is wrong | Unpublish it from the workspace (one click) or correct it and publish a new version with a correction note; log it on the corrections page |
| A legal complaint or takedown request | Grievance officer acknowledges and decides within 15 days; unpublish while reviewing if there is a real risk |
| Agents failing | Activity tab shows the error. "API key rejected" → key or billing; "rate limited" → retries happen automatically; persistent failure → retry the run from the failed step |
| Payment webhooks failing | Razorpay retries automatically; fix the endpoint, then run the reconciliation task so every paying reader has access |
| Secret leaked | Rotate it at the provider, update `.env.production`, `up -d`; review logs for misuse |
| Spam or abuse on sign-up | Tighten rate limits, add a CAPTCHA to sign-up, block offending IP ranges at Cloudflare |

## 13. References

- Stripe accounts are invite-only in India — https://support.stripe.com/questions/stripe-accounts-are-invite-only-in-india
- Razorpay recurring payments with UPI — https://razorpay.com/docs/payments/recurring-payments/upi.md
- Google: structured data for subscription and paywalled content — https://developers.google.com/search/docs/appearance/structured-data/paywalled-content
- DPDP Act brought into force, phased rules (Hogan Lovells) — https://www.hoganlovells.com/en/publications/indias-digital-personal-data-protection-act-2023-brought-into-force-
- IT Rules 2021 overview (Trilegal) — https://trilegal.com/knowledge-repository/information-technology-rules-2021/
- Unsplash API guidelines — https://help.unsplash.com/api-guidelines/unsplash-api-guidelines
- Pexels: what you can do with Pexels photos — https://help.pexels.com/hc/en-us/articles/360042790573-Can-I-sell-photos-or-videos-from-Pexels
