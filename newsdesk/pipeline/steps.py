"""What each agent does in a run. Mixed into Pipeline (runner.py).

Every handler takes (step, draft) and returns the working draft (unchanged if
the agent doesn't edit text). Outputs worth keeping go in step.output; a
one-line step.summary appears in the activity feed and the change summary.
"""

import re

from django.utils import timezone

from newsdesk.content import word_count
from newsdesk.models import AgentDefinition, AgentRun, FactCheckFlag, Finding, NewsroomAISettings, SessionMessage, Source

from . import drafts, planning
from .context import block_refs, brief_block, draft_block, sources_block, target_length
from .llm import AgentError, server_tools
from .schemas import RECORD_FINDING_TOOL, Analysis, Edits, FactCheck, FullDraft, Outline, Plan, Seo

DOMAIN = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", re.I)


def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def seen_urls(blocks):
    """URLs the agent actually got back from web search or web fetch."""
    urls = set()
    for block in blocks:
        kind = _get(block, "type", "")
        content = _get(block, "content")
        if kind == "web_search_tool_result" and isinstance(content, list):
            urls.update(_get(result, "url") for result in content)
        elif kind == "web_fetch_tool_result" and content is not None:
            urls.add(_get(content, "url"))
    return {url.rstrip("/") for url in urls if url}


def _normal(text):
    return " ".join((text or "").split()).casefold()


def user(text):
    return [{"role": "user", "content": text}]


