# CLAUDE.md — project conventions

"The Ledger" (working title): an analysis-led Indian news publication sold as a
**paid product**. AI agents suggest topics and research, write and edit articles;
a human editor approves and publishes. Some articles are free, others are behind
a **paywall**; readers have their own **accounts**. Shipping plan:
`docs/DEPLOYMENT.md` (deployment playbook).

## Stack
- Python 3.12 (Docker) / 3.11+ locally, Django 5.2 LTS, Wagtail 7.0 LTS
- PostgreSQL 16 (Wagtail database search backend = Postgres full-text)
- Celery + Redis: runs the AI agents (`newsdesk.tasks`); restart the worker
  after Python changes (`docker compose restart worker`)
- Django templates + HTMX 2 + Tailwind CSS 4 (compiled CSS is committed)
- Anthropic Python SDK (Claude Opus 5.5 by default; models are set per agent in admin)
- Docker Compose for local development; production plan in `docs/DEPLOYMENT.md`

## Layout
```
config/            settings.py (env-driven), urls.py, celery.py, wsgi.py
core/              StandardPage (About & AI policy), site settings, navigation
                   template tags, newsroom roles/workflow setup, management
                   commands (bootstrap_site, seed_demo), celery tasks
news/              HomePage, SectionPage, ArticlePage, Author snippet, tags,
                   StreamField blocks, author/tag/search views, sitemaps, SEO
newsdesk/          The AI newsroom
  models/          topics, workspace (ArticleWorkspace, ArticleVersion,
                   ArticleSession, SessionMessage, InlineComment), research
                   (Source, Finding, FactCheckFlag), runs (AgentRun/Step/Event),
                   agents (AgentDefinition, ModelPrice, NewsroomAISettings),
                   desks (phase 2: DeskAgent, DeskFeedback, ArticleNote, DraftRequest)
  pipeline/        llm.py (the only Claude call site), runner.py (runs a plan
                   step by step), context.py (per-article prompts), drafts.py,
                   schemas.py, fake.py (offline agents), events.py
  roles.py         starter agents, house style, model prices (seeded by bootstrap_site)
  workspace_views.py, jobs.py, approval.py, pagesync.py, versions.py, diff.py,
                   rendering.py — the admin "AI articles" workspace
  views.py, writer.py, prompts.py, publishing.py — phase 2 commission flow
                   (being retired into the workspace; see PLAN.md item 39)
templates/         base.html, includes/, news/, core/, search/, newsdesk/
static/src/        Tailwind source (main.css) — edit this, then rebuild
static/css/site.css  compiled Tailwind output (committed; do not hand-edit)
static/js/         vendored htmx.min.js
docker/            entrypoint script
docs/              DEPLOYMENT.md (playbook), screenshots
```

## Commands
- Run everything: `docker compose up --build` → http://localhost:8000
  (admin at /admin/, demo logins in README; AI articles under Newsdesk AI)
- Tests: `docker compose run --rm web python manage.py test`
  (locally: `python manage.py test` with `DATABASE_URL` pointing at Postgres)
- After Python changes the web server reloads itself; the worker does not:
  `docker compose restart worker`
- Rebuild CSS: `npm install && npm run build:css` (or `npm run watch:css`)
- Re-seed demo content: `python manage.py seed_demo --reset`
- Site structure, roles, agents, prices (idempotent): `python manage.py bootstrap_site`

## Product direction (set by the owner)
- **Agents do the work, the editor approves.** Agents suggest topics (topic
  scout, with ready briefs) and research, write, fact-check and edit. The
  editor's job is approve and publish, with optional feedback. Default every
  flow to "agents propose, editor clicks approve"; nothing publishes without
  that click.
- **Voice: highly personal**, meaning a strong, recognisable publication voice in
  the spirit of The Economist's named columns — confident, witty, warm, talks
  to the reader ("you"), vivid images, takes a clear line — but never "I" and
  never invented experiences, quotes or encounters. Lives in the house style
  (`newsdesk/roles.py` → `DEFAULT_HOUSE_STYLE`, editable in admin).
- **Paid product with a paywall.** Every article is either free or for
  subscribers (plus a monthly allowance of free premium reads for registered
  readers). Payments via Razorpay (cards and UPI AutoPay) — Stripe is
  invite-only for Indian businesses.
