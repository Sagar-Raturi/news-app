# The Ledger

An analysis-led Indian news website — news, analysis, explainers, opinion and
editorials — built with Django 5.2, Wagtail 7.0, PostgreSQL, HTMX and Tailwind CSS.
Celery + Redis are wired up for future background jobs.

Screenshots: [homepage](docs/screenshots/final-home-desktop.png) ·
[article on mobile](docs/screenshots/final-article-mobile.png)

## Quick start (Docker)

Requires Docker with Compose v2.

```bash
git clone <this repo> news-app && cd news-app
docker compose up --build
```

Then open:

| URL | What |
|---|---|
| http://localhost:8000/ | The site (seeded with ~20 demo articles) |
| http://localhost:8000/admin/ | Wagtail newsroom admin |

The first start takes a minute: the `web` container waits for Postgres, runs
migrations, runs `bootstrap_site` (sections, roles, workflow) and then
`seed_demo` (demo content), all automatically. Later starts skip the seed.

### Demo logins (local development only)

| Username / password | Role | Can do |
|---|---|---|
| `writer` / `writer` | Writer | Create and edit articles, submit them for review. Cannot publish. |
| `editor` / `editor` | Editor | Review, approve (publish) or request changes; publish directly; manage authors and site settings. |
| `admin` / `admin` | Superuser | Everything. |

Change or delete these before exposing the site anywhere.

## Trying the publishing workflow

Workflow: **draft → Editor review → published**, implemented with Wagtail's
workflows ("Newsroom review", one "Editor review" task assigned to the Editors
group, applied to the whole site).

1. Sign in as **editor**. The dashboard shows one article already waiting for
   review: *“Monsoon session at the halfway mark…”*. Open it and choose
   **Approve and Publish** (or **Request changes**) from the button menu at the bottom.
2. Sign in as **writer**, go to *Pages → Economy → Add child page → Article*,
   fill in headline, standfirst, an author and some body text, then choose
   **Submit to Newsroom review** (there is no Publish option for writers).
3. Sign back in as **editor** and approve it. It appears on the homepage and in
   the Economy section.

Workflow notifications are emailed; in development they are printed to the
`web` container's log.

## What's in it

- **Sections:** Politics, International, Local, Economy, Society, Education,
  Health, Science & Tech, Opinion (Wagtail pages under the homepage).
- **Article types:** News, Analysis, Explainer, Opinion, Editorial.
- **Article fields:** headline, standfirst, ordered author(s), section (the
  parent page), type, tags, hero image + caption/credit, StreamField body
  (paragraphs, headings, images, pull quotes, key points, Q&A, key figures,
  fact boxes, embeds, tables), sources/references, published date, AI-assisted
  flag with a disclosure note.
- **Pages:** homepage (curated top stories, opinion rail, latest, explainers,
  section blocks), section pages (type filter, HTMX “load more”), article pages,
  author pages (`/authors/<slug>/`), tag pages (`/tags/<slug>/`), search
  (`/search/`, live HTMX results), About & AI policy (`/about/`).
- **SEO:** Open Graph + Twitter cards, canonical URLs, `NewsArticle` JSON-LD
  (plus `WebSite` and `ProfilePage`), `/sitemap.xml` (pages, authors, tags),
  Google News sitemap at `/news-sitemap.xml` (last 48 hours), `/robots.txt`,
  RSS at `/feed/`.

Top stories are curated in the admin on the homepage (*Pages → The Ledger →
Top stories*); empty slots fall back to the latest articles. Site name,
tagline, Twitter handle, default share image and the demo-content notice are
under *Settings → Site settings*.

## AI desk agents (phase 2)

Each news desk (Politics, Economy, Health, …) has its own **AI writing agent**:
a style guide plus a **memory** of editors' feedback. Agents write drafts from
material you supply; every draft is flagged *AI-assisted* and goes to **Editor
review**. Agents never publish, and never write opinion or editorials.

### Setup

1. Get an API key from the Anthropic Console (https://platform.claude.com/).
2. Copy `.env.example` to `.env` (next to `docker-compose.yml`) and set
   `ANTHROPIC_API_KEY=...`. `.env` is git-ignored.
3. Restart: `docker compose up --build`.

No key yet? Set `NEWSDESK_WRITER=fake` in `.env` to try the whole flow with
canned drafts (no API calls, no cost).

### Commissioning a draft

*Newsdesk AI → Commission a draft* (writers and editors):

- **Desk**: picks the agent (and the section the draft is filed in).
- **Type**: news, analysis or explainer.
- **Brief**: the story and angle you want.
- **Source material**: paste notes, statements, report extracts, data and links.
  The agent is told to use **only** this material, and links it didn't get
  from you are stripped.

The draft appears under the desk's section a minute or so later, in Editor
review, with the commissioning writer's byline (or the desk's default author).
The commission's detail page shows the agent's **notes for the editor**
(claims to check, gaps in the material) and token usage.

### Teaching a desk (memory)

*Newsdesk AI → Desk agents → (desk)* (editors):

- **Style guide**: standing instructions for that desk.
- **Memory: feedback for this desk**: add notes. Leave *Article type* blank
  for "always", or pick one (e.g. only for Politics *analysis*). Untick
  *Active* to make the agent forget a note.
- **Automatic memory**: when an editor chooses **Request changes** on an
  agent's draft and writes a comment, that comment is saved to the desk's
  memory for that article type.

Every note a desk has is included in its agent's instructions on every draft,
and only that desk's agent sees it. Politics feedback never reaches the
Economy agent.

### Model and cost

Desks default to Claude Opus 5.5 with *high* effort; editors can switch a
desk to Claude Sonnet 5.5 (cheaper, faster). A typical draft costs roughly
$0.10–0.30 on Opus 5.5, depending on length and how much material you paste.
Repeated drafts from the same desk reuse cached instructions, which lowers the
cost. Usage per draft is shown on each commission.

How it works in code: `newsdesk/prompts.py` (house rules + desk style +
memory), `newsdesk/writer.py` (Claude call with structured output),
`newsdesk/publishing.py` (draft → article in review), `newsdesk/tasks.py`
(Celery job), `newsdesk/signals.py` (review comments → memory).

## Common commands

```bash
docker compose run --rm web python manage.py test        # run the test suite
docker compose run --rm web python manage.py seed_demo --reset   # reload demo content
docker compose run --rm web python manage.py bootstrap_site      # repair sections/roles/workflow
docker compose run --rm web python manage.py createsuperuser
docker compose down -v                                    # stop and wipe the database
```

### Front-end (Tailwind)

The compiled stylesheet `static/css/site.css` is committed, so Node is not
needed to run the site. After changing template classes or `static/src/main.css`:

```bash
npm install
npm run build:css          # or: npm run watch:css
# or, without local Node:
docker compose --profile css up tailwind
```

### Running without Docker

Needs Python 3.11+, PostgreSQL and (optionally) Redis.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgres://newsapp:newsapp@localhost:5432/newsapp
python manage.py migrate && python manage.py bootstrap_site && python manage.py seed_demo
python manage.py runserver
```

## Configuration

All settings come from environment variables (see `config/settings.py`):
`DATABASE_URL`, `CELERY_BROKER_URL`, `DJANGO_DEBUG`, `DJANGO_SECRET_KEY`,
`DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `SITE_BASE_URL`
(public origin used for canonical URLs and sitemaps), `WAGTAILADMIN_BASE_URL`.

## Project docs

- `CLAUDE.md` — conventions and layout
- `PLAN.md` — phase 1 checklist
- `DECISIONS.md` — choices made where the brief was ambiguous