class AgentSteps:
    # -- helpers -----------------------------------------------------------------

    def output_of(self, task):
        """The latest finished output of a task earlier in this run."""
        for step in self.run.steps.filter(status="succeeded").order_by("-sequence"):
            if self.run.plan[step.sequence - 1].get("task") == task:
                return step.output or {}
        return {}

    def known_sources(self):
        return set(self.workspace.sources.values_list("number", flat=True))

    def accepted_claims(self):
        return list(
            FactCheckFlag.objects.filter(workspace=self.workspace, status=FactCheckFlag.Status.DISMISSED)
            .values_list("claim", flat=True)
            .distinct()
        )

    def require(self, draft, task):
        if draft is None:
            raise AgentError(f"There is no draft yet for the {task} step to work on.")

    # -- orchestrator ----------------------------------------------------------

    def step_plan(self, step, draft):
        ws = self.workspace
        fresh = self.run.kind == AgentRun.Kind.GENERATE
        active = set(AgentDefinition.objects.filter(active=True).values_list("role", flat=True))
        team = "\n".join(
            f"- {a.role}: {a.description}" for a in AgentDefinition.objects.filter(active=True).exclude(role__in=["orchestrator", "summariser", "scout"])
        )
        if fresh and draft is None:
            task = "Plan the first draft of this article."
        elif fresh:
            task = "The editor asked for a completely new draft from scratch. Plan it (the current draft is shown for reference only)."
        else:
            task = "Plan a revision of the current draft that addresses the editor's feedback below, using as few agents as possible."
        parts = [brief_block(ws), f"Sources so far: {ws.sources.count()}."]
        if draft is not None:
            parts.append(draft_block(draft))
        feedback = self.feedback_block()
        if feedback:
            parts.append(feedback)
        parts.append(f"Available agents:\n{team}")
        parts.append(task)
        response = self.call(step, "orchestrator", user("\n\n".join(parts)), output_format=Plan, input_summary=task)
        items = planning.validate(response.parsed.steps, fresh=fresh, active_roles=active)
        if not items:
            raise AgentError("The orchestrator didn't plan any work. Rephrase the feedback and try again.")
        self.run.plan = self.run.plan[: step.sequence] + items
        self.run.save(update_fields=["plan"])
        message = response.parsed.message_to_editor.strip()
        step.output = {"plan": items, "message": message}
        step.summary = f"Plan: {planning.describe(items)}."
        if message:
            SessionMessage.objects.create(
                session=ws.session, role=SessionMessage.Role.ORCHESTRATOR, content=message, run=self.run
            )
        return draft

    def feedback_block(self):
        """The editor's feedback for this run (revision runs; filled in by the feedback chat)."""
        trigger = self.run.trigger
        if trigger is None:
            return ""
        return f"<editor_feedback>\n{trigger.content.strip()}\n</editor_feedback>"

    # -- researcher --------------------------------------------------------------

    def step_research(self, step, draft):
        ws = self.workspace
        agent = AgentDefinition.for_role("researcher")
        tools = server_tools(agent)
        avoid = sorted({d.lower() for d in DOMAIN.findall(ws.sources_to_avoid)})
        for tool in tools:
            if avoid and tool["name"] in ("web_search", "web_fetch"):
                tool["blocked_domains"] = avoid
        tools.append(RECORD_FINDING_TOOL)
        recorded = []

        def record_finding(data):
            text = (data.get("text") or "").strip()
            if not text:
                raise ValueError("A finding needs text.")
            url = (data.get("url") or "").strip()
            if url and not url.startswith(("http://", "https://")):
                raise ValueError("The url must start with http:// or https://")
            source = Source.record(
                ws, url=url, title=data.get("title", ""), publisher=data.get("publisher", ""), origin=Source.Origin.SEARCH
            )
            kind = data.get("kind") if data.get("kind") in Finding.Kind.values else Finding.Kind.FACT
            finding = Finding.objects.create(
                workspace=ws, source=source, kind=kind, text=text, detail=(data.get("detail") or "").strip(), step=step
            )
            recorded.append(finding)
            return f"Saved as [S{source.number}]."

        message = "\n\n".join(
            [
                brief_block(ws),
                sources_block(ws),
                f"Task from the orchestrator: {step.instructions}",
                "Research the brief. Record every finding with the record_finding tool as you go.",
            ]
        )
        response = self.call(
            step, "researcher", user(message), tools=tools, tool_handlers={"record_finding": record_finding},
            input_summary="Brief and editor's material",
        )
        # Keep only findings whose page the researcher actually retrieved (or the editor supplied).
        allowed = seen_urls(response.blocks) | {
            u.rstrip("/") for u in ws.sources.filter(origin=Source.Origin.EDITOR).exclude(url="").values_list("url", flat=True)
        }
        dropped = 0
        for finding in recorded:
            url = (finding.source.url if finding.source else "").rstrip("/")
            if url and url not in allowed:
                source = finding.source
                finding.delete()
                if not source.findings.exists() and source.origin != Source.Origin.EDITOR:
                    source.delete()
                dropped += 1
        kept = len(recorded) - dropped
        step.output = {"notes": response.text.strip(), "findings": kept, "dropped": dropped}
        step.summary = f"Recorded {kept} finding{'s' if kept != 1 else ''} from {ws.sources.count()} sources" + (
            f"; dropped {dropped} with links it hadn't opened." if dropped else "."
        )
        return draft

    # -- analyst and outliner ------------------------------------------------------

    def step_analyse(self, step, draft):
        ws = self.workspace
        message = "\n\n".join([brief_block(ws), sources_block(ws), f"Task from the orchestrator: {step.instructions}"])
        response = self.call(step, "analyst", user(message), output_format=Analysis, input_summary="Brief and research")
        analysis = response.parsed
        step.output = {"analysis": analysis.model_dump()}
        step.summary = f"Thesis: {analysis.thesis}"
        return draft

    def analysis_text(self):
        analysis = self.output_of("analyse").get("analysis")
        if not analysis:
            return ""
        views = "\n".join(f"- {p['view']} ({p['evidence']})" for p in analysis["perspectives"])
        return (
            f"<analysis>\nThesis: {analysis['thesis']}\nContext: {analysis['context']}\nPerspectives:\n{views}\n"
            f"Implications: {analysis['implications']}\nUncertainties: {analysis['uncertainties']}\n</analysis>"
        )

    def step_outline(self, step, draft):
        ws = self.workspace
        message = "\n\n".join(
            [brief_block(ws), self.analysis_text(), sources_block(ws, with_findings=False),
             f"Target length: {target_length(ws)}", f"Task from the orchestrator: {step.instructions}"]
        )
        response = self.call(step, "outliner", user(message), output_format=Outline, input_summary="Brief and analysis")
        outline = response.parsed
        step.output = {"outline": outline.model_dump()}
        first = outline.headline_options[0] if outline.headline_options else ""
        step.summary = f"{len(outline.sections)} sections" + (f"; working headline “{first}”." if first else ".")
        return draft

    def outline_text(self):
        outline = self.output_of("outline").get("outline")
        if not outline:
            return ""
        sections = "\n".join(
            f"- {s['heading'] or '(opening)'} (~{s['words']} words): " + "; ".join(s["points"]) for s in outline["sections"]
        )
        extras = "\n".join(f"- {e}" for e in outline["extras"])
        return (
            f"<outline>\nHeadline options: {' | '.join(outline['headline_options'])}\n"
            f"Standfirst: {outline['standfirst']}\nSections:\n{sections}\n"
            + (f"Extras:\n{extras}\n" if extras else "")
            + "</outline>"
        )

    # -- writer ------------------------------------------------------------------

    def step_write(self, step, draft):
        """Writer: a complete article (first draft, or a full rewrite on request)."""
        ws = self.workspace
        message = "\n\n".join(
            part
            for part in [
                brief_block(ws),
                self.analysis_text(),
                self.outline_text(),
                sources_block(ws),
                f"Task from the orchestrator: {step.instructions}",
                f"Write the complete article. Target length: {target_length(ws)} Cite the sources above by "
                "their markers, e.g. [S2], after each claim they support; use no facts beyond them. If the "
                "material is thin, write a shorter piece and say what is missing in your notes.",
            ]
            if part
        )
        response = self.call(step, "writer", user(message), output_format=FullDraft, input_summary="Brief, analysis, outline, sources")
        try:
            new = drafts.from_full_draft(response.parsed, self.known_sources(), previous=draft)
        except ValueError as exc:
            raise AgentError(str(exc))
        step.output = {"notes": response.parsed.notes}
        step.summary = (
            f"Wrote “{new['headline']}” ({word_count(new['body'])} words, {len(new['source_numbers'])} sources cited)."
        )
        return new

    # -- targeted edits: writer revisions and the editor ---------------------------

    def _edit(self, step, draft, role, task_text):
        self.require(draft, step.role)
        ws = self.workspace
        item = self.run.plan[step.sequence - 1]
        targets = ", ".join(item.get("blocks") or [])
        parts = [
            brief_block(ws),
            sources_block(ws),
            draft_block(draft),
            f"Target length: {target_length(ws)}",
            f"Task from the orchestrator: {step.instructions}",
        ]
        if targets:
            parts.append(f"Blocks to work on: {targets}. Leave every other block alone.")
        feedback = self.feedback_block()
        if feedback:
            parts.append(feedback)
        parts.append(task_text)
        response = self.call(step, role, user("\n\n".join(parts)), output_format=Edits, input_summary="Draft, brief and sources")
        try:
            new, skipped = drafts.apply_edits(draft, response.parsed, self.known_sources())
        except ValueError as exc:
            raise AgentError(str(exc))
        changed = len(response.parsed.edits) - len(skipped)
        step.output = {"notes": response.parsed.notes, "skipped": skipped}
        step.summary = f"Changed {changed} block{'s' if changed != 1 else ''}" + (
            f", headline" if response.parsed.headline.strip() else ""
        ) + (f"; skipped {len(skipped)} edit{'s' if len(skipped) != 1 else ''}." if skipped else ".")
        return new

    def step_revise(self, step, draft):
        return self._edit(
            step, draft, "writer",
            "Revise the draft with targeted edits to the blocks that need them. Return only the edits; "
            "blocks you don't mention stay exactly as they are.",
        )

    def step_edit(self, step, draft):
        return self._edit(
            step, draft, "editor",
            "Edit the draft with targeted edits. Return only the edits; blocks you don't mention stay exactly as they are.",
        )

    # -- fact-checker --------------------------------------------------------------

    def step_fact_check(self, step, draft):
        self.require(draft, "fact-check")
        ws = self.workspace
        accepted = self.accepted_claims()
        parts = [draft_block(draft), sources_block(ws)]
        if accepted:
            parts.append(
                "The editor has checked and accepted these claims; do not flag them again:\n"
                + "\n".join(f"- {claim}" for claim in accepted)
            )
        parts.append("Check every factual claim in the draft against the sources and findings above.")
        response = self.call(step, "fact_checker", user("\n\n".join(parts)), output_format=FactCheck, input_summary="Draft and research")
        refs = block_refs(draft)
        known = self.known_sources()
        accepted_normal = {_normal(c) for c in accepted}
        flags = [
            {
                "block_id": refs.get(flag.block.strip().upper(), ""),
                "claim": flag.claim.strip(),
                "severity": flag.severity,
                "issue": flag.issue.strip(),
                "suggestion": flag.suggestion.strip(),
                "sources": [n for n in flag.sources if n in known],
                "ref": flag.block.strip().upper(),
            }
            for flag in response.parsed.flags
            if flag.claim.strip() and _normal(flag.claim) not in accepted_normal
        ]
        high = [f for f in flags if f["severity"] == "high"]
        step.output = {"summary": response.parsed.summary, "flags": flags}
        counts = ", ".join(
            f"{sum(1 for f in flags if f['severity'] == s)} {s}" for s in ("high", "medium", "low") if any(f["severity"] == s for f in flags)
        )
        step.summary = f"{len(flags)} flag{'s' if len(flags) != 1 else ''}" + (f" ({counts})." if counts else ": the draft checks out.")

        rounds = sum(1 for it in self.run.plan if it.get("fix"))
        if high and rounds < NewsroomAISettings.load().max_fix_rounds:
            issues = "\n".join(f"- {f['ref'] or 'headline/standfirst'}: “{f['claim']}”: {f['issue']} {f['suggestion']}".strip() for f in high)
            fix = [
                planning.item(
                    "revise",
                    f"Fix these serious fact-check flags, changing only what is needed:\n{issues}",
                    sorted({f["ref"] for f in high if f["ref"]}),
                    fix=True,
                ),
                planning.item("fact_check", "Check the draft again after the fixes."),
            ]
            self.run.plan = self.run.plan[: step.sequence] + fix + self.run.plan[step.sequence :]
            self.run.save(update_fields=["plan"])
            step.summary += " Sending the serious ones back to the writer."
        return draft

    # -- headline & SEO --------------------------------------------------------------

    def step_seo(self, step, draft):
        self.require(draft, "SEO")
        ws = self.workspace
        message = "\n\n".join([brief_block(ws), draft_block(draft), f"Task from the orchestrator: {step.instructions}"])
        response = self.call(step, "seo", user(message), output_format=Seo, input_summary="Draft")
        seo = response.parsed
        new = {**draft, "seo": {**draft.get("seo", {}), "headline_options": seo.headline_options,
                                "meta_description": seo.meta_description[:300], "slug": seo.slug[:80]}}
        if seo.headline.strip():
            new["headline"] = drafts.CITATION.sub("", seo.headline).strip()[:255]
        tags = [t.strip()[:100] for t in seo.tags if t.strip()][:4]
        if tags:
            new["tags"] = tags
        step.output = {"seo": seo.model_dump()}
        step.summary = f"Headline: “{new['headline']}”; {len(seo.headline_options)} options."
        return new

    # -- flags on the saved version ------------------------------------------------------

    def save_flags(self, version):
        """Attach the latest fact-check (if it saw the final text) to the version."""
        steps = list(self.run.steps.filter(status="succeeded").order_by("sequence"))
        task_of = {s.sequence: self.run.plan[s.sequence - 1].get("task") for s in steps}
        last_content = max((s.sequence for s in steps if task_of[s.sequence] in planning.CONTENT_TASKS), default=0)
        checks = [s for s in steps if task_of[s.sequence] == "fact_check" and s.sequence > last_content]
        if not checks:
            if version is not None and version.based_on_id:
                self.carry_flags(version.based_on, version)
            return []
        target = version or self.workspace.current_version
        if target is None:
            return []
        target.flags.filter(status=FactCheckFlag.Status.OPEN).update(
            status=FactCheckFlag.Status.FIXED, resolved_at=timezone.now()
        )
        block_ids = {b["id"] for b in target.body}
        created = []
        for data in checks[-1].output.get("flags", []):
            block_id = data["block_id"] if data["block_id"] in block_ids else ""
            flag = FactCheckFlag.objects.create(
                workspace=self.workspace, version=target, block_id=block_id, claim=data["claim"],
                severity=data["severity"], issue=data["issue"], suggestion=data["suggestion"], step=checks[-1],
            )
            flag.sources.set(self.workspace.sources.filter(number__in=data["sources"]))
            created.append(flag)
        return created

    def carry_flags(self, previous, version):
        """No fact-check this run: flags on passages that didn't change still apply."""
        from newsdesk.content import block_text

        old = {b["id"]: block_text(b) for b in previous.body}
        new = {b["id"]: block_text(b) for b in version.body}
        for flag in previous.flags.filter(status__in=[FactCheckFlag.Status.OPEN, FactCheckFlag.Status.DISMISSED]):
            if flag.block_id and (flag.block_id not in new or old.get(flag.block_id) != new[flag.block_id]):
                continue
            sources = list(flag.sources.all())
            flag.pk = None
            flag.version = version
            flag.save()
            flag.sources.set(sources)
