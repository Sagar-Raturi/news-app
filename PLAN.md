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
- [ ] 8. Frontend tooling: Tailwind 4 build (package.json, main.css), vendored
      HTMX, base layout (masthead, section nav, footer)
- [ ] 9. Page templates: homepage (top stories + section blocks), section
      page (HTMX load more), article page, StandardPage
- [ ] 10. Author pages, tag pages, search (HTMX live results)
- [ ] 11. SEO: Open Graph/Twitter tags, canonical, NewsArticle JSON-LD,
      sitemap.xml, Google News sitemap, robots.txt
- [ ] 12. Page/view tests (home, section, article, author, tag, search, about,
      sitemaps, structured data)
- [ ] 13. Demo seed: `seed_demo` command, generated hero images, ~20 articles,
      authors, About & AI policy content, demo users (writer/editor/admin)
- [ ] 14. Seed tests + full test run; code review pass and fixes
- [ ] 15. Verify `docker compose up` end-to-end from README; screenshots/smoke
      check of every page
- [ ] 16. README (setup, roles, workflow how-to) and final summary
