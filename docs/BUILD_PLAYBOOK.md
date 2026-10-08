# Build playbook — what's built, what's next, and how to build it

The working guide for continuing development, written so a new session (or a
new developer) can pick up without the chat history. Read with:

- `CLAUDE.md` — conventions and product rules (always applies)
- `PLAN.md` — the checklist; tick items as they land, one item per commit
- `DECISIONS.md` — why things are the way they are
- `docs/specs/ai-article-workspace.md` — the owner's original brief
- `docs/DEPLOYMENT.md` — shipping: production, accounts, paywall, payments, legal

Contents

1. Where things stand
2. Resuming work (commands)
3. How the AI newsroom works today
4. Invariants — don't break these
5. Remaining work, item by item
6. Testing patterns
7. Known gotchas
8. Check-ins with the owner

---

## 1. Where things stand

| Phase | State |
|---|---|
| 1 — Site (Wagtail news site, SEO, demo content) | Done |
| 2 — Desk agents (commission → draft → review, article notes) | Done; being retired into the workspace at item 39 |
| 3 — AI article workspace | Items 34–38 done (data model, workspace page, background runs, approve/publish, live activity feed, the full eight-agent pipeline with fact-check fix loop). Next: 38a (topic scout) |
| 4 — Ship it (production, accounts, paywall, payments, images, ads, live blog, legal) | Planned in `PLAN.md` and `docs/DEPLOYMENT.md` |

The owner has **no Anthropic API key yet**: everything is built and demoed with
`NEWSDESK_WRITER=fake`. Every new agent role must have fake output.

## 2. Resuming work

```bash
cd news-app
docker compose up -d --build                     # db, redis, web (:8000), worker
docker compose exec web python manage.py migrate  # if you added migrations
docker compose exec web python manage.py bootstrap_site
docker compose restart worker                     # after ANY Python change (Celery doesn't reload)
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py test            # full suite
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py test newsdesk   # faster
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py makemigrations newsdesk -n <name>
```

- Admin: http://localhost:8000/admin/ — demo logins `editor`/`editor`,
  `writer`/`writer`, `admin`/`admin` (dev only). AI articles: Newsdesk AI → AI articles.
