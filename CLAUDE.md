# CLAUDE.md — project conventions

Analysis-led Indian news website ("The Ledger" working title): news plus
analysis, explainers, opinion and editorials.

## Stack
- Python 3.12 (Docker) / 3.11+ locally, Django 5.2 LTS, Wagtail 7.0 LTS
- PostgreSQL 16 (Wagtail database search backend = Postgres full-text)
- Celery + Redis (configured, no real tasks yet — `core.tasks.ping` only)
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
- Demo content must not invent quotes or claims attributed to real, named
  living people; use roles ("a senior finance ministry official") instead.
