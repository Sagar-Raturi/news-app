---
name: newsroom-build
description: Resume building The Ledger (AI newsroom + paid news site) in a new session. Use when the user asks to continue, pick up where we left off, build the next PLAN.md item, or work on the AI article workspace, agent pipeline, topic scout, live blog, paywall, reader accounts, payments, images, ads or deployment.
---

# Continue building The Ledger

You are continuing a multi-session build. Nothing from earlier chats is
available except what is in the repository, so orient yourself from the files
below before writing code.

## 1. Orient (always, in this order)

1. `CLAUDE.md`: conventions and the owner's product rules.
2. `PLAN.md`: find the first unticked item; that is the next job unless the
   user names another.
3. `docs/BUILD_PLAYBOOK.md`: section 3 (how the code works), section 4
   (invariants), and the section for the item you're building (section 5).
4. `DECISIONS.md`: skim the phase 3/4 entries; don't relitigate them.
5. For shipping items (43+): `docs/DEPLOYMENT.md`. For the original brief:
   `docs/specs/ai-article-workspace.md`.
6. `git log --oneline -15` and `git status`: confirm where work stopped
   (an uncommitted, half-finished item is possible).

## 2. Ground rules

- **No API key:** build and demo with `NEWSDESK_WRITER=fake`. Every new agent
  role gets deterministic fake output in `newsdesk/pipeline/fake.py`. Never
  run real Anthropic calls; tests use `ScriptedCaller` or mocked clients.
- **Agents propose, the editor approves.** Nothing publishes without an
  editor's click. No AI opinion/editorials, no first person, no invented
  experiences or quotes.
- One PLAN item per commit; full test suite green before committing; log any
  judgement call in `DECISIONS.md`; tick the PLAN item.
- Restart the Celery worker after Python changes (`docker compose restart worker`).
- Prefer the Edit tool over shell heredocs for files with non-ASCII text (Windows encoding).

## 3. Build loop for one item

1. Re-read the item's spec in `docs/BUILD_PLAYBOOK.md` section 5. If the
   item is ambiguous in a way that changes what you build, ask the user; if
   not, choose the sensible default and log it.
2. Models → migration (`docker compose run --rm -e RUN_MIGRATIONS=0 web python
   manage.py makemigrations <app> -n <name>`) → services → views/templates →
   fake outputs → tests.
3. Run the app's tests, then the full suite:
   `docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py test`.
4. Apply to the dev stack: `docker compose exec web python manage.py migrate`,
   `... bootstrap_site`, `docker compose restart worker`.
5. Check it in the browser (admin login `editor` / `editor`, dev only) with
   the fake agents: http://localhost:8000/admin/newsdesk/articles/.
6. Update `PLAN.md` (tick), `DECISIONS.md`, and `docs/BUILD_PLAYBOOK.md`
   section 1 ("Where things stand") and section 3 if the architecture changed.
7. Commit (imperative subject; end the message with the Co-Authored-By trailer
   the session gives you).

## 4. Check in with the owner

Stop and report after the milestones in `docs/BUILD_PLAYBOOK.md` section 8
(full pipeline, inline comments, live blog, images, before any deploy): what
was built, how to try it in fake mode, and decisions needed. Always ask
before spending money, changing the public AI policy, deleting data or
deploying.
