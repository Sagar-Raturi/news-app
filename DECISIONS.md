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
