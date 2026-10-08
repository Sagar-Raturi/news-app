# Spec: AI Article Workspace (owner's brief, 2026-10-07)

The owner's original requirements for phase 3, kept verbatim in substance so
later sessions build against the real brief. Decisions taken since then
override details here — see "Changes since the brief" at the end, and
DECISIONS.md.

## Context
An AI-assisted news analysis platform in the spirit of The Hindu, The
Economic Times and The Economist, focused on analysis and viewpoints, not just
reporting. Sections include Politics, International, Local, Economy, Society,
Education and Health.

AI agents and subagents do almost all of the writing. The human editor's role
is minimal:
1. Create or pick a topic.
2. Write a short prompt (the brief) in the admin panel.
3. Agents research, write and edit the article.
4. If the editor has feedback, they give it on the same page and the AI revises.
5. The editor approves and publishes.

## 1. Topics
- Title, section/category, optional description, status (suggested /
  accepted / in progress / published / archived), created_by (human or agent).
- Created manually in the admin.
- A "Topic Scout" agent suggests topics (news searches, trending items) into a
  "Suggested" queue the editor accepts or rejects.
- One topic can have one or more articles.

## 2. The Article Workspace (the core)
Each article has one admin page where everything happens.
- Main area: the current draft, rendered: headline, standfirst/dek, body, sources.
- Sidebar tabs:
  - **Brief:** the prompt plus settings (section, target length, tone,
    angle/viewpoint, audience, must-include points, sources to use or avoid).
  - **Agent activity:** live pipeline progress, which agent is running, what it
    is doing, outputs of each step; collapsible, streamed in real time.
  - **Feedback / chat:** a chat thread scoped to this article only.
  - **Versions:** revision history with diff view and "restore this version".
- Top bar: status badge, Generate / Regenerate, Approve, Publish, Unpublish.
- **Inline comments:** select text in the draft and comment on it (like Google
  Docs), e.g. "this claim needs a source". Comments can be sent to the AI
  individually or batched with a general feedback message.

## 3. Per-article AI session
- Each article has its own isolated AI session: brief, research notes, every
  draft version, all feedback and comments, agent outputs.
- Feedback gives agents the full context of that article's session and nothing
  from other articles.
- Sessions persist in the database; the editor can leave and continue days later.
- Context management: when a session grows long, summarise older turns, keeping
  the brief, latest draft, sources and unresolved feedback verbatim.
- Revisions edit the existing draft according to the feedback; they do not
  rewrite from scratch unless asked. Untouched sections stay unchanged.

## 4. Agent pipeline
An orchestrator coordinates subagents:
1. **Orchestrator:** reads the brief, plans, dispatches subagents, assembles the
   result, decides when the draft is ready.
2. **Researcher:** web search/fetch for facts, data, quotes, background;
   structured research notes with source URLs.
3. **Analyst / Angle:** the analytical argument — thesis, context, multiple
   perspectives, implications.
4. **Outliner:** headline options, dek, section headings, key points per section.
5. **Writer:** the full article from outline and research, following the house
   style guide.
6. **Fact-checker:** checks every factual claim against research and sources;
   flags unsupported or uncertain claims. The draft cannot be "ready for review"
   while unresolved high-severity flags remain.
7. **Editor:** clarity, flow, balance, tone, length; enforces the style guide.
8. **Headline & SEO:** final headline options, meta description, slug, tags.

Revision flow: the orchestrator decides which agents rerun. A tone comment may
need only the Editor; "add more data on X" needs Researcher → Writer →
Fact-checker. Don't rerun the whole pipeline unnecessarily.

Requirements:
- Anthropic Claude API with tool use for web search. Model per agent
  configurable, not hardcoded.
- Agent definitions (name, role, system prompt, model, tools, temperature)
  stored and editable in the admin.
- A global house style guide and per-section guidelines, editable in admin,
  injected into the relevant agents' prompts.
- Every article stores its sources, shown at the end and linked to the claims
  they support where practical.

## 5. Human in the loop
- Default flow: brief → agents → draft "Ready for review" → approve → publish.
- Nothing publishes automatically in v1; a per-section auto-publish setting
  exists for the future, default off.
- Fact-check flags and uncertain claims are shown prominently so review takes
  minutes, not a full read.

## 6. Execution and reliability
- Agent runs in background jobs, not in the web request.
- Progress streamed to the workspace (SSE or WebSockets).
- Log each step: input summary, output, tokens, cost estimate, duration, errors.
- Retry transient API errors, allow retrying a failed step, never lose a
  completed draft.
- No two conflicting runs on the same article (lock or queue).
- Token usage and estimated cost per article and per run.

## 7. Data model (suggested)
Topic, Article (topic, section, status, current_version, brief fields,
published_at), ArticleVersion (number, headline, dek, body, sources,
created_by agent/human, change summary), ArticleSession (conversation +
rolling summary), SessionMessage (role, content, linked version, timestamps),
InlineComment (version, text anchor/selection range, comment, status
open/sent/resolved), AgentDefinition, AgentRun and AgentStep, Source (url,
title, publisher, accessed_at, linked claims), StyleGuide (global + per
section). Inline comments must anchor correctly after a revision; if the
passage changed, mark the comment "outdated" rather than losing it.

## 8. Acceptance criteria
- Create a topic, open its workspace, write a brief, click Generate, watch
  agents work live.
- A complete draft with headline, dek, body and sources appears, with
  fact-check flags visible.
- General feedback in the chat and inline comments on selected text; the AI
  revises only what's needed; a new version appears with a diff.
- Leaving and returning preserves the full session.
- Feedback on article A never affects article B's session.
- Agent prompts, models and style guides editable in admin.
- Nothing publishes without approval.
- Tests for: pipeline orchestration (LLM mocked), session isolation,
  versioning, comment anchoring.

## 9. Build order and check-ins
1 data models → 2 static workspace with versions and brief → 3 background job
+ single-agent generation → 4 streaming → 5 full pipeline + fact-checker →
6 feedback chat + targeted revisions → 7 inline comments → 8 admin-editable
agents and style guides → 9 cost tracking, polish, tests.
Check in with the owner after steps 3, 5 and 7.

## Changes since the brief (owner's later decisions)
- Agents also **suggest** topics (scout is core, with ready briefs); the editor
  mainly approves. Build the scout right after the full pipeline.
- Voice is **highly personal**: strong publication voice (Economist named
  columns), talks to "you", takes a line; never "I", never invented experiences.
- Agent settings use effort + max tokens instead of temperature (current Claude
  models reject sampling parameters).
- No Anthropic API key yet: everything is built and demoed with
  NEWSDESK_WRITER=fake.
- The product becomes a paid publication: reader accounts, paywall, Razorpay
  subscriptions, ads for free readers, licensed never-repeated images, live
  blogs. See docs/DEPLOYMENT.md and docs/BUILD_PLAYBOOK.md.
