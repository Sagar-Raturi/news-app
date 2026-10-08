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
  (`/search/`, live HTMX results), About (`/about/`), AI policy, corrections, contact, grievance redressal (complaint form), terms and privacy pages.
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
- **Special instructions for this article** (optional): rules for this piece
  only, e.g. "keep it under 600 words". They are saved as the article's first
  note and followed on every revision.
- **Source material**: paste notes, statements, report extracts, data and links.
  The agent is told to use **only** this material, and links it didn't get
  from you are stripped.

The draft appears under the desk's section a minute or so later, in Editor
review, with the commissioning writer's byline (or the desk's default author).
The commission's detail page shows the agent's **notes for the editor**
(claims to check, gaps in the material) and token usage.

### Revise with AI

When an agent's draft needs work, the editor clicks **Request changes** and
writes what's wrong. Then, on the article's edit screen, choose **Revise with
AI**. It's in the green save/publish menu at the bottom, and in the "⋯" menu
next to the title. The form is prefilled with your latest comment; adjust it
and submit.

The same desk agent rewrites the draft as a **new revision of the same
article**. It gets your instructions, the article's notes from earlier rounds,
the current text (including any edits made by hand), the original brief and
source material, and the desk's memory. The slug, byline and image are kept.
A minute or so later the article is back in **Editor review** with the revised
text; the old version stays in the page's *History*.

Editors also see a tickbox, **"Also remember this for all future … drafts"**.
Tick it only when the instruction is a lesson for the whole desk; leave it
unticked for anything about this one article.

Who can use it: editors, and the draft's own writer once changes have been
requested. Not available for published articles or human-written ones, or
while the agent is already working on that draft.

### Memory: desk rules and article notes

The agent's instructions are layered, from the widest to the narrowest:

```
House rules (whole newspaper)
  └─ Desk style guide + desk memory (every draft from this desk)
       └─ Desk memory for one type (e.g. Economy *news* only)
            └─ Article notes (this article only, every revision)
                 └─ This revision's instructions
```

**Desk memory**: *Newsdesk AI → Desk agents → (desk)* (editors):

- **Style guide**: standing instructions for that desk.
- **Memory: feedback for this desk**: add notes. Leave *Article type* blank
  for "always", or pick one (e.g. only for Politics *analysis*). Untick
  *Active* to make the agent forget a note.

Only that desk's agent sees its memory. Politics feedback never reaches the
Economy agent.

**Article notes**: on an agent's draft, open the **⋯** menu next to the title
and choose **Article notes** (editors, and the draft's writer):

- Added automatically: the commission's special instructions, every
  **Request changes** comment, and every **Revise with AI** instruction.
- **Add note** for anything else about this article.
- **Forget** stops the agent seeing a note (**Remember again** undoes it).
- **Make desk rule** (editors) copies a note into the desk's memory for that
  article type, when it turns out to apply to every future draft.

Article notes never reach other articles or the desk's memory unless an
editor promotes them. Comments that were saved to desk memory before this
change are still there; untick any that were really about one article.

### Model and cost

Desks default to Claude Opus 5.5 with *high* effort; editors can switch a
desk to Claude Sonnet 5.5 (cheaper, faster). A typical draft costs roughly
$0.10–0.30 on Opus 5.5, depending on length and how much material you paste.
Repeated drafts from the same desk reuse cached instructions, which lowers the
cost. Usage per draft is shown on each commission.

How it works in code: `newsdesk/prompts.py` (house rules + desk style +
memory), `newsdesk/writer.py` (Claude call with structured output),
`newsdesk/publishing.py` (draft → article in review, revisions),
`newsdesk/views.py` ("Revise with AI" and "Article notes" screens),
`newsdesk/tasks.py` (Celery job), `newsdesk/signals.py` (review comments →
article notes).

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
- `PLAN.md` — checklists for phase 1 and the AI desk agents (2, 2b, 2c)
- `DECISIONS.md` — choices made where the brief was ambiguous
