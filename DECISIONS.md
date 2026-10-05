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
- Writers get only Wagtail's `add_page` permission (create, then edit/delete their own drafts); Editors can edit anyone's — stops writers deleting colleagues' drafts in review (found in code review).
- The homepage never repeats a story across top stories, opinion rail, explainers and section blocks; private (view-restricted) articles never appear in listings, sitemaps or tag pages.

## Phase 2 — AI desk agents

- One agent per news desk, as data (DeskAgent: style guide, model, effort) rather than separate programs — one tested code path; editors configure agents in the admin.
- Memory is explicit, editable notes (DeskFeedback) injected into the prompt, scoped to one desk and optionally one article type — predictable, auditable and easy to "forget" (untick), unlike opaque learned memory.
- "Request changes" comments on an agent's draft are saved to that desk's memory automatically — feedback is captured where editors already give it.
- Agents write only news, analysis and explainers; opinion and editorials are blocked in the model, form and prompt — matches the published AI policy.
- Agents must use only editor-supplied material; source URLs not present in that material are removed before saving — guards against invented links.
- Model output is plain text, escaped into rich text by our code — the model can't inject HTML into pages.
- Drafts are saved as the commissioning user and submitted to the existing Newsroom review workflow; byline is the commissioner's author profile, else the desk's default author — a human is accountable for every piece.
- Default model Claude Opus 5.5 at high effort, switchable per desk to Sonnet 5.5; server-side refusal fallback enabled so a safety decline retries on a suitable model instead of failing.
- System prompt is two cached blocks (house rules, then desk style + memory) — repeated drafts from a desk hit the prompt cache.
- Calls run in the Celery worker, never in a web request — drafts take tens of seconds.
- `NEWSDESK_WRITER=fake` produces canned drafts without an API key — lets the flow be demoed and tested offline; tests never call the real API.
- Starter desks and style guides come from `bootstrap_site` (created once, never overwritten), example memory notes from `seed_demo`.

## Phase 2b — Revise with AI

- A revision is a DraftRequest with `revision_of` + `instructions`, reusing the same task, listing and inspect screens — one pipeline for drafts and revisions.
- Revisions rewrite the same article as a new page revision (slug, byline, image kept; history preserved) instead of creating a new article — editors review one story, with Wagtail's revision history as the audit trail.
- The agent receives the latest saved text (including manual edits), the editor's instructions, the original brief and source material, and the desk memory; it returns the complete article, not a patch — simpler and more reliable than partial edits.
- After a revision, a "changes requested" draft resumes review (Wagtail's own resubmit); an open review is cancelled and restarted so the editor reviews the revised text, not the old revision.
- Revision is a deliberate button, not automatic on "Request changes" — each run costs money and the editor may prefer the writer to fix it.
- Available to editors, and to the draft's writer once changes are requested (it's locked to them while in review); never for published or human-written articles, nor while a run is pending.
- Links in a revision are kept only if they appear in the source material or the editor's instructions.
