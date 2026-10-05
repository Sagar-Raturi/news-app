from wagtail import blocks
from wagtail.contrib.table_block.blocks import TableBlock
from wagtail.embeds.blocks import EmbedBlock
from wagtail.images.blocks import ImageChooserBlock

RICH_TEXT_FEATURES = ["bold", "italic", "link", "ol", "ul"]


class ImageBlock(blocks.StructBlock):
    image = ImageChooserBlock()
    caption = blocks.CharBlock(required=False)
    credit = blocks.CharBlock(required=False)

    class Meta:
        icon = "image"
        template = "news/blocks/image.html"


class PullQuoteBlock(blocks.StructBlock):
    quote = blocks.TextBlock()
    attribution = blocks.CharBlock(required=False)

    class Meta:
        icon = "openquote"
        template = "news/blocks/pullquote.html"


class KeyPointsBlock(blocks.StructBlock):
    title = blocks.CharBlock(default="Key points")
    points = blocks.ListBlock(blocks.CharBlock(label="Point"))

    class Meta:
        icon = "list-ul"
        template = "news/blocks/key_points.html"


class QuestionAnswerBlock(blocks.StructBlock):
    """Explainer-style question with a rich-text answer."""

    question = blocks.CharBlock()
    answer = blocks.RichTextBlock(features=RICH_TEXT_FEATURES)

    class Meta:
        icon = "help"
        label = "Q&A"
        template = "news/blocks/qa.html"


class StatBlock(blocks.StructBlock):
    figure = blocks.CharBlock(help_text="The number, e.g. ‘6.5%’ or ‘₹1.2 lakh crore’")
    label = blocks.CharBlock(help_text="What the number measures")
    source = blocks.CharBlock(required=False)

    class Meta:
        icon = "pick"
        label = "Key figure"
        template = "news/blocks/stat.html"


class CalloutBlock(blocks.StructBlock):
    title = blocks.CharBlock()
    body = blocks.RichTextBlock(features=RICH_TEXT_FEATURES)

    class Meta:
        icon = "info-circle"
        label = "Fact box"
        template = "news/blocks/callout.html"


class ArticleBodyBlock(blocks.StreamBlock):
    paragraph = blocks.RichTextBlock(features=RICH_TEXT_FEATURES, template="news/blocks/paragraph.html")
    heading = blocks.CharBlock(icon="title", template="news/blocks/heading.html")
    image = ImageBlock()
    pullquote = PullQuoteBlock()
    key_points = KeyPointsBlock()
    qa = QuestionAnswerBlock()
    stat = StatBlock()
    callout = CalloutBlock()
    embed = EmbedBlock(icon="media", template="news/blocks/embed.html")
    table = TableBlock(template="news/blocks/table.html")


class SourceBlock(blocks.StructBlock):
    title = blocks.CharBlock()
    publisher = blocks.CharBlock(required=False)
    url = blocks.URLBlock(required=False)
    note = blocks.CharBlock(required=False)

    class Meta:
        icon = "link"
        template = "news/blocks/source.html"


class SourcesBlock(blocks.StreamBlock):
    source = SourceBlock()
