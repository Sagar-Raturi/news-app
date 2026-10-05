# DECISIONS.md

Choices made where the brief was ambiguous. One line each: choice — reason.

- Site name "The Ledger" (placeholder, set in `SiteSettings`) — the brief gave no name; easy to change in admin.
- Django 5.2 LTS + Wagtail 7.0 LTS (not Wagtail 8.0) — long-term-support pair, mature APIs, lower upgrade risk for phase 1.
- Sections are Wagtail pages under the homepage and articles are their children — gives clean URLs (`/economy/<slug>/`) and makes "section" the parent page, so it cannot be inconsistent.
- Article type is a choice field on ArticlePage (not separate page models) — one template and one workflow; type changes styling/labels only.
- Authors are a snippet with optional link to a Wagtail user, ordered via an inline (multiple bylines) — authors can exist without logins (columnists, guest writers).
- Author, tag and search pages are plain Django views, not Wagtail pages — they are listings derived from data, nothing for editors to edit.
- Tag pages live at `/tags/<slug>/`, author pages at `/authors/<slug>/`.
- "About & AI policy" is a single StandardPage at `/about/` with an `#ai-policy` anchor — the brief names one page.
- Compiled Tailwind CSS is committed — `docker compose up` works without a Node build step; `npm run build:css` regenerates it.
- Accent colour is a deep sindoor/terracotta (#B4441C) — Indian identity, distinct from The Economist red and The Hindu blue; used only for kickers, rules and drop caps.
- Fonts loaded from Google Fonts (Source Serif 4 + Inter) with system serif/sans fallbacks — per the design brief; avoids vendoring font files.
- Demo articles avoid fabricated quotes from real named people (roles instead) and link only to top-level official sites — realistic without inventing statements by real persons.
- Hero images for demo articles are generated abstract illustrations (Pillow) — no licensing issues, no network needed at seed time.
- Wagtail's default "Moderators" group and "Moderators approval" workflow are removed/deactivated by `bootstrap_site`; "Writers" and "Editors" groups with permissions scoped to the home page replace them — the brief names exactly two roles.
- Workflow is a single "Editor review" group-approval task — draft → review → publish maps 1:1; Editors keep publish rights so they can publish their own copy or urgent corrections directly.
- Opinion section is hidden from homepage section blocks (`show_on_homepage=False`) because opinion and editorials get their own homepage rail.
- AI policy anchor is `/about/#our-ai-policy` (auto-generated from the "Our AI policy" heading) rather than a hand-set `#ai-policy` — headings get slug ids automatically, so editors don't manage anchors.
- JSON-LD uses `@type: NewsArticle` for every article type (type exposed via `genre`) — the brief asks for NewsArticle and it is the type Google's news features document best.
- Google News sitemap lists only articles from the last 48 hours (per Google's guidance); everything else is in `/sitemap.xml`, which also lists author and tag pages.
- Added an RSS feed at `/feed/` — tiny cost, expected of a news site.
- The Wagtail Site's hostname/port are synced from `SITE_BASE_URL` by `bootstrap_site` so canonical URLs and sitemaps carry the right origin (incl. `:8000` locally).
- Demo logins are admin/admin, editor/editor, writer/writer (created only by `seed_demo`, which Docker runs when `SEED_DEMO=1`) — easy to try the workflow locally; documented as dev-only.
- `seed_demo` leaves one draft waiting in "Editor review" so the publishing workflow can be tried immediately.
- Seeded articles get backdated publish times (0–9 days) so the homepage, "Latest" rail and Google News sitemap look like a live site.
- Docker image has no apt packages; a `wait_for_db` management command replaces `pg_isready` — faster builds, fewer moving parts. Entrypoint is run via `sh` so it works even if the executable bit is lost (bind mounts, Windows checkouts).
