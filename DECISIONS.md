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
- "Request changes" comments on an agent's draft are saved to that desk's memory automatically — feedback is captured where editors already give it. (Superseded in phase 2c: they now become article notes.)
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

## Phase 2c — Article notes

- "Request changes" comments become notes on that article, not desk memory — most review comments are about one story; saving them desk-wide made the agent apply one-off instructions to unrelated drafts.
- An instruction becomes a desk rule only when an editor says so ("Make desk rule", or the tickbox on "Revise with AI") — desk memory is shared by every future draft, so promoting is a deliberate editorial choice; writers can't, as they can't edit desks either.
- Article notes are a separate table with a plain foreign key, not page content (not an InlinePanel) — they are added outside page edits (review signal, Revise form), so storing them in page revisions would let an older revision overwrite them.
- Article notes go in the user message, never the system prompt — the cached desk block stays identical across a desk's drafts.
- Every revision gets all of the article's active notes; on conflict the current instructions win — earlier rounds aren't forgotten, but editors can still change their minds.
- A note already contained in a longer note or in the current instructions is not repeated to the agent — typically a review comment the editor extended in the Revise form; the notes themselves are left untouched.
- Writers can see, add and forget notes on their own drafts even while the draft is locked in review — notes are instructions to the agent, not page content.
- Existing desk-memory notes captured from reviews before 2c are left as they are — removing them silently could lose real lessons; editors can untick them.

## Phase 3 — AI article workspace

- The spec's "Article" is a new `ArticleWorkspace`, not `ArticlePage` — a brief exists before any text, and Wagtail pages need a body and a place in the page tree; the page is created with the first draft and linked one-to-one.
- `ArticleVersion` stores the body as raw StreamField JSON (the same shape as `ArticlePage.body`) and is mirrored to a Wagtail page revision — versions convert both ways without loss, so preview, page history and hand edits in the Wagtail editor keep working.
- StreamField block ids are the unit of revision and of comment anchoring — an agent's revision replaces only the blocks it changes, so untouched passages and the comments on them survive.
- Approval belongs to one version; any newer version needs approving again — an editor never publishes text they haven't approved.
- One active run per article, enforced by a Postgres partial unique constraint — a second Generate or new feedback waits for the next run instead of racing the first.
- Every agent defaults to Claude Opus 5.5; effort varies by role (low for SEO and summaries, high for research, writing and fact-checking) — editors can switch any agent to Sonnet 5.5 in the admin to cut cost.
- Agent settings have effort and max tokens but no temperature — current Claude models reject sampling parameters; effort is the supported control.
- bootstrap_site refreshes the starter prompt of agents nobody has edited (`customised` flag) — prompt improvements reach existing installs without overwriting an editor's work.
- Topics also have a "Rejected" status — so the topic scout doesn't suggest a rejected idea again.
- Per-section auto-publish exists as a read-only setting, always off — nothing publishes without an editor's click in v1.
- Sources are numbered per article and cited in the text as [S3] — citations stay valid across revisions and link claims to sources.
- AI writing of opinion and editorials stays blocked; analysis may argue a thesis.
- Agent runs are a Celery task (`run_agents`); transient API errors (rate limits, overload, network) are retried after 30 s, 2 min and 5 min, resuming from the failed step; other errors fail the run with a "Retry from the failed step" button.
- Each step saves its output (including the working draft) as it finishes — a retry resumes where the run stopped, and if a run fails after a draft was written, that draft is still saved as a version marked as unfinished.
- "Regenerate" writes a completely new draft (new blocks); changing part of a draft is what feedback is for, and the old draft stays in Versions.
- Agent drafts are saved as page revisions but not submitted to the Wagtail "Newsroom review" workflow — the workspace's Approve and Publish (Editors only) replace it for AI articles; human-written articles keep the workflow.
- Edits made to an AI article in the Wagtail page editor are imported as a new "Editor" version the next time the workspace is opened, a run starts, or someone approves or publishes — the workspace never overwrites hand edits, and edits after approval require approving again.
- Versions are compared by visible content, not markup — Draftail re-serialises rich text on save, and a save without changes shouldn't create a version or a diff.
- On the public page, citations [S3] become numbered links ([1], [2]…) to the source, numbered in the order the article cites them; importing a hand edit maps them back.
- Until live streaming lands, the activity panel polls every 2 s while a run is active and reloads the page when it finishes.
- "Highly personal" writing (owner's choice) means a strong publication voice — confident, witty, warm, addressing the reader, taking a clear line — with no first person and no invented experiences; it fits the existing AI policy and the no-opinion rule. bootstrap_site upgrades a house style still on an earlier shipped default and leaves edited ones alone.
- The topic scout moves from "optional" to core and is built straight after the full pipeline — the owner wants agents to propose topics with ready briefs, leaving the editor to approve.

## Phase 4 — Shipping (assumptions in docs/DEPLOYMENT.md, section 2)

- Payments through Razorpay Subscriptions — Stripe takes new Indian businesses by invitation only; Razorpay supports cards and UPI AutoPay mandates.
- Hosting: one Docker Compose VM + managed PostgreSQL + object storage in an Indian region, behind Cloudflare — cheapest reliable start; the database is the only irreplaceable part and it is managed and backed up.
- Paywall default: news and explainers free, analysis for subscribers, editor override per article, 3 free premium reads a month for registered readers — free stories bring readers from search; analysis is what people pay for.
- Premium text is cut on the server, never hidden with CSS/JS, and marked with Google's paywalled-content structured data — no leaks, no cloaking penalty.
- Reader accounts with django-allauth, separate from staff accounts — readers never see the admin.
- Photos from Pexels and Wikimedia Commons (files can be stored, licence recorded) until a wire subscription; Unsplash is skipped because its terms require hotlinking. One image per article, enforced.
- Live blogs are free to read and carry ads; every agent-drafted update needs an editor's approval, even during breaking news — speed comes from a one-click mobile queue, not from skipping review.
- Ads are shown only to readers without a subscription — ad-free reading is part of what subscribers pay for.
