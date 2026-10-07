from django import forms

from .models import ArticleWorkspace, DeskAgent, Topic

BRIEF_FIELDS = [
    "article_type",
    "brief",
    "target_words",
    "angle",
    "tone",
    "audience",
    "must_include",
    "sources_to_use",
    "sources_to_avoid",
    "byline",
]

TEXTAREA_ROWS = {"brief": 5, "angle": 3, "must_include": 3, "sources_to_use": 3, "sources_to_avoid": 2}


class BriefForm(forms.ModelForm):
    class Meta:
        model = ArticleWorkspace
        fields = BRIEF_FIELDS
        widgets = {name: forms.Textarea(attrs={"rows": rows}) for name, rows in TEXTAREA_ROWS.items()}


class NewArticleForm(BriefForm):
    """Start an article: pick a topic or create one, then write the brief."""

    topic = forms.ModelChoiceField(
        queryset=Topic.objects.exclude(status__in=[Topic.Status.ARCHIVED, Topic.Status.REJECTED]),
        required=False,
        help_text="Pick an existing topic, or leave blank and name a new one below",
    )
    new_topic = forms.CharField(label="New topic", max_length=200, required=False)
    desk = forms.ModelChoiceField(
        label="Section",
        queryset=DeskAgent.objects.filter(active=True),
        required=False,
        help_text="Needed for a new topic",
    )

    class Meta(BriefForm.Meta):
        fields = ["topic", "new_topic", "desk"] + BRIEF_FIELDS

    field_order = ["topic", "new_topic", "desk"] + BRIEF_FIELDS

    def clean(self):
        data = super().clean()
        if not data.get("topic"):
            if not data.get("new_topic", "").strip():
                self.add_error("new_topic", "Pick a topic or name a new one.")
            if not data.get("desk"):
                self.add_error("desk", "Choose a section for the new topic.")
        return data

    def save(self, user):
        data = self.cleaned_data
        topic = data.get("topic")
        if topic is None:
            topic = Topic.objects.create(
                title=data["new_topic"].strip(), desk=data["desk"], status=Topic.Status.ACCEPTED, created_by=user
            )
        workspace = super().save(commit=False)
        workspace.topic = topic
        workspace.desk = topic.desk
        workspace.created_by = user
        workspace.save()
        topic.article_started()
        return workspace
