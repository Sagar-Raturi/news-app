"""StreamField blocks for standard pages (About, policies, Contact)."""

from wagtail import blocks

from news.blocks import ArticleBodyBlock


class ContactDetailsBlock(blocks.StructBlock):
    """Publisher contact details from Settings → Site settings, so every page shows the same, current ones."""

    kind = blocks.ChoiceBlock(
        choices=[
            ("publisher", "Publisher (legal name, address, email, phone)"),
            ("grievance", "Grievance Officer"),
            ("privacy", "Personal data questions"),
            ("corrections", "Corrections"),
        ],
        default="publisher",
    )

    class Meta:
        icon = "mail"
        template = "core/blocks/contact_details.html"
        help_text = "Shows details from Settings → Site settings → Publisher details."


class RecentCorrectionsBlock(blocks.StructBlock):
    count = blocks.IntegerBlock(default=20, min_value=1, max_value=100)

    class Meta:
        icon = "list-ul"
        template = "core/blocks/recent_corrections.html"
        help_text = "The latest correction notes added to published articles."

    def get_context(self, value, parent_context=None):
        from news.models import ArticleCorrection

        context = super().get_context(value, parent_context)
        context["corrections"] = (
            ArticleCorrection.objects.filter(page__live=True)
            .select_related("page")
            .order_by("-date", "-pk")[: value["count"]]
        )
        return context


class StandardPageBodyBlock(ArticleBodyBlock):
    contact_details = ContactDetailsBlock()
    recent_corrections = RecentCorrectionsBlock()