- **Reader accounts.** Readers sign up and log in on the public site (email +
  password, optional Google sign-in). Readers are not newsroom staff and never
  get Wagtail admin access.
- **Images: real, licensed, never repeated.** Prefer real photographs from
  licensed sources (wire/agency subscription when available; Pexels and
  Wikimedia Commons meanwhile), always stored with photographer, source,
  licence and credit. No image is used for more than one article. Never
  AI-generated images presented as photographs; a generated illustration must
  be labelled as one.
- **No Anthropic API key yet:** develop, test and demo with
  `NEWSDESK_WRITER=fake`. Every agent role needs offline fake output
  (`newsdesk/pipeline/fake.py`).

## Conventions
- Settings come from environment variables only (`config/settings.py`); never
  hard-code secrets. Defaults are safe for local dev; production must set
  `DJANGO_DEBUG=0` and every variable listed in `docs/DEPLOYMENT.md`.
- Page models live in `news/models.py` / `core/models.py`; StreamField blocks in
  `news/blocks.py`. Keep templates per page type in `templates/<app>/`.
- Sections are `SectionPage`s directly under the `HomePage`; articles are
  `ArticlePage`s under a section (so the section is the parent page).
- An article's display date is `published_date`, auto-filled from
  `first_published_at` on first publish (see `ArticlePage.save`).
- Any change to structure (page tree, groups, workflow, agents, prices) goes
  through the idempotent `bootstrap_site` command so tests, Docker and
  production share one code path.
- Tailwind: utility classes in templates; shared component classes in
  `static/src/main.css` under `@layer components`. Rebuild and commit
  `static/css/site.css` after changing classes.
- HTMX is used for progressive enhancement only — every HTMX endpoint must
  also work as a normal full-page request.
- Tests live in `<app>/tests/`. Every model, the workflow and every public
  page needs a test. Run the full suite before each commit.
- Commits: small, one PLAN.md item per commit, imperative subject line.
- Ambiguities: pick the sensible default and log it in DECISIONS.md.
- AI agents never publish and never write opinion/editorials; their articles
  are AI-assisted and are approved and published by an editor in the workspace.
- Everything an agent sees comes from one article's workspace
  (`newsdesk/pipeline/context.py`); never mix in other articles' data. The
  only shared context is the house style and the section's guidelines/memory.
- Claude is called only through `newsdesk/pipeline/llm.py`. Tests must not call
  the real Anthropic API (use `ScriptedCaller`, a mocked client, or
  NEWSDESK_WRITER=fake).
- Demo content must not invent quotes or claims attributed to real, named
  living people; use roles ("a senior finance ministry official") instead.

## Paywall, accounts and money (rules for when these are built)
- Never send premium text to a reader who isn't entitled to it: truncate on
  the server, not with CSS or JavaScript. Mark paywalled articles with Google's
  paywalled-content structured data (`isAccessibleForFree: false` + `hasPart`
  with a `.paywall` class selector) so it isn't treated as cloaking.
- Pages that depend on who is logged in must not be cached by the CDN.
- Subscription state changes only from verified payment webhooks (signature
  checked, idempotent, every event stored); never trust the browser's word
  that a payment succeeded.
- Store no card or UPI details ourselves; the payment provider holds them.
- Readers can export and delete their data (DPDP Act); collect only what the
  product needs, with clear consent.

## Design direction
Serious editorial newspaper look (spirit of The Economist / The Hindu, own identity).
- Type: **Source Serif 4** for headlines and article body (`font-serif`),
  **Inter** for UI text — nav, labels, bylines, buttons (`font-sans`).
- One accent colour (`accent`, deep sindoor/terracotta) used sparingly:
  kickers, the masthead rule, active states, drop caps. Everything else is ink
  on paper (near-black on warm off-white) with greys.
- Thin rule lines (`border-rule`) between stories; no cards, shadows or rounded
  boxes for story lists.
- Homepage: multi-column grid (1 col mobile → 12-col grid on desktop).
- Article: narrow readable column (~680px), standfirst under the headline,
  drop cap on the first paragraph, pull quotes; body uses the Tailwind
  typography plugin (`prose`), customised in `static/src/main.css`.
- Mobile-first: write base classes for small screens, add `md:`/`lg:` up.