- `.env` (git-ignored) must keep `NEWSDESK_WRITER=fake` until the owner buys a key.
- `RUN_MIGRATIONS=0` on `docker compose run` skips the entrypoint's migrate +
  bootstrap (needed when models changed but migrations don't exist yet).
- Commit after each PLAN item with an imperative subject and the
  `Co-Authored-By` trailer; run the full suite first.

## 3. How the AI newsroom works today

### Data (newsdesk/models/)
- `Topic` → has many `ArticleWorkspace` (the spec's "Article": brief fields,
  status, `current_version`, `approved_version`, `published_version`, OneToOne
  `page` → `news.ArticlePage`).
- `ArticleVersion`: immutable; `body` is raw StreamField JSON with stable block
  ids; `source_numbers` (cited, in order); `tags`; `seo`; `origin` agent/human;
  `page_revision` (Wagtail revision it was saved as).
- `ArticleSession` (1:1 workspace; `summary`, `summarised_through`) and
  `SessionMessage` (role editor/orchestrator/agent/system, `status` for
  feedback open/addressed/dismissed, `pinned` = applies to every revision).
- `InlineComment`: version, `anchored_version`, `block_id`, `start`/`end`,
  `quote`, `prefix`/`suffix`, `status` open/sent/resolved, `outdated`.
- `Source` (per-workspace `number`, cited as `[S3]`), `Finding` (research note
  tied to a source), `FactCheckFlag` (version, block, claim, severity, status
  open/fixed/dismissed).
- `AgentRun` (kind generate/revise, status, plan JSON, usage + cost;
  partial unique constraint = one active run per workspace), `AgentStep`
  (role, agent, model, instructions, output JSON incl. working draft, usage,
  cost, attempts), `AgentEvent` (activity feed lines).
- `AgentDefinition` (one per role; prompt, model, effort, max_tokens, web
  tools, active, `customised`), `ModelPrice`, `NewsroomAISettings` (house
  style, summarise threshold, recent messages kept, max fix rounds, search fee).
- Starter agents/prompts/house style/prices: `newsdesk/roles.py`, created by
  `bootstrap_site` (`core/newsroom.py`); uncustomised agents get prompt updates.

### Flow
```
Generate (workspace_views.generate)
  → jobs.start_run()  [IntegrityError → ArticleBusy]  → on_commit: tasks.run_agents.delay
  → Pipeline(run).execute()                 newsdesk/pipeline/runner.py
      import_page_edits(); record_editor_sources()
      plan = make_plan()                     [plan] → the orchestrator's step_plan appends the real steps
      for each plan item (plan can grow):   handler = AgentSteps.step_<task>(step, draft) -> draft
          tasks: plan, research, analyse, outline, write, revise, edit, fact_check, seo (pipeline/steps.py)
          planning.validate(): only active agents; new drafts always write, in order; fact_check
              inserted after the last text change; fix loop inserts revise + fact_check (max_fix_rounds)
          self.call(step, role, messages, output_format=PydanticModel)
              → caller.call(AgentRequest)    llm.AnthropicCaller | fake.FakeCaller | fake.ScriptedCaller
              → usage + cost on step and run (F() updates)
          step.output["draft"] saved after each step (resume point)
      finish(): versions.create_version() → pagesync.sync_page() (page revision, never published)
                → save_flags(): latest fact-check that saw the final text → FactCheckFlag rows;
                  no fact-check this run → carry flags on unchanged blocks from the previous version
                → SessionMessage from orchestrator → workspace.refresh_status()
  TransientAgentError → task retries at 30s/2m/5m from the failed step
  AgentError → fail(): saves any finished draft as a version, run failed, "Retry" button
```
- Working draft = dict with version fields (`pipeline/drafts.py`);
  `drafts.finish()` strips citations to unknown sources and normalises
  `[S#]` spacing; `same_content()` compares visible text only.
- Prompts: `pipeline/context.py` — `build_system(agent, workspace)` = role
  prompt + (for STYLE_ROLES) house style + section guidelines + desk memory,
  all cached; user messages built from `brief_block`, `sources_block`,
  `draft_block` (blocks as `[B1] (paragraph) text` so agents refer to B-refs).
- Approve/publish/unpublish: `newsdesk/approval.py` (approval is for one
  version; publish imports hand edits first; serious flags block approval;
  `accept_flag` view dismisses a flag).
- Page sync: `newsdesk/pagesync.py` (`[S#]` ↔ numbered links `[1]` on the page;
  hand edits in Wagtail become "human" versions).
- UI: `newsdesk/workspace_views.py`, URLs in `wagtail_hooks.ArticlesViewSet`
  (namespace `newsdesk_articles:`), templates in `templates/newsdesk/workspace/`,
  CSS/JS in `newsdesk/static/newsdesk/`.
- Live feed: `pipeline/events.emit()` stores an `AgentEvent` and publishes it on
  Redis channel `newsdesk:ws:<id>`; streamed text is published in chunks
  (`TextBuffer`), not stored. `newsdesk/live.py` is an async SSE view at
  `/newsdesk/live/<id>/events/?after=<last event id>` (outside the Wagtail
  admin URLs, own permission check) that replays stored events then relays
  Redis. `workspace.js` subscribes while a run is active, appends lines and
  text, redraws the activity panel on step changes and reloads on `run_end`.
  The 2 s HTMX polling pauses while the stream is connected (`window.ndLive`).
  The web container runs uvicorn (ASGI) with polling file watching.

## 4. Invariants — don't break these

1. Agents never publish. Approval is per version; any newer version needs re-approval.
2. Everything an agent sees comes from one workspace (plus house style and
   section guidelines). Session isolation has tests — keep them passing.
3. Claude is called only via `pipeline/llm.py`; tests never hit the network.
4. Every role has fake output in `pipeline/fake.py` (FakeCaller) so the whole
   product works with `NEWSDESK_WRITER=fake`.
5. Revisions edit blocks by id; untouched blocks stay byte-identical (this is
   what keeps comment anchors and diffs meaningful).
6. Citations are `[S#]` to workspace sources only; unknown numbers are stripped.
7. Model output is plain text, escaped by our code — never raw HTML from a model.
8. One active run per workspace (DB constraint); feedback during a run waits.
9. No opinion/editorials by AI; no first person or invented experiences.
10. Premium text never reaches non-entitled readers (when the paywall lands).

## 5. Remaining work, item by item

Each item: what to build, where it plugs in, tests, done when. Numbers match `PLAN.md`.

### 37. Live progress (SSE) — done
- **Build:** `config/asgi.py`; serve web with uvicorn in Docker
  (`uvicorn config.asgi:application --reload --host 0.0.0.0 --port 8000` in
  dev; gunicorn + uvicorn workers in prod). Add `uvicorn[standard]` to requirements.
- `pipeline/events.publish()` → Redis pub/sub channel `newsdesk:ws:<id>`
  (use `redis` client from `CELERY_BROKER_URL`); persisted `AgentEvent`s stay.
  Writer text deltas: publish only (not persisted), throttled (~every 250 ms).
- Async view `newsdesk_articles:events` (`StreamingHttpResponse` with an
  async generator): on connect, replay `AgentEvent`s after `Last-Event-ID`,
  then relay pub/sub; heartbeat every 15 s; permission check like `detail`.
- `workspace.js`: `EventSource`; append lines to the running step's
  `[data-step-events]`, live text into `[data-step-stream]`, update the status
  badge; on `run_finished` reload. Keep the 2 s HTMX polling as fallback when
  EventSource fails (and for tests).
- **Tests:** publish called with the right channel/payload (mock redis);
  events view replays persisted events and requires login.
- **Done when:** clicking Generate in fake mode shows lines appearing without polling.

### 38. Full multi-agent pipeline + fact-checker — done
Built as specified below: `pipeline/planning.py`, `pipeline/steps.py`,
schemas in `pipeline/schemas.py`, `drafts.apply_edits()`, fake outputs for
all eight roles, tests in `newsdesk/tests/test_pipeline.py`. Revision runs
(kind=revise with a `trigger` SessionMessage) already plan from the
feedback; item 39 adds the chat UI around them.

- **Orchestrator** (`step_plan`, runs first): output schema `Plan { message_to_editor,
  steps: [{task: research|analyse|outline|write|revise|edit|seo, instructions,
  blocks: [B-refs]}] }`. Code validates: only active agents; content-changing
  steps are always followed by `fact_check` (code appends it — the orchestrator
  doesn't plan it); first draft default plan if the orchestrator fails:
  research → analyse → outline → write → fact_check → edit → seo.
- **Researcher** (`step_research`): tools = `server_tools(agent)` (web_search +
  web_fetch `_20260209`) + client tool `record_finding` (strict schema: kind,
  text, detail, url, title, publisher) → `Source.record()` + `Finding`. Also
  record every URL from `web_search_tool_result` blocks the agent cites.
  Summary = counts + gaps note. Honour `sources_to_avoid` (pass as
  instructions; optionally `blocked_domains`).
- **Analyst** (`step_analyse`): schema `Analysis { thesis, context, perspectives
  [{view, evidence [S#]}], implications, uncertainties }` → step.output.
- **Outliner** (`step_outline`): schema `Outline { headline_options[], dek,
  sections [{heading, points[], sources[], words}], extras[] }`.
- **Writer** (`step_write`, exists): add analysis + outline to its message.
- **Fact-checker** (`step_fact_check`): input = draft with B-refs + sources +
  findings + editor-accepted claims (dismissed flags); schema `FactCheck {
  verdict, flags [{block, claim, severity, issue, suggestion, sources[]}] }`.
  Persist flags on the version created at the end (store in step.output, create
  `FactCheckFlag` rows in `finish()` against the new version); earlier open
  flags of older versions don't carry over. If high flags and fix rounds <
  `max_fix_rounds`: insert `revise` (writer, targeted at flagged blocks) +
  `fact_check` steps into the plan and continue. Still-open high flags →
  status "Needs attention" (exists in `compute_status`).
- **Editor** (`step_edit`) and **targeted revise** (`step_revise`): schema
  `BlockEdits { edits: [{op: replace|insert_after|delete, block: B-ref,
  new_block: DraftBlock|null}], headline?, standfirst?, notes }`; apply in
  `pipeline/drafts.apply_edits()`. Untouched blocks are left exactly as they
  are; a replaced block keeps its id (so comments re-anchor if the quoted text
  survives); inserted blocks get new ids.
- **SEO** (`step_seo`): schema `Seo { headline_options[], headline, meta_description,
  slug, tags[] }` → draft headline/tags/seo.
- **Fake outputs** for every role in `FakeCaller` (deterministic, labelled demo).
- **Tests (LLM mocked with ScriptedCaller):** full plan order; orchestrator
  plan validated (fact-check appended); fix loop runs at most N rounds; high
  flags keep status attention; researcher findings → sources; block edits keep
  untouched blocks identical; resume after failure mid-pipeline; salvage draft.
- **Done when:** fake Generate shows 8+ steps in activity, a draft with sources
  and flags; a run with a scripted high flag ends in "Needs attention".

### 38a. Topic scout (core)
- `step_scout` / task `scout_section(desk_id)`: scout agent with web search,
  schema `Suggestions { topics: [{title, why_now, angle, article_type, brief,
  must_include, sources[{url,title}]}] }`; pass the section's recent topics
  and articles (titles only) to avoid repeats; create `Topic(status=suggested,
  origin=agent, scout_notes=...)` and keep the proposed brief (add
  `Topic.proposed_brief` JSONField).
- Celery beat schedule (daily per active desk, configurable in
  `NewsroomAISettings`); "Suggest topics now" button per section.
- Admin queue: Topics list filtered to Suggested with **Accept & generate**
  (creates workspace from the proposed brief and starts a run) and **Reject**.
- Tests: suggestions stored, duplicates skipped, accept creates workspace +
  run, reject marks rejected; fake output.

### 38b. Live blog (new)
- **Models:** `news.LiveBlogPage` (Page under a section: standfirst, status
  live/ended, `key_points` StreamField or text, `coverage_start/end`) and
  `news.LiveUpdate` (blog FK, body (paragraph/embed/image blocks), sources,
  `published_at`, `pinned`, `label` breaking/confirmed/unconfirmed/analysis,
  `status` draft/approved/published, created_by agent/human).
- **Public page:** newest-first updates with timestamps and per-update anchors,
  pinned on top, "N new updates" via SSE/HTMX polling, key developments box,
  ad slots every few updates for free readers, "This live blog has ended".
  `LiveBlogPosting` JSON-LD (`coverageStartTime`, `coverageEndTime`,
  `liveBlogUpdate`). Free (not paywalled).
- **Live desk agent:** every N minutes (beat or self-rescheduling task while
  live) searches for new developments since the last update, drafts short
  sourced updates and refreshes key points; never repeats an update.
- **Approval queue** in admin, mobile-friendly, one click per update (approve /
  edit / discard); nothing publishes without it. Rules: attribution on every
  claim, "unconfirmed" label for single-source reports, no graphic content,
  casualty figures attributed.
- Tests: page renders, ordering, pinned, JSON-LD, agent drafts go to queue
  not live, approve publishes, ended state.

### 39. Feedback chat + targeted revisions; retire phase 2
- Feedback tab form → `SessionMessage(role=editor, status=open, pinned?)`;
  starts a `revise` run (or queues if busy: open messages are picked up by the
  next run). Orchestrator plans from the message(s) + open inline comments.
- **Context assembly** (`pipeline/context.session_block`): pinned + open
  editor messages verbatim; last `keep_recent_messages` turns verbatim; older
  turns via `ArticleSession.summary` (summariser agent when estimated tokens >
  `summarise_after_tokens`; update `summarised_through`). Brief, latest draft,
  sources always verbatim.
- After the run: addressed messages → `addressed`; orchestrator reply message
  linked to the new version (diff link in the chat).
- **Isolation tests:** two workspaces with feedback; prompts for A contain
  nothing of B (assert on ScriptedCaller.requests).
- **Retire phase 2:** remove Commission a draft / Revise with AI / Article
  notes screens, signals and hooks; data migration: each original
  `DraftRequest` with an article → Topic + ArticleWorkspace (brief from
  brief/instructions/source material, page linked, version 1 imported from the
  page's latest revision); active `ArticleNote`s → pinned editor messages.
  Keep `DeskAgent`/`DeskFeedback` (section guidelines + memory). Delete
  writer.py/prompts.py parts no longer used (keep `TYPE_GUIDANCE`).

### 40. Inline comments
- JS: on text selection inside `.nd-block`, show "Comment" button; compute
  block id, quote, 32-char prefix/suffix, offsets in the block's text (use the
  same text as `content.block_text`); POST → `InlineComment`.
- Draft view highlights anchored comments (wrap ranges client-side), sidebar
  list with Send now / Add to next feedback / Resolve.
- **Re-anchoring** (`newsdesk/anchoring.py`, run in `create_version`): for each
  open/sent comment on the previous version: same block id and quote found →
  update offsets (prefer the match nearest the old offset, disambiguate with
  prefix/suffix); quote found in another block → move; else `outdated=True`
  (keep quote). Comments sent with a run whose blocks changed → `resolved`.
- Tests: anchors survive untouched blocks, move with edits elsewhere in the
  block, go outdated when the passage is rewritten or the block deleted.

### 41. Admin-editable agents and style
- Snippet viewsets: AgentDefinition (form sets `customised=True` on change;
  role not editable; required roles can't be deactivated), ModelPrice;
  NewsroomAISettings is already a Wagtail setting (Settings menu) — check the
  house style panel; DeskAgent edit = section guidelines (rename labels).
- Model field: free text with suggestions (datalist of ModelPrice models).
- Permissions: editors only. Tests for each.

### 42. Cost/usage polish
- Per-article totals in list and top bar; per-run breakdown in activity;
  monthly spend report (admin report view); warn when a run exceeds a
  configurable budget.

### 43–50. Shipping
Fully specified in `docs/DEPLOYMENT.md` section 5 (production hardening,
reader accounts, paywall, subscriptions, images, trust pages, staging,
launch). Extra item:

### 45a. Ads for free readers (new)
- Ad slots (in-article after paragraph N, between live updates, sidebar on
  desktop) rendered only for readers who are not subscribers; lazy-loaded,
  fixed-height containers (no layout shift); `ads.txt` served from site
  settings; consent banner for EEA/UK visitors (Google-certified CMP); site
  setting to switch ads off globally; start with AdSense, plan for Ad Manager.
- Tests: subscriber sees no ad markup; free reader does; ads.txt served.

## 6. Testing patterns

- Base fixtures: `newsdesk/tests/base.py` (`WorkspaceTestCase`: bootstrap,
  writer/editor users, `make_topic`, `make_workspace`, `make_version`,
  `paragraph()`, `heading()`).
- Pipeline: `ScriptedCaller({"writer": [FullDraft(...), AgentError(...)]},
  usage={...})`; run `Pipeline(run, caller=caller).execute()`; inspect
  `caller.requests` for prompts (isolation tests).
- Celery: `mock.patch("newsdesk.jobs._enqueue")` to queue without running;
  to run end to end: `mock.patch("newsdesk.tasks.run_agents.delay",
  side_effect=lambda pk: run_agents.apply(args=[pk]))` inside
  `captureOnCommitCallbacks(execute=True)`; patch
  `newsdesk.pipeline.runner.get_caller` to inject a ScriptedCaller.
- Real-client tests: `newsdesk/tests/test_llm.py` (`FakeStream`, `client_with`).
- Views: Wagtail turns `PermissionDenied` into a redirect to the dashboard —
  assert the outcome, not a 403.

## 7. Known gotchas

- **Celery doesn't auto-reload:** `docker compose restart worker` after Python edits.
- **Windows shell + non-ASCII:** heredoc Python patch scripts mangle characters
  like `•` or `—`; use the Edit tool, or run scripts with `PYTHONUTF8=1` from a file.
- **Stale objects:** `create_version` locks and re-reads the workspace; it
  syncs the caller's instance — follow that pattern. Read `page.live` from the
  DB (`workspace.page_is_live()`), not a cached `workspace.page`.
- **StreamField raw data:** ListBlock items come back as
  `{"type": "item", "value": ...}` dicts (`content.list_items`); Draftail adds
  `data-block-key` to paragraphs — compare visible text (`visible_signature`).
- **Wagtail colour tokens:** `-50` shades are light backgrounds, `-100` are
  strong colours.
- **Agent prompts in the DB:** changing `roles.py` updates only agents with
  `customised=False` (on `bootstrap_site`).
- **Desktop app browser pane** opens written HTML/template files as tabs;
  close them; it can't run `confirm()` dialogs reliably — test publish via tests.

## 8. Check-ins with the owner

Stop and report (what's built, how to try it, decisions needed) after:
- item 38 (full pipeline with fact-checker),
- item 40 (inline comments),
- item 38b (live blog) and 47 (images), and before any production deploy.
Ask before: spending money (real API runs), changing the public AI policy,
deleting data, or deploying.
