"""Turning the orchestrator's plan into steps the runner will execute.

The orchestrator decides which agents run and what each should do; code
enforces the rules it must not get wrong:
- only active agents run;
- a new draft (Generate) always includes the writer, in a sensible order;
- the fact-checker always runs after the last change to the text (the
  orchestrator never needs to plan it).
"""

ROLE_FOR = {
    "plan": "orchestrator",
    "research": "researcher",
    "analyse": "analyst",
    "outline": "outliner",
    "write": "writer",
    "revise": "writer",
    "edit": "editor",
    "fact_check": "fact_checker",
    "seo": "seo",
}
ORDER = ["research", "analyse", "outline", "write", "revise", "edit", "seo"]
CONTENT_TASKS = {"write", "revise", "edit"}

FIRST_DRAFT = [
    ("research", "Gather the facts, latest data, background and the main competing views for the brief."),
    ("analyse", "Build the argument from the research."),
    ("outline", "Structure the article from the analysis."),
    ("write", "Write the complete article from the outline, analysis and research."),
    ("edit", "Edit for clarity, voice, balance and length."),
    ("seo", "Final headline, meta description, slug and tags."),
]

LABELS = {
    "plan": "plan",
    "research": "research",
    "analyse": "analysis",
    "outline": "outline",
    "write": "writing",
    "revise": "revision",
    "edit": "editing",
    "fact_check": "fact-check",
    "seo": "headline & SEO",
}


def item(task, instructions="", blocks=(), **extra):
    return {"role": ROLE_FOR[task], "task": task, "instructions": instructions, "blocks": list(blocks), **extra}


def with_fact_check(items):
    """Insert a fact-check after the last step that changes the text."""
    last = max((i for i, it in enumerate(items) if it["task"] in CONTENT_TASKS), default=None)
    if last is None:
        return items
    return items[: last + 1] + [item("fact_check", "Check every factual claim in the draft.")] + items[last + 1 :]


def default_first_draft(active_roles):
    return with_fact_check(
        [item(task, text) for task, text in FIRST_DRAFT if task == "write" or ROLE_FOR[task] in active_roles]
    )


def validate(plan_steps, *, fresh, active_roles):
    """Plan steps from the orchestrator -> run.plan items.

    `fresh` is True when the run writes a whole new draft (first draft or a
    full rewrite on request); otherwise the run revises the current draft.
    """
    steps = [s for s in plan_steps if s.task in ROLE_FOR and (s.task in ("write", "revise") or ROLE_FOR[s.task] in active_roles)]
    if fresh:
        chosen = {}
        for s in steps:
            if s.task != "revise":
                chosen.setdefault(s.task, s)
        if "write" not in chosen:
            return default_first_draft(active_roles)
        items = [item(task, chosen[task].instructions, chosen[task].blocks) for task in ORDER if task in chosen]
    else:
        items = [item(s.task, s.instructions, s.blocks) for s in steps]
    return with_fact_check(items)


def describe(items):
    return " → ".join(LABELS.get(it["task"], it["task"]) for it in items)
