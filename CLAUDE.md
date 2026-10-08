# CLAUDE.md — project conventions

Analysis-led Indian news website ("The Ledger" working title): news plus
analysis, explainers, opinion and editorials.

## Stack
- Python 3.12 (Docker) / 3.11+ locally, Django 5.2 LTS, Wagtail 7.0 LTS
- PostgreSQL 16 (Wagtail database search backend = Postgres full-text)
- Celery + Redis: runs the AI agents (`newsdesk.tasks`); restart the worker
  after Python changes (`docker compose restart worker`)
- Django templates + HTMX 2 + Tailwind CSS 4 (compiled CSS is committed)
- Docker Compose for local development

## Layout
```
config/            settings.py (env-driven), urls.py, celery.py, wsgi.py
core/              StandardPage (About & AI policy), site settings, navigation
                   template tags, newsroom roles/workflow setup, management
                   commands (bootstrap_site, seed_demo), celery tasks
news/              HomePage, SectionPage, ArticlePage, Author snippet, tags,
                   StreamField blocks, author/tag/search views, sitemaps, SEO
newsdesk/          AI desk agents (phase 2): DeskAgent + DeskFeedback (desk
                   memory), ArticleNote (per-article memory), DraftRequest
                   commissions, prompts, Claude writer, Celery task,
                   review-comment capture, Wagtail admin viewsets and screens
templates/         base.html, includes/, news/, core/, search/
static/src/        Tailwind source (main.css) — edit this, then rebuild
static/css/site.css  compiled Tailwind output (committed; do not hand-edit)
static/js/         vendored htmx.min.js
docker/            entrypoint script
```

## Commands
- Run everything: `docker compose up --build` → http://localhost:8000
- Tests: `docker compose run --rm web python manage.py test`
  (locally: `python manage.py test` with `DATABASE_URL` pointing at Postgres)
- Rebuild CSS: `npm install && npm run build:css` (or `npm run watch:css`)
- Re-seed demo content: `python manage.py seed_demo --reset`
- Newsroom roles + workflow (idempotent): `python manage.py bootstrap_site`

## Conventions
- Settings come from environment variables only (`config/settings.py`); never
  hard-code secrets. Defaults are safe for local dev.
- Page models live in `news/models.py` / `core/models.py`; StreamField blocks in
  `news/blocks.py`. Keep templates per page type in `templates/<app>/`.
- Sections are `SectionPage`s directly under the `HomePage`; articles are
  `ArticlePage`s under a section (so the section is the parent page).
- An article's display date is `published_date`, auto-filled from
  `first_published_at` on first publish (see `ArticlePage.save`).
- Any change to structure (page tree, groups, workflow) goes through the
  idempotent `bootstrap_site` command so tests and Docker share one code path.
- Tailwind: utility classes in templates; shared component classes in
  `static/src/main.css` under `@layer components`. Rebuild and commit
  `static/css/site.css` after changing classes.
- HTMX is used for progressive enhancement only — every HTMX endpoint must
  also work as a normal full-page request.
- Tests live in `<app>/tests/`. Every model, the workflow and every public
  page needs a test. Run the full suite before each commit.
- Commits: small, one PLAN.md item per commit, imperative subject line.
- Ambiguities: pick the sensible default and log it in DECISIONS.md.
- AI desk agents never publish and never write opinion/editorials; their drafts
  are AI-assisted and go through Editor review.
- Agent memory has two scopes: desk memory (DeskFeedback, system prompt,
  cached) and article notes (ArticleNote, user message, one article). Review
  comments become article notes; only an editor promotes one to a desk rule. Tests must not call the real
  Anthropic API (mock the client or use NEWSDESK_WRITER=fake).
- Demo content must not invent quotes or claims attributed to real, named
  living people; use roles ("a senior finance ministry official") instead.

## AI newsroom direction (phase 3, set by the owner)
- Agents do the work: they **suggest topics** (topic scout) and **research,
  write and edit** articles. The human editor's job is to **approve and
  publish**, with optional feedback. Design every flow so the default is
  "agents propose, editor clicks approve"; nothing publishes without that click.
- Writing style is **highly personal**, decided as: a strong, recognisable
  voice in the spirit of The Economist's named columns — confident, witty,
  warm, talks to the reader ("you"), vivid images, takes a clear line — but
  never "I" and never invented experiences, quotes or encounters. The voice
  belongs to the publication. Lives in the house style
  (`newsdesk/roles.py` → `DEFAULT_HOUSE_STYLE`, editable in admin).
- No Anthropic API key yet: develop, test and demo with `NEWSDESK_WRITER=fake`.
  Every agent role needs offline fake output (`newsdesk/pipeline/fake.py`).

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
