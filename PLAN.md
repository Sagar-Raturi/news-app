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

# Phase 3 — AI article workspace

Agents research, write and edit; the editor briefs, gives feedback in one
place per article, approves and publishes. Check in with the editor after
items 36, 38 and 40.

- [x] 34. Data model: Topic, ArticleWorkspace (brief, status), ArticleVersion
      (raw StreamField body with stable block ids), ArticleSession +
      SessionMessage, InlineComment, Source / Finding / FactCheckFlag,
      AgentDefinition, ModelPrice, NewsroomAISettings (house style),
      AgentRun / AgentStep / AgentEvent; agents and prices seeded by
      bootstrap_site; permissions; model tests
- [x] 35. Workspace page (static): topics and articles lists, new article
      form, draft view, brief tab, versions tab with diff and restore
- [x] 36. Background job + single-agent generation end to end (Writer),
      version → page revision sync, hand edits imported as versions,
      Approve / Publish / Unpublish (editors) — CHECK IN
- [ ] 37. Live progress: ASGI (uvicorn), Redis pub/sub events, SSE activity
      feed with polling fallback
- [ ] 38. Full pipeline: orchestrator plan, researcher (web search/fetch),
      analyst, outliner, writer, fact-checker loop, editor, SEO; retry a
      failed step — CHECK IN
- [ ] 38a. Topic scout (core, per the owner): scheduled and on-demand topic
      suggestions with ready briefs per section, accept/reject queue,
      accepted topics start generating automatically
- [ ] 39. Feedback chat + targeted block-level revisions; session context and
      summarisation; retire Commission / Revise with AI / Article notes and
      migrate their data into workspaces
- [ ] 40. Inline comments with re-anchoring across versions — CHECK IN
- [ ] 41. Admin: editable agents, house style, section guidelines, prices
- [ ] 42. Cost and usage display, polish, README/DECISIONS/CLAUDE updates,
      full test run

# Phase 4 — Ship it: production, readers, paywall, payments, images

The playbook is `docs/DEPLOYMENT.md` (sections 5, 9 and 10). Items 44–48 can be
built and tested without an Anthropic API key.

- [ ] 43. Production hardening: docker-compose.prod.yml (caddy, gunicorn +
      uvicorn ASGI, worker, beat, redis), production settings (security
      headers, Redis cache, SMTP email, Sentry, logging), media on object
      storage, /healthz/, Celery limits and beat, seed_demo blocked in
      production, staff 2FA, auth rate limits
- [ ] 44. Reader accounts: django-allauth (email login + verification,
      password reset, Google sign-in), account page, readers kept out of the
      admin, data export and deletion
- [ ] 45. Paywall: article access level (free / subscribers) with defaults by
      type and an editor control in the workspace, server-side truncation,
      metered free reads, paywalled-content JSON-LD, feeds and search without
      premium text, cache rules
- [ ] 46. Subscriptions: Plan / Subscription / PaymentEvent, Razorpay
      Subscriptions checkout (cards, UPI AutoPay), verified idempotent
      webhooks, renewals, grace period, cancellation, receipts, reconciliation
- [ ] 47. Images: licence metadata, picture-editor agent (Pexels + Wikimedia
      Commons, vision check), editor approves with the article, never-repeat
      enforcement (source ID, perceptual hash, one article per image), credits,
      real images in seed_demo
- [ ] 48. Trust pages: terms, privacy, refund and cancellation, contact and
      grievance officer, AI policy rewritten for agent-written articles,
      consent notice
- [ ] 49. Staging deployment, smoke tests, restore drill, monitoring alerts
- [ ] 50. Production launch (docs/DEPLOYMENT.md section 10)
