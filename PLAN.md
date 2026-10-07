# PLAN.md — Phase 1 checklist

Work top to bottom. Tick each item when done and commit.

- [x] 1. Project docs: CLAUDE.md, PLAN.md, DECISIONS.md
- [x] 2. Django + Wagtail project skeleton: requirements, env-driven settings,
      Postgres, Celery app + Redis config, URLs, .gitignore
- [x] 3. Docker: Dockerfile, docker-compose.yml (db, redis, web, worker),
      entrypoint that migrates, bootstraps and seeds
- [x] 4. Content models: HomePage, SectionPage, ArticlePage (type, standfirst,
      authors, tags, hero, StreamField body, sources, published date,
      AI-assisted flag), Author snippet, tags, StandardPage; migrations
- [x] 5. Model tests (page hierarchy, defaults, published date, authors, tags)
- [x] 6. `bootstrap_site` command: page tree (home, 9 sections, About & AI
      policy), Writer/Editor groups + permissions, "Newsroom review" workflow
- [x] 7. Workflow tests (writer can't publish, submit → editor approves →
      live, editor can reject; admin views)
- [x] 8. Frontend tooling: Tailwind 4 build (package.json, main.css), vendored
      HTMX, base layout (masthead, section nav, footer)
- [x] 9. Page templates: homepage (top stories + section blocks), section
      page (HTMX load more), article page, StandardPage
- [x] 10. Author pages, tag pages, search (HTMX live results)
- [x] 11. SEO: Open Graph/Twitter tags, canonical, NewsArticle JSON-LD,
      sitemap.xml, Google News sitemap, robots.txt
- [x] 12. Page/view tests (home, section, article, author, tag, search, about,
      sitemaps, structured data)
- [x] 13. Demo seed: `seed_demo` command, generated hero images, ~20 articles,
      authors, About & AI policy content, demo users (writer/editor/admin)
- [x] 14. Seed tests + full test run; code review pass and fixes
- [x] 15. Verify `docker compose up` end-to-end from README; screenshots/smoke
      check of every page
- [x] 16. README (setup, roles, workflow how-to) and final summary

# Phase 2 — AI desk agents

One writing agent per desk (section). Each desk has a style guide and a
feedback memory; drafts are written by Claude from editor-supplied material,
saved as AI-assisted drafts and submitted to Editor review. Agents never publish.

- [x] 17. `newsdesk` app: DeskAgent (style guide, model, effort), DeskFeedback
      (memory notes, per article type), DraftRequest (brief, sources, status,
      usage); migrations; anthropic SDK dependency and settings
- [x] 18. Prompt builder (house rules + desk style + desk memory, cached) and
      structured ArticleDraft schema
- [x] 19. Writers: Anthropic writer (structured output, refusal fallback,
      error handling) and an offline "fake" writer for demos/tests
- [x] 20. Draft → ArticlePage conversion (safe HTML, source-URL guard, byline,
      AI disclosure) and submission to Newsroom review
- [x] 21. Celery task + enqueue on commission; failure handling
- [x] 22. Feedback capture: "Request changes" comments on AI drafts become
      desk memory automatically
- [x] 23. Wagtail admin: "Newsdesk" menu (desks with inline memory,
      commissions list/inspect), permissions for Writers/Editors, desks created
      by bootstrap_site, demo feedback in seed_demo
- [x] 24. Tests for all of the above (no real API calls); full suite green
- [x] 25. Docker/README/DECISIONS updates; verify end to end in Docker

## Phase 2b — "Revise with AI"

An editor (or the draft's writer) can send an agent's draft back to the same
desk agent with instructions; the agent rewrites that draft as a new revision
of the same article and it returns to Editor review.

- [x] 26. Revision commissions (revision_of + instructions); prompt carries the
      current draft (latest revision, incl. manual edits) and the instructions;
      fake writer supports revisions
- [x] 27. Apply a revision to the existing article (new page revision, slug,
      byline and image kept) and resubmit to review; Celery task branch
- [x] 28. Admin: "Revise with AI" button on the article's edit screen and a
      form prefilled with the latest "Request changes" comment; permissions
- [x] 29. Tests, README/DECISIONS, Docker verification

## Phase 2c — Article notes (per-article memory)

Instructions meant for one article stay with that article; only what an
editor chooses becomes a desk rule.

- [x] 30. ArticleNote model (per-article memory) and "special instructions" on
      commissions; "Request changes" comments become article notes instead of
      desk memory; promoting a note to a desk rule
- [x] 31. Prompts: special instructions in first drafts, all active article
      notes in every revision; fake writer shows them
- [x] 32. Admin: "Article notes" screen (add, forget, make desk rule),
      header button, notes on the Revise form plus an "also remember for the
      desk" tickbox, special instructions on the commission form
- [x] 33. Tests, README/DECISIONS/CLAUDE updates, end-to-end check
